"""Agency staff management (V2.1c) and deletion requests (V2.1d).

Staff management is owner-only: create accounts, replace assignments,
reset passwords, suspend, delete. Deletion requests are the staff path to
removal: a staff member asks, nothing is destroyed, the owner approves
(running the impact-guarded delete) or rejects.

Every route here is a new authorization surface, so the owner-vs-staff
distinction is asserted per route -- not inherited from the fixture.

Same conventions as the other agency suites: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import agency

OWNER_ID = 10
STAFF_ID = 20
OTHER_STAFF_ID = 21

ACME = SimpleNamespace(
    id=1, provider_id="org_oss_1_acme", name="Acme Dental", archived=False
)
GLOBEX = SimpleNamespace(
    id=2, provider_id="org_oss_2_globex", name="Globex Legal", archived=False
)

STAFF_ACCOUNT = SimpleNamespace(
    id=STAFF_ID,
    provider_id="oss_staff",
    email="staff@agency.test",
    name="Staff Member",
    agency_role="staff",
    is_suspended=False,
    created_at=None,
)

OWNER_ACCOUNT = SimpleNamespace(
    id=OWNER_ID,
    provider_id="oss_owner",
    email="owner@agency.test",
    name="Owner",
    agency_role="owner",
    is_suspended=False,
    created_at=None,
)


def _make_app(user_id: int, agency_role: str):
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id="oss_caller",
        email="caller@agency.test",
        selected_organization_id=None,
        agency_role=agency_role,
    )
    return app


def _patched_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.list_staff_users = AsyncMock(return_value=[STAFF_ACCOUNT])
    mock_db.list_organizations_for_staff = AsyncMock(return_value=[ACME])
    mock_db.get_user_by_id = AsyncMock(return_value=STAFF_ACCOUNT)
    mock_db.get_user_by_email = AsyncMock(return_value=None)
    mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
    mock_db.create_user_with_email = AsyncMock(return_value=STAFF_ACCOUNT)
    mock_db.count_workflows_owned_by_user = AsyncMock(return_value=0)
    mock_db.get_organization_resource_counts = AsyncMock(return_value={})
    return mock_db


# =============================================================================
# Owner-only gate on every staff-management route
# =============================================================================


class TestStaffRoutesAreOwnerOnly:
    """A staff caller gets 403 from the whole staff-management surface."""

    STAFF_ROUTES = [
        ("get", "/api/v1/agency/staff", None),
        ("post", "/api/v1/agency/staff", {"email": "x@example.com", "password": "longenough1"}),
        ("patch", "/api/v1/agency/staff/20/suspended", {"suspended": True}),
        ("post", "/api/v1/agency/staff/20/reset-password", {"new_password": "longenough1"}),
        ("put", "/api/v1/agency/staff/20/assignments", {"organization_ids": [1]}),
        ("delete", "/api/v1/agency/staff/20", None),
        ("get", "/api/v1/agency/deletion-requests", None),
        ("post", "/api/v1/agency/deletion-requests/1/approve", None),
        ("post", "/api/v1/agency/deletion-requests/1/reject", None),
    ]

    @pytest.mark.asyncio
    async def test_staff_is_403_on_every_route(self):
        for method, url, body in self.STAFF_ROUTES:
            app = _make_app(STAFF_ID, "staff")
            client = TestClient(app)
            mock_db = _patched_db()
            with patch("api.routes.agency.db_client", mock_db), patch(
                "api.db.db_client", mock_db
            ):
                kwargs = {"json": body} if body is not None else {}
                response = getattr(client, method)(url, **kwargs)
            assert response.status_code == 403, (
                f"{method.upper()} {url} returned {response.status_code} for staff"
            )


# =============================================================================
# Staff accounts
# =============================================================================


class TestStaffAccounts:
    @pytest.mark.asyncio
    async def test_create_staff_account(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(
                "/api/v1/agency/staff",
                json={
                    "email": "new.hire@example.com",
                    "password": "longenough1",
                    "name": "New Hire",
                },
            )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == "staff@agency.test"  # mocked create returns fixture
        # A staff account is an access grant, not a tenant: no org creation,
        # no bootstrap call.
        mock_db.create_user_with_email.assert_awaited_once()
        args, kwargs = mock_db.create_user_with_email.await_args
        assert kwargs.get("agency_role") == "staff" or args[-1] == "staff"

    @pytest.mark.asyncio
    async def test_create_staff_rejects_duplicate_email(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_user_by_email = AsyncMock(return_value=STAFF_ACCOUNT)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(
                "/api/v1/agency/staff",
                json={"email": "staff@example.com", "password": "longenough1"},
            )

        assert response.status_code == 409, response.text

    @pytest.mark.asyncio
    async def test_create_staff_rejects_an_owner_email(self):
        """An OWNER_EMAILS address must not enter as staff: the one-way
        promotion would make it owner on first login."""
        from api.services import agency_access

        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        # The route reads OWNER_EMAILS through its own module-level import,
        # so that is the binding the test has to replace.
        with patch.object(agency_access, "OWNER_EMAILS", {"owner@example.com"}), patch(
            "api.routes.agency.OWNER_EMAILS", {"owner@example.com"}
        ):
            with patch("api.routes.agency.db_client", mock_db):
                response = client.post(
                    "/api/v1/agency/staff",
                    json={"email": "owner@example.com", "password": "longenough1"},
                )

        assert response.status_code == 400, response.text
        mock_db.create_user_with_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_refused_when_staff_built_agents(self):
        """workflows.user_id has no ondelete: the delete would abort mid-FK.
        The 409 surfaces the suspend alternative with the count."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.count_workflows_owned_by_user = AsyncMock(return_value=3)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/staff/{STAFF_ID}")

        assert response.status_code == 409, response.text
        assert "workflow_count" in str(response.json()["detail"])
        mock_db.delete_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_succeeds_for_an_account_without_agents(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.delete_user = AsyncMock(return_value=True)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/staff/{STAFF_ID}")

        assert response.status_code == 204, response.text
        mock_db.delete_user.assert_awaited_once_with(STAFF_ID)

    @pytest.mark.asyncio
    async def test_owner_account_is_not_manageable(self):
        """The owner is not staff; every staff-management route must refuse
        to treat the owner as a target."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_user_by_id = AsyncMock(return_value=OWNER_ACCOUNT)
        with patch("api.routes.agency.db_client", mock_db):
            suspend = client.patch(
                f"/api/v1/agency/staff/{OWNER_ID}/suspended", json={"suspended": True}
            )
            delete = client.delete(f"/api/v1/agency/staff/{OWNER_ID}")

        assert suspend.status_code == 400, suspend.text
        assert delete.status_code == 400, delete.text


# =============================================================================
# Assignments
# =============================================================================


class TestStaffAssignments:
    @pytest.mark.asyncio
    async def test_replace_assignments(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            response = client.put(
                f"/api/v1/agency/staff/{STAFF_ID}/assignments",
                json={"organization_ids": [ACME.id, GLOBEX.id]},
            )

        assert response.status_code == 200, response.text
        mock_db.set_staff_assignments.assert_awaited_once_with(
            STAFF_ID, [ACME.id, GLOBEX.id]
        )

    @pytest.mark.asyncio
    async def test_replace_deduplicates_ids(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            client.put(
                f"/api/v1/agency/staff/{STAFF_ID}/assignments",
                json={"organization_ids": [ACME.id, ACME.id]},
            )

        mock_db.set_staff_assignments.assert_awaited_once_with(STAFF_ID, [ACME.id])

    @pytest.mark.asyncio
    async def test_unknown_business_is_refused_before_any_write(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_organization_by_id = AsyncMock(return_value=None)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.put(
                f"/api/v1/agency/staff/{STAFF_ID}/assignments",
                json={"organization_ids": [4242]},
            )

        assert response.status_code == 404, response.text
        mock_db.set_staff_assignments.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_list_revokes_everything(self):
        """Saving an empty set is how access is removed from the page."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            response = client.put(
                f"/api/v1/agency/staff/{STAFF_ID}/assignments",
                json={"organization_ids": []},
            )

        assert response.status_code == 200, response.text
        mock_db.set_staff_assignments.assert_awaited_once_with(STAFF_ID, [])


# =============================================================================
# Suspension enforcement
# =============================================================================


class TestSuspensionEnforcement:
    """Suspension must take effect at the door and on every auth path."""

    @pytest.mark.asyncio
    async def test_suspended_staff_cannot_log_in(self):
        from api.routes import auth as auth_routes

        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/api/v1")

        suspended = SimpleNamespace(
            id=STAFF_ID,
            provider_id="oss_staff",
            email="staff@example.com",
            agency_role="staff",
            is_suspended=True,
            password_hash="$hashed",
        )
        mock_db = AsyncMock()
        mock_db.get_user_by_email = AsyncMock(return_value=suspended)

        with patch("api.routes.auth.db_client", mock_db), patch(
            "api.routes.auth.verify_password", AsyncMock(return_value=True)
        ), patch("api.constants.ENABLE_SIGNUP", True):
            client = TestClient(app)
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "staff@example.com", "password": "longenough1"},
            )

        assert response.status_code == 403, response.text
        assert "suspended" in response.text.lower()

    @pytest.mark.asyncio
    async def test_suspended_token_is_rejected(self):
        """An already-issued JWT dies at the next request."""
        from api.services.auth import depends as auth_depends

        suspended = SimpleNamespace(
            id=STAFF_ID,
            provider_id="oss_staff",
            email="staff@example.com",
            agency_role="staff",
            is_suspended=True,
            selected_organization_id=None,
        )
        mock_db = AsyncMock()
        mock_db.get_user_by_id = AsyncMock(return_value=suspended)

        with patch("api.services.auth.depends.db_client", mock_db), patch(
            "api.services.auth.depends.decode_jwt_token",
            lambda token: {"sub": str(STAFF_ID)},
        ), patch(
            "api.services.auth.depends.ensure_organization_bootstrapped", AsyncMock()
        ):
            with pytest.raises(Exception) as exc_info:
                await auth_depends._handle_oss_auth("Bearer some-token")

        assert "suspended" in str(exc_info.value).lower()


# =============================================================================
# Deletion requests
# =============================================================================


REQUEST_ROW = SimpleNamespace(
    id=1,
    organization_id=ACME.id,
    requested_by=STAFF_ID,
    status="pending",
    reason="client asked to leave",
    created_at=None,
)


class TestDeletionRequests:
    @pytest.mark.asyncio
    async def test_assigned_staff_can_request_deletion(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=True)
        mock_db.create_deletion_request = AsyncMock(return_value=REQUEST_ROW)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post(
                f"/api/v1/agency/clients/{ACME.id}/deletion-request",
                json={"reason": "client asked to leave"},
            )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert body["business_label"] == "Acme Dental"

    @pytest.mark.asyncio
    async def test_unassigned_staff_is_403(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=False)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post(
                f"/api/v1/agency/clients/{ACME.id}/deletion-request", json={}
            )

        assert response.status_code == 403, response.text
        mock_db.create_deletion_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_pending_request_is_409(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=True)
        mock_db.create_deletion_request = AsyncMock(
            side_effect=ValueError("A deletion request is already pending")
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post(
                f"/api/v1/agency/clients/{ACME.id}/deletion-request", json={}
            )

        assert response.status_code == 409, response.text

    @pytest.mark.asyncio
    async def test_owner_delete_is_owner_only_now(self):
        """Staff deletes are requests; the direct DELETE belongs to the owner."""
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=True)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.delete(f"/api/v1/agency/clients/{ACME.id}")

        assert response.status_code == 403, response.text

    @pytest.mark.asyncio
    async def test_approve_runs_the_guarded_delete(self):
        """Approval performs the same delete a direct owner action would:
        selection cleanup, membership cleanup, then the row -- and it is
        impact-guarded, so the empty fixture business goes through."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_deletion_request = AsyncMock(return_value=REQUEST_ROW)
        mock_db.resolve_deletion_request = AsyncMock(
            return_value=SimpleNamespace(
                id=REQUEST_ROW.id,
                organization_id=ACME.id,
                requested_by=STAFF_ID,
                status="approved",
                reason=REQUEST_ROW.reason,
                created_at=None,
            )
        )
        mock_db.get_organization_resource_counts = AsyncMock(
            return_value={
                ACME.id: {
                    "workflow_count": 0,
                    "run_count": 0,
                    "phone_number_count": 0,
                    "member_count": 1,
                }
            }
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/deletion-requests/1/approve")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "approved"
        mock_db.delete_organization.assert_awaited_once_with(ACME.id)

    @pytest.mark.asyncio
    async def test_approve_refused_for_a_business_with_history(self):
        """The impact guard is not bypassed by the approval path: a business
        with runs is refused with the counts, and the request stays pending
        so the owner can reject it or archive instead."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_deletion_request = AsyncMock(return_value=REQUEST_ROW)
        mock_db.get_organization_resource_counts = AsyncMock(
            return_value={
                ACME.id: {
                    "workflow_count": 4,
                    "run_count": 128,
                    "phone_number_count": 2,
                    "member_count": 3,
                }
            }
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/deletion-requests/1/approve")

        assert response.status_code == 409, response.text
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reject_leaves_the_business_alone(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_deletion_request = AsyncMock(return_value=REQUEST_ROW)
        mock_db.resolve_deletion_request = AsyncMock(
            return_value=SimpleNamespace(
                id=REQUEST_ROW.id,
                organization_id=ACME.id,
                requested_by=STAFF_ID,
                status="rejected",
                reason=REQUEST_ROW.reason,
                created_at=None,
            )
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/deletion-requests/1/reject")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "rejected"
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_resolved_request_cannot_be_redecided(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_deletion_request = AsyncMock(
            return_value=SimpleNamespace(
                id=1, organization_id=1, requested_by=STAFF_ID,
                status="approved", reason=None, created_at=None,
            )
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/deletion-requests/1/approve")

        assert response.status_code == 409, response.text

    @pytest.mark.asyncio
    async def test_clients_list_carries_the_pending_flag(self):
        """The badge travels on the list response, computed in one query for
        the whole list."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.list_all_organizations = AsyncMock(return_value=[ACME, GLOBEX])
        mock_db.list_organization_ids_with_pending_deletion = AsyncMock(
            return_value={ACME.id}
        )
        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        flags = {c["id"]: c["deletion_pending"] for c in response.json()}
        assert flags[ACME.id] is True
        assert flags[GLOBEX.id] is False
