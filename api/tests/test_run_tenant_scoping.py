"""Cross-tenant run authorization: the agent's org is the run's tenant.

The bug (live-reported): testing an agent while the operator stands in a
DIFFERENT business failed with "Workflow not found". The run-start paths
stamped and authorized runs against `user.selected_organization_id` instead
of the agent's own organization, so the quota check looked up the agent in
the wrong tenant.

Under test: text-chat session creation falls back to the agent's own tenant,
stamps the run with the agent's org, and authorizes quota against the
agent's org; the workflow editor fetch falls back the same way.
"""

from datetime import datetime, UTC

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.enums import WorkflowRunMode
from api.services.auth.depends import get_user, get_user_with_selected_organization
from api.routes import workflow_text_chat

WF_ID = 14
AGENT_ORG = 18  # Evil
SELECTED_ORG = 9  # ACME -- the operator is standing elsewhere

EVIL_AGENT = SimpleNamespace(
    id=WF_ID, name="cold calling", organization_id=AGENT_ORG, user_id=1
)


def _fake_workflow_run(run_id=77, organization_id=AGENT_ORG):
    return SimpleNamespace(
        id=run_id,
        workflow_id=WF_ID,
        name="cold calling",
        mode=WorkflowRunMode.TEXTCHAT.value,
        organization_id=organization_id,
        is_completed=False,
        state=None,
        initial_context={},
        gathered_context={},
        annotations={},
    )


def _fake_text_session(run_id=77, organization_id=AGENT_ORG):
    _now = datetime.now(UTC)
    return SimpleNamespace(
        workflow_run=_fake_workflow_run(run_id, organization_id),
        revision=1,
        session_data={"status": "active", "messages": []},
        checkpoint={"messages": [], "version": 1},
        created_at=_now,
        updated_at=_now,
    )


def _make_app():
    app = FastAPI()
    app.include_router(workflow_text_chat.router, prefix="/api/v1")
    owner = SimpleNamespace(
        id=10,
        provider_id="oss_owner",
        email="owner@agency.test",
        selected_organization_id=SELECTED_ORG,
        agency_role="owner",
    )
    app.dependency_overrides[get_user] = lambda: owner
    app.dependency_overrides[get_user_with_selected_organization] = lambda: owner
    return app


class TestRunTenantIsTheAgentsOrg:
    @pytest.mark.asyncio
    async def test_session_creation_falls_back_to_the_agents_org(self):
        """Standing in ACME while testing Evil's agent still resolves the
        agent, stamps the run with Evil's org, and authorizes against it."""
        from api.services.quota_service import QuotaCheckResult

        app = _make_app()
        client = TestClient(app)

        run = SimpleNamespace(id=77)
        mock_db = AsyncMock()
        # The org-scoped lookup misses (wrong tenant)...
        mock_db.get_workflow = AsyncMock(return_value=None)
        # ...the by-id fallback resolves the agent in its own org.
        mock_db.get_workflow_by_id = AsyncMock(return_value=EVIL_AGENT)
        mock_db.prepare_workflow_run_inputs = None  # unused (patched below)
        mock_db.create_workflow_run = AsyncMock(return_value=run)
        mock_db.update_workflow_run = AsyncMock(return_value=run)
        mock_db.ensure_workflow_run_text_session = AsyncMock(
            return_value=_fake_text_session()
        )

        quota_calls = {}

        async def fake_quota(**kwargs):
            quota_calls.update(kwargs)
            return QuotaCheckResult(has_quota=True)

        with patch("api.routes.workflow_text_chat.db_client", mock_db), patch(
            "api.routes.workflow_text_chat.prepare_workflow_run_inputs",
            AsyncMock(
                return_value=SimpleNamespace(
                    initial_context={}, definition_id=None
                )
            ),
        ), patch(
            "api.routes.workflow_text_chat.authorize_workflow_run_start",
            fake_quota,
        ), patch(
            "api.routes.workflow_text_chat.initialize_text_chat_session",
            AsyncMock(return_value=_fake_text_session()),
        ), patch(
            "api.routes.workflow_text_chat.execute_pending_text_chat_turn",
            AsyncMock(return_value=_fake_text_session()),
        ):
            response = client.post(
                f"/api/v1/workflow/{WF_ID}/text-chat/sessions", json={}
            )

        assert response.status_code != 404, response.text
        # The run was stamped with the AGENT's org, not the selection.
        _, kwargs = mock_db.create_workflow_run.await_args
        assert kwargs.get("organization_id") == AGENT_ORG
        # Quota was authorized against the AGENT's org.
        assert quota_calls.get("organization_id") == AGENT_ORG

    @pytest.mark.asyncio
    async def test_agent_that_exists_nowhere_is_still_404(self):
        app = _make_app()
        client = TestClient(app)

        mock_db = AsyncMock()
        mock_db.get_workflow = AsyncMock(return_value=None)
        mock_db.get_workflow_by_id = AsyncMock(return_value=None)

        with patch("api.routes.workflow_text_chat.db_client", mock_db):
            response = client.post(
                f"/api/v1/workflow/{WF_ID}/text-chat/sessions", json={}
            )

        assert response.status_code == 404, response.text
