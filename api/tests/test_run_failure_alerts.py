"""Failed-run monitoring & alerting (V2.6).

The guarantee: the agency learns about a broken agent before the client
does. Three pieces under test:

- The evaluator (run completion hook): a failed run bumps the open alert for
  its business+agent (debounced by the partial unique index -- one open row,
  a growing failure count); a successful run auto-clears it; monitoring is
  best-effort (a run row that vanished must not raise).
- The health endpoint: role-scoped exactly like the Clients list (owner:
  every business; staff: assignments only, scoped in the query).
- Acknowledge: staff for assigned businesses, owners for any, 404
  otherwise.

Conventions as the other agency suites: bare FastAPI app + TestClient +
patch(db_client) with AsyncMock.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import agency

OWNER_ID = 10
STAFF_ID = 20

ACME = SimpleNamespace(
    id=9, provider_id="org_oss_9_acme", name="Acme Corp", archived=False
)
GLOBEX = SimpleNamespace(
    id=2, provider_id="org_oss_2_globex", name="Globex Legal", archived=False
)

FAILED_RUN = SimpleNamespace(
    id=501,
    workflow_id=9,
    is_completed=True,
    gathered_context={"error": "Twilio error: 30003", "call_status": "error"},
)
GOOD_RUN = SimpleNamespace(
    id=502,
    workflow_id=9,
    is_completed=True,
    gathered_context={"call_status": "completed"},
)

OPEN_ALERT = SimpleNamespace(
    id=7,
    organization_id=ACME.id,
    workflow_id=9,
    first_failed_run_id=501,
    last_failed_run_id=501,
    failure_count=3,
    last_error="Twilio error: 30003",
    acknowledged_at=None,
    resolved_at=None,
    updated_at=datetime.now(timezone.utc),
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


def _patched_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.list_all_organizations = AsyncMock(return_value=[ACME, GLOBEX])
    mock_db.list_organizations_for_staff = AsyncMock(return_value=[ACME])
    mock_db.get_organization_resource_counts = AsyncMock(return_value={})
    mock_db.get_run_failure_health = AsyncMock(
        return_value={
            ACME.id: {
                "runs_24h": 6,
                "failed_24h": 3,
                "last_failure": {
                    "run_id": 501,
                    "agent_name": "Acme support agent",
                    "error": "Twilio error: 30003",
                    "at": datetime.now(timezone.utc),
                },
            },
            GLOBEX.id: {"runs_24h": 0, "failed_24h": 0, "last_failure": None},
        }
    )
    mock_db.get_balances_for_orgs = AsyncMock(return_value={ACME.id: 60})
    mock_db.list_active_failure_alerts = AsyncMock(
        return_value=[
            {
                "id": 7,
                "organization_id": ACME.id,
                "business_label": "Acme Corp",
                "workflow_id": 9,
                "agent_name": "Acme support agent",
                "failure_count": 3,
                "last_error": "Twilio error: 30003",
                "last_failed_run_id": 501,
                "updated_at": datetime.now(timezone.utc),
            }
        ]
    )
    mock_db.get_run_failure_alert_by_id = AsyncMock(return_value=OPEN_ALERT)
    mock_db.acknowledge_failure_alert = AsyncMock(return_value=True)
    return mock_db


# =============================================================================
# The evaluator (completion-task hook)
# =============================================================================


class TestEvaluator:
    @pytest.mark.asyncio
    async def test_failed_run_bumps_the_alert(self):
        from api.services import run_failure_alerts

        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=FAILED_RUN)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=9, organization_id=ACME.id)
        )
        mock_db.upsert_run_failure_alert = AsyncMock(return_value=OPEN_ALERT)

        with patch("api.services.run_failure_alerts.db_client", mock_db):
            await run_failure_alerts.evaluate_run_completion_for_alerts(501)

        mock_db.upsert_run_failure_alert.assert_awaited_once_with(
            organization_id=ACME.id,
            workflow_id=9,
            failed_run_id=501,
            error="Twilio error: 30003",
        )
        mock_db.resolve_run_failure_alerts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_run_auto_clears_the_alert(self):
        from api.services import run_failure_alerts

        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=GOOD_RUN)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=9, organization_id=ACME.id)
        )

        with patch("api.services.run_failure_alerts.db_client", mock_db):
            await run_failure_alerts.evaluate_run_completion_for_alerts(502)

        mock_db.resolve_run_failure_alerts.assert_awaited_once_with(ACME.id, 9)
        mock_db.upsert_run_failure_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_incomplete_run_is_neither_failure_nor_clear(self):
        """A run still initializing must not be counted as failed -- nor
        clear an open alert (the call may still fail)."""
        from api.services import run_failure_alerts

        run = SimpleNamespace(
            id=503, workflow_id=9, is_completed=False, gathered_context={}
        )
        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=run)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=9, organization_id=ACME.id)
        )

        with patch("api.services.run_failure_alerts.db_client", mock_db):
            await run_failure_alerts.evaluate_run_completion_for_alerts(503)

        mock_db.upsert_run_failure_alert.assert_not_awaited()
        mock_db.resolve_run_failure_alerts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_vanished_run_does_not_raise(self):
        """Best-effort by contract: monitoring must never break the
        completion pipeline it watches."""
        from api.services import run_failure_alerts

        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=None)

        with patch("api.services.run_failure_alerts.db_client", mock_db):
            await run_failure_alerts.evaluate_run_completion_for_alerts(999)

        mock_db.upsert_run_failure_alert.assert_not_awaited()


# =============================================================================
# The health endpoint
# =============================================================================


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_owner_sees_every_business(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/health")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["window_hours"] == 24
        labels = {b["label"] for b in body["businesses"]}
        assert labels == {"Acme Corp", "Globex Legal"}
        acme = next(b for b in body["businesses"] if b["label"] == "Acme Corp")
        assert acme["runs_24h"] == 6
        assert acme["failed_24h"] == 3
        assert acme["last_failure"]["agent_name"] == "Acme support agent"
        assert body["alerts"][0]["failure_count"] == 3
        assert body["credit_minutes"][str(ACME.id)] == 60

    @pytest.mark.asyncio
    async def test_staff_sees_only_assigned_businesses(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/health")

        assert response.status_code == 200, response.text
        labels = {b["label"] for b in response.json()["businesses"]}
        assert labels == {"Acme Corp"}
        # the assignment-scoped read, not the owner's cross-org one
        mock_db.list_organizations_for_staff.assert_awaited_once_with(STAFF_ID)
        mock_db.list_all_organizations.assert_not_awaited()


# =============================================================================
# Acknowledge
# =============================================================================


class TestAcknowledge:
    @pytest.mark.asyncio
    async def test_owner_can_acknowledge(self):
        app = _make_app(OWNER_ID, "owner")
        client = TestClient(app)

        mock_db = _patched_db()
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/failure-alerts/7/acknowledge")

        assert response.status_code == 204, response.text
        mock_db.acknowledge_failure_alert.assert_awaited_once_with(
            7, ACME.id, OWNER_ID
        )

    @pytest.mark.asyncio
    async def test_assigned_staff_can_acknowledge(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=True)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/failure-alerts/7/acknowledge")

        assert response.status_code == 204, response.text

    @pytest.mark.asyncio
    async def test_unassigned_staff_is_403(self):
        app = _make_app(STAFF_ID, "staff")
        client = TestClient(app)

        mock_db = _patched_db()
        mock_db.is_user_assigned_to_organization = AsyncMock(return_value=False)
        with patch("api.routes.agency.db_client", mock_db), patch(
            "api.db.db_client", mock_db
        ):
            response = client.post("/api/v1/agency/failure-alerts/7/acknowledge")

        assert response.status_code == 403, response.text
        mock_db.acknowledge_failure_alert.assert_not_awaited()
