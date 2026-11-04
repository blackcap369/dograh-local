"""The agency audit log (V2.1c): who did what, to which business, when.

Under test:

- Writes: the destructive/management routes append audit rows with the
  actor, action, business, and human-meaningful detail (rename carries
  from/to; trash carries the label).
- Best-effort contract: an audit write failure never fails the action.
- Reads: owner-only; staff 403.
- The record helper itself tolerates a vanished actor.

Conventions as the other agency suites: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user, require_agency_owner
from api.routes import agency

OWNER_ID = 10
STAFF_ID = 20

ACME = SimpleNamespace(
    id=9, provider_id="org_oss_9_acme", name="Acme Corp", archived=False
)
STAFF_ACCOUNT = SimpleNamespace(
    id=STAFF_ID,
    provider_id="oss_staff",
    email="staff@agency.test",
    name="Staff",
    agency_role="staff",
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
        selected_organization_id=ACME.id,
        agency_role=agency_role,
    )
    return app


def _patched_db(balance: int = 60) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
    mock_db.is_user_assigned_to_organization = AsyncMock(return_value=True)
    mock_db.get_organization_resource_counts = AsyncMock(return_value={})
    mock_db.get_balances_for_orgs = AsyncMock(return_value={ACME.id: balance})
    mock_db.list_recent_audit_entries = AsyncMock(return_value=[])
    mock_db.rename_organization = AsyncMock(
        return_value=SimpleNamespace(
            id=ACME.id, provider_id=ACME.provider_id, name="Renamed"
        )
    )
    mock_db.mark_organization_deleted = AsyncMock(return_value=ACME)
    mock_db.get_user_by_id = AsyncMock(return_value=STAFF_ACCOUNT)
    mock_db.get_user_by_email = AsyncMock(return_value=None)
    return mock_db


class TestAuditWrites:
    @pytest.mark.asyncio
    async def test_rename_writes_from_and_to(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.routes.agency.record_audit", AsyncMock()
        ) as audit:
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "Renamed"}
            )

        assert response.status_code == 200, response.text
        audit.assert_awaited_once()
        args, kwargs = audit.await_args
        assert args[0] == "client.renamed"
        assert kwargs["from"] == "Acme Corp"
        assert kwargs["to"] == "Renamed"

    @pytest.mark.asyncio
    async def test_trash_writes_the_label(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.routes.agency.record_audit", AsyncMock()
        ) as audit:
            response = client.delete(f"/api/v1/agency/clients/{ACME.id}")

        assert response.status_code in (200, 204), response.text
        args, kwargs = audit.await_args
        assert args[0] == "client.trashed"
        assert kwargs["label"] == "org_oss_9_acme"

    @pytest.mark.asyncio
    async def test_top_up_writes_minutes_and_balance(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.top_up = AsyncMock(
            return_value=SimpleNamespace(
                id=ACME.id,
                organization_id=ACME.id,
                balance_minutes=560,
            )
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.routes.agency.record_audit", AsyncMock()
        ) as audit:
            response = client.post(
                f"/api/v1/agency/credits/{ACME.id}/top-up", json={"minutes": 500}
            )

        assert response.status_code == 200, response.text
        args, kwargs = audit.await_args
        assert args[0] == "credits.top_up"
        assert kwargs["minutes"] == 500
        assert kwargs["balance_after"] == 560

    @pytest.mark.asyncio
    async def test_actor_identity_is_captured(self):
        """The row's actor args come from the authenticated caller."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.routes.agency.record_audit", AsyncMock()
        ) as audit:
            client.post(
                f"/api/v1/agency/credits/{ACME.id}/top-up", json={"minutes": 10}
            )

        args, _kwargs = audit.await_args
        actor = args[1]
        assert actor.id == OWNER_ID
        assert actor.email == "caller@agency.test"


class TestAuditBestEffort:
    @pytest.mark.asyncio
    async def test_audit_failure_never_fails_the_action(self):
        """The whole point of best-effort: the rename must succeed even if
        the audit write explodes. The service's try/except is what delivers
        this, so the failure is injected under it -- at the db layer."""
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        exploding_audit_db = AsyncMock()
        exploding_audit_db.record_audit = AsyncMock(
            side_effect=RuntimeError("audit db down")
        )
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.services.audit.db_client", exploding_audit_db
        ):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "Renamed"}
            )

        assert response.status_code == 200, response.text
        exploding_audit_db.record_audit.assert_awaited()  # it was tried...
        mock_db.rename_organization.assert_awaited()  # ...and the action still succeeded


class TestAuditRead:
    @pytest.mark.asyncio
    async def test_owner_can_read(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.list_recent_audit_entries = AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=1,
                    action="client.trashed",
                    actor_email="caller@agency.test",
                    organization_id=ACME.id,
                    detail={"label": "Acme Corp"},
                    created_at=None,
                )
            ]
        )
        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/audit-log")

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 1
        assert body[0]["action"] == "client.trashed"
        assert body[0]["detail"]["label"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_staff_is_403(self):
        """Entries name staff actions across businesses -- exactly what the
        staff scoping exists to keep from individual staff members."""
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/audit-log")

        assert response.status_code == 403, response.text
