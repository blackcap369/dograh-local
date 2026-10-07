"""Agency roles: the owner identity and staff-assignment authorization.

V2.1a/V2.1b. Two questions are separated here, and the tests keep them
separate on purpose:

- "What is this account?" -- resolve_agency_role (OWNER_EMAILS) and the
  one-way promotion. The owner sees and can enter every business.
- "May this account touch THIS business from the agency surface?" -- staff
  pass only with a staff_client_assignments row, re-derived per request.

The owner tests live in test_agency_clients.py (whose fixture defaults to the
owner role); this file is the staff side of the wall and the promotion logic.

Same conventions as test_agency_clients.py: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import agency, organization

STAFF_ID = 20
STAFF_PROVIDER = "user_staff"
OWNER_ID = 10
OWNER_PROVIDER = "user_owner"

ACME = SimpleNamespace(
    id=1, provider_id="org_oss_1_acme", name="Acme Dental", archived=False
)
GLOBEX = SimpleNamespace(
    id=2, provider_id="org_oss_2_globex", name="Globex Legal", archived=False
)


def _make_agency_app(user_id: int, agency_role: str, org_id: int | None = None):
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=STAFF_PROVIDER if agency_role == "staff" else OWNER_PROVIDER,
        email=f"{agency_role}@agency.test",
        selected_organization_id=org_id,
        agency_role=agency_role,
    )
    return app


def _patched_db(assigned: bool = False) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.list_all_organizations = AsyncMock(return_value=[ACME, GLOBEX])
    mock_db.list_organizations_for_staff = AsyncMock(return_value=[ACME])
    mock_db.get_organization_resource_counts = AsyncMock(return_value={})
    mock_db.is_user_assigned_to_organization = AsyncMock(return_value=assigned)
    mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
    return mock_db


# =============================================================================
# Role resolution and promotion
# =============================================================================


class TestRoleResolution:
    """resolve_agency_role reads OWNER_EMAILS; promotion is one-way."""

    def test_owner_email_resolves_to_owner(self):
        from api.services import agency_access

        with patch.object(agency_access, "OWNER_EMAILS", {"owner@agency.test"}):
            assert agency_access.resolve_agency_role("Owner@Agency.Test") == "owner"

    def test_any_other_email_resolves_to_staff(self):
        from api.services import agency_access

        with patch.object(agency_access, "OWNER_EMAILS", {"owner@agency.test"}):
            assert agency_access.resolve_agency_role("someone@agency.test") == "staff"

    def test_no_owner_configured_means_everyone_is_staff(self):
        """The empty-env default must be fail-closed, not fail-open."""
        from api.services import agency_access

        with patch.object(agency_access, "OWNER_EMAILS", set()):
            assert agency_access.resolve_agency_role("owner@agency.test") == "staff"

    @pytest.mark.asyncio
    async def test_promotion_upgrades_listed_email(self):
        from api.services import agency_access

        user = SimpleNamespace(
            id=OWNER_ID, email="owner@agency.test", agency_role="staff"
        )
        mock_db = AsyncMock()

        with patch.object(agency_access, "OWNER_EMAILS", {"owner@agency.test"}):
            with patch("api.db.db_client", mock_db):
                await agency_access.promote_to_owner_if_listed(user)

        mock_db.update_user_agency_role.assert_awaited_once_with(OWNER_ID, "owner")
        assert user.agency_role == "owner"

    @pytest.mark.asyncio
    async def test_promotion_never_demotes(self):
        """Removing an email from OWNER_EMAILS must not demote its owner.

        The check reads the stored role, not the env -- rotation of the env
        cannot silently strip the agency of its owner.
        """
        from api.services import agency_access

        user = SimpleNamespace(
            id=OWNER_ID, email="owner@agency.test", agency_role="owner"
        )
        mock_db = AsyncMock()

        with patch.object(agency_access, "OWNER_EMAILS", set()):
            with patch("api.db.db_client", mock_db):
                await agency_access.promote_to_owner_if_listed(user)

        mock_db.update_user_agency_role.assert_not_awaited()
        assert user.agency_role == "owner"

    @pytest.mark.asyncio
    async def test_promotion_ignores_unlisted_email(self):
        from api.services import agency_access

        user = SimpleNamespace(
            id=STAFF_ID, email="staff@agency.test", agency_role="staff"
        )
        mock_db = AsyncMock()

        with patch.object(agency_access, "OWNER_EMAILS", {"owner@agency.test"}):
            with patch("api.db.db_client", mock_db):
                await agency_access.promote_to_owner_if_listed(user)

        mock_db.update_user_agency_role.assert_not_awaited()


# =============================================================================
# The staff Clients page sees only assignments
# =============================================================================


class TestStaffListScoping:
    """`GET /agency/clients` is role-scoped at the query, not in the UI."""

    @pytest.mark.asyncio
    async def test_staff_lists_only_assigned_businesses(self):
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db(assigned=True)):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        ids = [c["id"] for c in response.json()]
        assert ids == [ACME.id], "staff must see only their assigned business"

    @pytest.mark.asyncio
    async def test_staff_scoping_happens_in_the_query(self):
        """The staff branch must ask the DB for assignments, not filter a full list.

        A Python-side filter over `list_all_organizations` would still pull every
        client's name over the wire inside the query result. The route must call
        the assignment-scoped read.
        """
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db(assigned=True)
        with patch("api.routes.agency.db_client", mock_db):
            client.get("/api/v1/agency/clients")

        mock_db.list_organizations_for_staff.assert_awaited_once_with(STAFF_ID)
        mock_db.list_all_organizations.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unassigned_staff_sees_an_empty_page_not_someone_elses(self):
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db(assigned=True)
        mock_db.list_organizations_for_staff = AsyncMock(return_value=[])
        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_owner_still_sees_every_business(self):
        app = _make_agency_app(OWNER_ID, "owner")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        ids = [c["id"] for c in response.json()]
        assert ids == [ACME.id, GLOBEX.id]


# =============================================================================
# Per-business routes are assignment-gated for staff
# =============================================================================


class TestStaffBusinessAccess:
    """Staff operate only on assigned businesses; owners on all of them."""

    @pytest.mark.asyncio
    async def test_staff_can_work_an_assigned_business(self):
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        # Two patch targets, both required: the route reads the module-level
        # db_client, while ensure_business_access lazily imports the singleton
        # from api.db -- the same mock must answer both.
        mock_db = _patched_db(assigned=True)
        mock_db.rename_organization = AsyncMock(
            return_value=SimpleNamespace(
                id=ACME.id, provider_id=ACME.provider_id, name="Renamed"
            )
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "Renamed"}
            )

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_staff_is_403_on_an_unassigned_business(self):
        """403, not 404: the business exists, the caller just may not touch it."""
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db(assigned=False)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "Renamed"}
            )

        assert response.status_code == 403, response.text

    @pytest.mark.asyncio
    async def test_assignment_is_rechecked_on_every_request(self):
        """A former assignment must stop working immediately.

        The access check must reach the database each call -- caching an
        earlier "yes" would let a revoked staff member keep working until some
        cache expired.
        """
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db(assigned=False)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            client.get(f"/api/v1/agency/clients/{ACME.id}/delete-impact")

        mock_db.is_user_assigned_to_organization.assert_awaited_once_with(
            STAFF_ID, ACME.id
        )

    @pytest.mark.asyncio
    async def test_owner_bypasses_the_assignment_check(self):
        app = _make_agency_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db(assigned=False)
        mock_db.rename_organization = AsyncMock(
            return_value=SimpleNamespace(
                id=ACME.id, provider_id=ACME.provider_id, name="Renamed"
            )
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "Renamed"}
            )

        assert response.status_code == 200, response.text
        mock_db.is_user_assigned_to_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_cannot_create_clients(self):
        """Onboarding a client is the agency owner's job, not any staff member's."""
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.post(
                "/api/v1/agency/clients", json={"name": "New Client"}
            )

        assert response.status_code == 403, response.text

    @pytest.mark.asyncio
    async def test_missing_business_is_404_even_for_staff(self):
        """404 before any access decision: probing for ids must not leak which
        businesses exist."""
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db(assigned=False)
        mock_db.get_organization_by_id = AsyncMock(return_value=None)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete("/api/v1/agency/clients/4242")

        assert response.status_code == 404, response.text


# =============================================================================
# The owner enters any business; staff still cannot
# =============================================================================


class TestSwitchByRole:
    """/organizations/switch: ownership is the power to stand in any business."""

    @pytest.mark.asyncio
    async def test_owner_can_switch_into_a_non_member_business(self):
        app = _make_agency_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = AsyncMock()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.get_organizations_for_user = AsyncMock(return_value=[])
        mock_db.update_user_selected_organization = AsyncMock()
        mock_db.ensure_organization_bootstrapped = AsyncMock()

        with patch("api.routes.organization.db_client", mock_db), patch(
            "api.routes.organization.ensure_organization_bootstrapped", AsyncMock()
        ), patch(
            "api.routes.organization.get_organization_context",
            AsyncMock(
                return_value=SimpleNamespace(
                    organization_id=ACME.id,
                    organization_provider_id=ACME.provider_id,
                    organization_name=ACME.name,
                    model_services=SimpleNamespace(
                        config_source="empty",
                        has_model_configuration_v2=False,
                        managed_service_version=None,
                        uses_managed_service_v2=False,
                    ),
                )
            ),
        ):
            response = client.post(
                "/api/v1/organizations/switch", json={"organization_id": ACME.id}
            )

        assert response.status_code == 200, response.text
        mock_db.update_user_selected_organization.assert_awaited_once_with(
            OWNER_ID, ACME.id
        )

    @pytest.mark.asyncio
    async def test_staff_still_cannot_switch_into_a_non_member_business(self):
        app = _make_agency_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = AsyncMock()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.get_organizations_for_user = AsyncMock(return_value=[])

        with patch("api.routes.organization.db_client", mock_db):
            response = client.post(
                "/api/v1/organizations/switch", json={"organization_id": ACME.id}
            )

        assert response.status_code == 403, response.text
