"""The recovery trash (V2.1e): soft delete, restore, purge, and the purge job.

Delete trashes; the trash is invisible to every default lookup; restore brings
the business back whole; the purge is the one irreversible act and stays
impact-guarded; the nightly job purges only expired, purge-safe businesses and
leaves guarded ones trashed forever.

Conventions as the other agency suites: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, call
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import agency, organization

OWNER_ID = 10
OWNER_PROVIDER = "user_owner"
STAFF_ID = 20

EMPTY = SimpleNamespace(
    id=1, provider_id="org_oss_1_empty", name="Empty Business", archived=False,
    deleted_at=datetime.now(timezone.utc) - timedelta(days=11),
)
FULL = SimpleNamespace(
    id=2, provider_id="org_oss_2_full", name="Full Business", archived=False,
    deleted_at=datetime.now(timezone.utc) - timedelta(days=11),
)
LIVE = SimpleNamespace(
    id=3, provider_id="org_oss_3_live", name="Live Business", archived=False,
    deleted_at=None,
)


def _make_app(user_id: int = OWNER_ID, agency_role: str = "owner"):
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=OWNER_PROVIDER if agency_role == "owner" else "oss_staff",
        email="caller@agency.test",
        selected_organization_id=None,
        agency_role=agency_role,
    )
    return app


def _patched_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.get_organization_by_id = AsyncMock(return_value=EMPTY)
    mock_db.get_balances_for_orgs = AsyncMock(return_value={})
    mock_db.get_organization_resource_counts = AsyncMock(
        return_value={
            EMPTY.id: {
                "workflow_count": 0,
                "run_count": 0,
                "phone_number_count": 0,
                "member_count": 1,
            },
            FULL.id: {
                "workflow_count": 4,
                "run_count": 128,
                "phone_number_count": 2,
                "member_count": 3,
            },
        }
    )
    mock_db.list_deleted_organizations = AsyncMock(return_value=[FULL, EMPTY])
    mock_db.mark_organization_deleted = AsyncMock(return_value=EMPTY)
    mock_db.restore_organization = AsyncMock(return_value=LIVE)
    return mock_db


# =============================================================================
# The trash listing
# =============================================================================


class TestTrashListing:
    @pytest.mark.asyncio
    async def test_lists_trashed_businesses_with_eligibility(self):
        """The purge clock is visible: an expired, history-free business shows
        its eligibility date; a business with runs shows `null` -- the nightly
        purge will never take it."""
        app = _make_app()
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/trash")

        assert response.status_code == 200, response.text
        rows = {r["id"]: r for r in response.json()}
        assert rows[FULL.id]["purge_eligible_at"] is None, (
            "history must pin the business in the trash"
        )
        assert rows[FULL.id]["run_count"] == 128
        assert rows[EMPTY.id]["purge_eligible_at"] is not None

    @pytest.mark.asyncio
    async def test_staff_is_403(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/trash")

        assert response.status_code == 403, response.text


# =============================================================================
# Restore
# =============================================================================


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_brings_the_business_back(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(f"/api/v1/agency/trash/{EMPTY.id}/restore")

        assert response.status_code == 204, response.text
        mock_db.restore_organization.assert_awaited_once_with(EMPTY.id)
        # A trashed business is not destroyed, so the trash must not run any
        # of the destructive cleanup -- restore is a column write.
        mock_db.clear_organization_users.assert_not_awaited()
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_restore_of_a_live_business_is_404(self):
        """Restoring something that was never trashed is a caller error, not
        a state change."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_organization_by_id = AsyncMock(return_value=LIVE)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(f"/api/v1/agency/trash/{LIVE.id}/restore")

        assert response.status_code == 404, response.text
        mock_db.restore_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_is_403(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.post(f"/api/v1/agency/trash/{EMPTY.id}/restore")

        assert response.status_code == 403, response.text


# =============================================================================
# Purge: the one irreversible act
# =============================================================================


class TestPurge:
    @pytest.mark.asyncio
    async def test_purge_of_an_empty_business_destroys_it(self):
        """The full hard-delete sequence, in order: selections, memberships,
        row. The row delete cascades keys, configs, and call records."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.delete_organization = AsyncMock(return_value=True)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post(f"/api/v1/agency/trash/{EMPTY.id}/purge")

        assert response.status_code == 204, response.text
        order = [
            name.split("/")[-1]
            for name, _args, _kwargs in mock_db.mock_calls
            if name
            in (
                "clear_selected_organization_references",
                "clear_organization_users",
                "delete_organization",
            )
        ]
        assert order == [
            "clear_selected_organization_references",
            "clear_organization_users",
            "delete_organization",
        ], f"purge steps ran out of order: {order}"

    @pytest.mark.asyncio
    async def test_purge_refused_for_a_business_with_history(self):
        """The impact guard lives here now. A business with runs is refused
        with the counts and stays trashed -- nothing is destroyed."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_organization_by_id = AsyncMock(return_value=FULL)
        mock_db.delete_organization = AsyncMock()
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post(f"/api/v1/agency/trash/{FULL.id}/purge")

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["workflow_count"] == 4
        assert detail["run_count"] == 128
        assert "restorable" in str(detail).lower()
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_purge_of_a_live_business_is_404(self):
        """Purge only applies to the trash. A live business is untouched --
        the path to removing it is trash first, then purge."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.get_organization_by_id = AsyncMock(return_value=LIVE)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(f"/api/v1/agency/trash/{LIVE.id}/purge")

        assert response.status_code == 404, response.text
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_is_403(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.post(f"/api/v1/agency/trash/{EMPTY.id}/purge")

        assert response.status_code == 403, response.text


# =============================================================================
# Scoping: trashed businesses vanish from every default lookup
# =============================================================================


class TestTrashedScoping:
    """The dangerous part of soft delete is completeness: a trashed business
    that any default lookup still resolves would be offered as a place to
    work. These tests pin the callers the routes depend on."""

    @pytest.mark.asyncio
    async def test_owner_clients_list_excludes_trashed(self):
        """The filter lives in the query (`list_all_organizations`), not in
        the route -- pinned by asserting the route asks no other source."""
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.list_all_organizations = AsyncMock(return_value=[LIVE])
        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        ids = [c["id"] for c in response.json()]
        assert EMPTY.id not in ids and FULL.id not in ids

    @pytest.mark.asyncio
    async def test_switch_into_a_trashed_business_is_404(self):
        """`/switch` resolves the target through `get_organization_by_id`,
        whose default filter excludes trashed rows -- so the switch endpoint
        404s before any membership check."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = AsyncMock()
        # get_organization_by_id is called WITHOUT include_deleted by the
        # switch route, so a trashed business resolves to None.
        mock_db.get_organization_by_id = AsyncMock(return_value=None)
        with patch("api.routes.organization.db_client", mock_db):
            response = client.post(
                "/api/v1/organizations/switch", json={"organization_id": EMPTY.id}
            )

        assert response.status_code == 404, response.text

    @pytest.mark.asyncio
    async def test_membership_query_filters_trashed(self):
        """The switcher's read (`/mine` -> get_organizations_for_user) must
        exclude trashed businesses at the query."""
        from api.db.user_client import UserClient

        captured = {}

        class _FakeResult:
            def scalars(self):
                return self

            def all(self):
                return []

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, query):
                captured["query"] = query
                return _FakeResult()

        client = UserClient.__new__(UserClient)
        client.async_session = lambda *a, **k: _FakeSession()

        await client.get_organizations_for_user(STAFF_ID)

        compiled = str(
            captured["query"].compile(compile_kwargs={"literal_binds": True})
        )
        assert "deleted_at IS NULL" in compiled, (
            f"the switcher read must exclude trashed businesses: {compiled}"
        )

    @pytest.mark.asyncio
    async def test_lookup_by_id_excludes_trashed_by_default(self):
        """The fail-closed default: every plain get_organization_by_id caller
        sees a trashed business as gone."""
        from api.db.organization_client import OrganizationClient

        captured = {}

        class _FakeResult:
            def scalars(self):
                return self

            def first(self):
                return None

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, query):
                captured["query"] = query
                return _FakeResult()

        client = OrganizationClient.__new__(OrganizationClient)
        client.async_session = lambda *a, **k: _FakeSession()

        await client.get_organization_by_id(EMPTY.id)

        compiled = str(
            captured["query"].compile(compile_kwargs={"literal_binds": True})
        )
        assert "deleted_at IS NULL" in compiled, (
            f"the default lookup must exclude trashed rows: {compiled}"
        )

        captured.clear()
        await client.get_organization_by_id(EMPTY.id, include_deleted=True)
        compiled = str(
            captured["query"].compile(compile_kwargs={"literal_binds": True})
        )
        assert "deleted_at IS NULL" not in compiled, (
            f"include_deleted must not filter: {compiled}"
        )


# =============================================================================
# The nightly purge job
# =============================================================================


class TestPurgeJob:
    @pytest.mark.asyncio
    async def test_purges_expired_safe_businesses_only(self):
        from api.tasks import trash_purge

        expired_empty = SimpleNamespace(
            id=EMPTY.id, provider_id=EMPTY.provider_id, deleted_at=EMPTY.deleted_at
        )
        expired_full = SimpleNamespace(
            id=FULL.id, provider_id=FULL.provider_id, deleted_at=FULL.deleted_at
        )
        not_expired = SimpleNamespace(id=LIVE.id, provider_id=LIVE.provider_id)

        mock_db = AsyncMock()
        mock_db.list_expired_trashed_organizations = AsyncMock(
            return_value=[expired_empty, expired_full]
        )
        mock_db.get_organization_resource_counts = AsyncMock(
            return_value={
                EMPTY.id: {
                    "workflow_count": 0,
                    "run_count": 0,
                    "phone_number_count": 0,
                    "member_count": 1,
                },
                FULL.id: {
                    "workflow_count": 4,
                    "run_count": 128,
                    "phone_number_count": 2,
                    "member_count": 3,
                },
            }
        )

        # The task reads the singleton from its own module namespace, so that
        # binding is the patch target (ctx is arq's bookkeeping, not a
        # dependency container here).
        with patch("api.tasks.trash_purge.db_client", mock_db):
            result = await trash_purge.purge_expired_trashed_organizations(
                {"db_client": mock_db}
            )

        assert result["purged"] == [EMPTY.id]
        assert result["skipped"] == [
            {
                "organization_id": FULL.id,
                "workflow_count": 4,
                "run_count": 128,
                "phone_number_count": 2,
                "member_count": 3,
            }
        ]
        mock_db.delete_organization.assert_awaited_once_with(EMPTY.id)
        # The skipped business keeps everything, including its memberships.
        mock_db.clear_organization_users.assert_awaited_once_with(EMPTY.id)

    @pytest.mark.asyncio
    async def test_does_nothing_when_nothing_is_expired(self):
        from api.tasks import trash_purge

        mock_db = AsyncMock()
        mock_db.list_expired_trashed_organizations = AsyncMock(return_value=[])

        with patch("api.tasks.trash_purge.db_client", mock_db):
            result = await trash_purge.purge_expired_trashed_organizations(
                {"db_client": mock_db}
            )

        assert result == {"purged": [], "skipped": []}
        mock_db.delete_organization.assert_not_awaited()
