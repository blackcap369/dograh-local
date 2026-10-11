"""Credit billing (V2.5-billing): 1 credit = 1 minute of successful run time.

Under test: the deduction math (rounded up, failed runs never deduct), the
zero-balance gate at run creation, owner top-ups, and the balance read
scoped to the organization.

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
ORG_ID = 9

ACME = SimpleNamespace(
    id=ORG_ID, provider_id="org_oss_9_acme", name="Acme Corp", archived=False
)


def _make_app():
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=OWNER_ID,
        provider_id="oss_owner",
        email="owner@agency.test",
        selected_organization_id=ORG_ID,
        agency_role="owner",
    )
    app.dependency_overrides[require_agency_owner] = lambda: SimpleNamespace(
        id=OWNER_ID,
        provider_id="oss_owner",
        email="owner@agency.test",
        selected_organization_id=ORG_ID,
        agency_role="owner",
    )
    return app


def _patched_db(balance: int = 60) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.list_all_organizations = AsyncMock(return_value=[ACME])
    mock_db.get_organization_resource_counts = AsyncMock(return_value={})
    mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
    mock_db.get_balances_for_orgs = AsyncMock(return_value={ORG_ID: balance})
    mock_db.top_up = AsyncMock(
        return_value=SimpleNamespace(
            id=ORG_ID,
            organization_id=ORG_ID,
            balance_minutes=balance + 120,
        )
    )
    return mock_db


class TestCreditRoutes:
    @pytest.mark.asyncio
    async def test_list_balances(self):
        app = _make_app()
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.get("/api/v1/agency/credits")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["businesses"][0]["balance_minutes"] == 60
        assert body["businesses"][0]["label"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_top_up_adds_minutes(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = _patched_db(balance=40)
        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(
                f"/api/v1/agency/credits/{ORG_ID}/top-up", json={"minutes": 120}
            )

        assert response.status_code == 200, response.text
        mock_db.top_up.assert_awaited_once_with(ORG_ID, 120, created_by=OWNER_ID)

    @pytest.mark.asyncio
    async def test_top_up_rejects_non_positive(self):
        app = _make_app()
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_db()):
            response = client.post(
                f"/api/v1/agency/credits/{ORG_ID}/top-up", json={"minutes": 0}
            )

        assert response.status_code == 422, response.text


class TestCreditDeduction:
    @pytest.mark.asyncio
    async def test_successful_run_deducts_rounded_up_minutes(self):
        from api.services import credit_billing

        run = SimpleNamespace(
            id=66,
            workflow_id=12,
            is_completed=True,
            usage_info={"call_duration_seconds": 125},  # 2.08 min -> 3
            gathered_context={"call_status": "completed"},
        )
        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=run)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=12, organization_id=ORG_ID)
        )

        with patch("api.services.credit_billing.db_client", mock_db):
            await credit_billing.apply_run_credit_deduction(66)

        mock_db.deduct_for_run.assert_awaited_once_with(
            organization_id=ORG_ID, minutes=3, run_id=66
        )

    @pytest.mark.asyncio
    async def test_failed_run_never_deducts(self):
        from api.services import credit_billing

        run = SimpleNamespace(
            id=66,
            workflow_id=12,
            is_completed=True,
            usage_info={"call_duration_seconds": 500},
            gathered_context={"error": "dropped", "call_status": "error"},
        )
        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=run)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=12, organization_id=ORG_ID)
        )

        with patch("api.services.credit_billing.db_client", mock_db):
            await credit_billing.apply_run_credit_deduction(66)

        mock_db.deduct_for_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_minimum_one_credit_per_successful_call(self):
        from api.services import credit_billing

        run = SimpleNamespace(
            id=66,
            workflow_id=12,
            is_completed=True,
            usage_info={"call_duration_seconds": 7},
            gathered_context={"call_status": "completed"},
        )
        mock_db = AsyncMock()
        mock_db.get_workflow_run_by_id = AsyncMock(return_value=run)
        mock_db.get_workflow_by_id = AsyncMock(
            return_value=SimpleNamespace(id=12, organization_id=ORG_ID)
        )

        with patch("api.services.credit_billing.db_client", mock_db):
            await credit_billing.apply_run_credit_deduction(66)

        mock_db.deduct_for_run.assert_awaited_once_with(
            organization_id=ORG_ID, minutes=1, run_id=66
        )


class TestZeroBalanceGate:
    @pytest.mark.asyncio
    async def test_gate_blocks_when_balance_is_zero(self):
        from api.services import credit_billing
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_db.has_credits = AsyncMock(return_value=False)

        with patch("api.services.credit_billing.db_client", mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await credit_billing.ensure_organization_has_credits(ORG_ID)

        assert exc_info.value.status_code == 402
        assert "out of credits" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_gate_passes_with_credits(self):
        from api.services import credit_billing

        mock_db = AsyncMock()
        mock_db.has_credits = AsyncMock(return_value=True)

        with patch("api.services.credit_billing.db_client", mock_db):
            await credit_billing.ensure_organization_has_credits(ORG_ID)  # no raise
