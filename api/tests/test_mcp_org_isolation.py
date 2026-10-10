"""MCP end-to-end with a real org-scoped API key (V2.3).

Proves, through the REAL auth path (`authenticate_mcp_request` ->
`_handle_api_key_auth`), that:

1. An MCP request authenticated by an organization-scoped API key is forced
   to that key's organization — even when the underlying user's personal
   selection points somewhere else.
2. `list_workflows` / `get_workflow` scope their queries to that
   organization, so another organization's agents are invisible through MCP.
3. The key's owner cannot widen their reach with a personal org switch:
   `/organizations/switch` changes `users.selected_organization_id`, and the
   API-key path overwrites it on every request.

No agency-level MCP tools exist by design (create/list organizations are
operator-UI work); this test pins that the existing per-org toolset cannot
reach across tenants.

The Windows loopback transport quirk that fails the mock-server session
tests (documented pre-existing) is bypassed here: the tool functions are
driven directly after the real authentication step, so the guarantee under
test — org scoping of every query — is exercised without the flaky
transport.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.db.models import UserModel
from api.mcp_server import auth as mcp_auth
from api.mcp_server.tools import workflows as mcp_workflows

KEY_ORG_ID = 9
OTHER_ORG_ID = 1
USER_ID = 30

ACME_AGENT = SimpleNamespace(
    id=101,
    name="Acme support agent",
    organization_id=KEY_ORG_ID,
    status="active",
    created_at=None,
)


def _key_row(organization_id: int):
    return SimpleNamespace(
        id=1,
        key_prefix="dgr_abc1",
        organization_id=organization_id,
        is_active=True,
        created_by=USER_ID,
    )


def _user(personal_selection: int | None):
    return UserModel(
        id=USER_ID,
        provider_id="oss_mcpguy",
        selected_organization_id=personal_selection,
    )


def _patch_headers(api_key: str):
    """Patch fastmcp's header source to present an X-API-Key header."""
    return patch(
        "api.mcp_server.auth.get_http_headers",
        return_value={"x-api-key": api_key},
    )


@pytest.mark.asyncio
async def test_api_key_forces_its_org_for_mcp_requests():
    """The key's organization wins over the user's personal selection.

    The user's row says they are standing in org 1; the key belongs to org 9.
    Every MCP tool must run inside org 9.
    """
    mock_db = AsyncMock()
    mock_db.validate_api_key = AsyncMock(return_value=_key_row(KEY_ORG_ID))
    mock_db.get_user_by_id = AsyncMock(
        return_value=_user(personal_selection=OTHER_ORG_ID)
    )

    with patch("api.services.auth.depends.db_client", mock_db), _patch_headers(
        "dgr_abc1_realkey"
    ):
        user = await mcp_auth.authenticate_mcp_request()

    assert user.selected_organization_id == KEY_ORG_ID, (
        "an MCP request authenticated by an org-scoped key must run inside "
        "that key's organization, not the user's personal selection"
    )


@pytest.mark.asyncio
async def test_list_workflows_is_scoped_to_the_keys_org():
    mock_db = AsyncMock()
    mock_db.validate_api_key = AsyncMock(return_value=_key_row(KEY_ORG_ID))
    mock_db.get_user_by_id = AsyncMock(return_value=_user(personal_selection=OTHER_ORG_ID))
    mock_db.get_all_workflows_for_listing = AsyncMock(return_value=[ACME_AGENT])

    with patch("api.services.auth.depends.db_client", mock_db), patch(
        "api.mcp_server.tools.workflows.db_client", mock_db
    ), _patch_headers("dgr_abc1_realkey"):
        agents = await mcp_workflows.list_workflows()

    assert [a["id"] for a in agents] == [ACME_AGENT.id]
    _, kwargs = mock_db.get_all_workflows_for_listing.await_args
    assert kwargs.get("organization_id") == KEY_ORG_ID, (
        "the list query must carry the key's organization"
    )


@pytest.mark.asyncio
async def test_get_workflow_of_another_org_is_invisible_through_mcp():
    """The org-scoped lookup misses for a foreign agent, and the tool turns
    that into a 404 — the same contract the HTTP routes honour."""
    mock_db = AsyncMock()
    mock_db.validate_api_key = AsyncMock(return_value=_key_row(KEY_ORG_ID))
    mock_db.get_user_by_id = AsyncMock(return_value=_user(personal_selection=OTHER_ORG_ID))
    # The org-scoped query returns None for a foreign agent id.
    mock_db.get_workflow = AsyncMock(return_value=None)

    from fastapi import HTTPException

    with patch("api.services.auth.depends.db_client", mock_db), patch(
        "api.mcp_server.tools.workflows.db_client", mock_db
    ), _patch_headers("dgr_abc1_realkey"), pytest.raises(HTTPException) as exc_info:
        await mcp_workflows.get_workflow(555)  # an org-1 agent id

    assert exc_info.value.status_code == 404
    _, kwargs = mock_db.get_workflow.await_args
    assert kwargs.get("organization_id") == KEY_ORG_ID, (
        "the fetch must be scoped to the key's organization"
    )


@pytest.mark.asyncio
async def test_personal_org_switch_cannot_widen_mcp_reach():
    """Even after the user's row is moved to another organization (the
    personal switch), the next MCP request is re-scoped to the key's org —
    the overwrite happens on every request."""
    mock_db = AsyncMock()
    mock_db.validate_api_key = AsyncMock(return_value=_key_row(KEY_ORG_ID))
    # The personal switch already happened: the row now points at org 1.
    mock_db.get_user_by_id = AsyncMock(return_value=_user(personal_selection=OTHER_ORG_ID))
    mock_db.get_all_workflows_for_listing = AsyncMock(return_value=[])

    with patch("api.services.auth.depends.db_client", mock_db), patch(
        "api.mcp_server.tools.workflows.db_client", mock_db
    ), _patch_headers("dgr_abc1_realkey"):
        user = await mcp_auth.authenticate_mcp_request()
        await mcp_workflows.list_workflows()

    assert user.selected_organization_id == KEY_ORG_ID
    _, kwargs = mock_db.get_all_workflows_for_listing.await_args
    assert kwargs.get("organization_id") == KEY_ORG_ID


@pytest.mark.asyncio
async def test_mcp_request_without_api_key_is_401():
    from fastapi import HTTPException

    with patch("api.mcp_server.auth.get_http_headers", return_value={}):
        with pytest.raises(HTTPException) as exc_info:
            await mcp_auth.authenticate_mcp_request()

    assert exc_info.value.status_code == 401
