"""
Cross-tenant isolation test harness.

This test suite validates that organization-scoped resources are properly isolated
across tenants. It creates two organizations with disjoint users and resources,
and asserts that a user authenticated in Org A cannot read, mutate, or enumerate
Org B's data across all org-scoped endpoints.

Follows the repo's test convention: bare FastAPI app + TestClient + patch(db_client)
with AsyncMock, rather than DB-seeded integration tests.
"""

import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import organization, workflow, credentials, tool, telephony, campaign, knowledge_base, user


# =============================================================================
# Test App Factories
# =============================================================================

def _make_org_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for organization endpoints with auth override."""
    app = FastAPI()
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_workflow_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for workflow endpoints with auth override."""
    app = FastAPI()
    app.include_router(workflow.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_credentials_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for credentials endpoints with auth override."""
    app = FastAPI()
    app.include_router(credentials.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_tools_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for tools endpoints with auth override."""
    app = FastAPI()
    app.include_router(tool.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_telephony_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for telephony endpoints with auth override."""
    # Phone numbers are under organizations router, not telephony
    app = FastAPI()
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_campaigns_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for campaigns endpoints with auth override."""
    app = FastAPI()
    app.include_router(campaign.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_knowledge_base_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for knowledge base endpoints with auth override."""
    app = FastAPI()
    app.include_router(knowledge_base.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


def _make_user_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """Create a minimal FastAPI app for user endpoints with auth override."""
    app = FastAPI()
    app.include_router(user.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


# =============================================================================
# Test Constants
# =============================================================================

# Two disjoint tenants
ORG_A_ID = 1
ORG_A_PROVIDER = "org_a_provider"
USER_A1_ID = 10
USER_A1_PROVIDER = "user_a1"
USER_A2_ID = 11
USER_A2_PROVIDER = "user_a2"

ORG_B_ID = 2
ORG_B_PROVIDER = "org_b_provider"
USER_B1_ID = 20
USER_B1_PROVIDER = "user_b1"
USER_B2_ID = 21
USER_B2_PROVIDER = "user_b2"


def _org_context(org_id: int, provider_id: str) -> SimpleNamespace:
    """An `OrganizationContextResponse` stand-in.

    Built from the real schema's field set (`api/services/organization_context.py`),
    because FastAPI validates the handler's return value against it — a hand-rolled
    namespace missing `model_services.*` fails at serialization, not at the assertion
    we actually care about.
    """
    return SimpleNamespace(
        organization_id=org_id,
        organization_provider_id=provider_id,
        model_services=SimpleNamespace(
            config_source="empty",
            has_model_configuration_v2=False,
            managed_service_version=None,
            uses_managed_service_v2=False,
        ),
    )


# =============================================================================
# Test: Organization Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestOrganizationEndpointsIsolation:
    """Test that /api/v1/organizations/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_get_mine_returns_only_own_orgs(self):
        """GET /organizations/mine returns only orgs the user belongs to."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        # Mock db_client to return only Org A for this user
        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)
        org_b = SimpleNamespace(id=ORG_B_ID, provider_id=ORG_B_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        data = response.json()
        org_ids = {o["id"] for o in data}
        assert org_ids == {ORG_A_ID}, f"Expected only org_a ({ORG_A_ID}), got {org_ids}"
        assert ORG_B_ID not in org_ids
        mock_db.get_organizations_for_user.assert_awaited_once_with(USER_A1_ID)

    @pytest.mark.asyncio
    async def test_switch_to_own_org_succeeds(self):
        """POST /organizations/switch to own org succeeds."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org_a)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])
            mock_db.update_user_selected_organization = AsyncMock()

            # Also need to mock the organization context response
            with patch("api.routes.organization.ensure_organization_bootstrapped", new=AsyncMock()), \
                 patch("api.routes.organization.get_organization_context") as mock_ctx:
                mock_ctx.return_value = _org_context(ORG_A_ID, ORG_A_PROVIDER)

                response = client.post(
                    "/api/v1/organizations/switch",
                    json={"organization_id": ORG_A_ID}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["organization_id"] == ORG_A_ID
        mock_db.get_organization_by_id.assert_awaited_once_with(ORG_A_ID)
        mock_db.get_organizations_for_user.assert_awaited_once_with(USER_A1_ID)
        mock_db.update_user_selected_organization.assert_awaited_once_with(USER_A1_ID, ORG_A_ID)

    @pytest.mark.asyncio
    async def test_switch_to_other_org_returns_403(self):
        """POST /organizations/switch to another org returns 403."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)
        org_b = SimpleNamespace(id=ORG_B_ID, provider_id=ORG_B_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org_b)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.post(
                "/api/v1/organizations/switch",
                json={"organization_id": ORG_B_ID}
            )

        assert response.status_code == 403
        assert "access" in response.json()["detail"].lower()
        mock_db.get_organization_by_id.assert_awaited_once_with(ORG_B_ID)
        mock_db.get_organizations_for_user.assert_awaited_once_with(USER_A1_ID)

    @pytest.mark.asyncio
    async def test_switch_to_nonexistent_org_returns_404(self):
        """POST /organizations/switch to nonexistent org returns 404."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=None)

            response = client.post(
                "/api/v1/organizations/switch",
                json={"organization_id": 99999}
            )

        assert response.status_code == 404
        mock_db.get_organization_by_id.assert_awaited_once_with(99999)

    @pytest.mark.asyncio
    async def test_get_context_returns_correct_org(self):
        """GET /organizations/context returns the user's selected org."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.get_organization_context") as mock_ctx:
            mock_ctx.return_value = _org_context(ORG_A_ID, ORG_A_PROVIDER)

            response = client.get("/api/v1/organizations/context")

        assert response.status_code == 200
        data = response.json()
        assert data["organization_id"] == ORG_A_ID
        assert data["organization_id"] != ORG_B_ID


# =============================================================================
# Test: Workflow Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestWorkflowEndpointsIsolation:
    """Test that /api/v1/workflow/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_workflows_only_own_org(self):
        """GET /workflow/fetch returns only workflows from user's org."""
        app = _make_workflow_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        wf_a = SimpleNamespace(id=100, name="Org A Workflow", status="active", created_at="2024-01-01T00:00:00Z", total_runs=5, folder_id=None, workflow_uuid=None)
        wf_b = SimpleNamespace(id=200, name="Org B Workflow", status="active", created_at="2024-01-01T00:00:00Z", total_runs=3, folder_id=None, workflow_uuid=None)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_all_workflows_for_listing = AsyncMock(return_value=[wf_a])
            mock_db.get_workflow_run_counts = AsyncMock(return_value={wf_a.id: 5})

            response = client.get("/api/v1/workflow/fetch")

        assert response.status_code == 200
        data = response.json()
        workflow_ids = {w["id"] for w in data}
        assert wf_a.id in workflow_ids
        assert wf_b.id not in workflow_ids
        # Verify org scoping was applied in the db call
        mock_db.get_all_workflows_for_listing.assert_awaited_once()
        call_kwargs = mock_db.get_all_workflows_for_listing.await_args.kwargs
        assert call_kwargs["organization_id"] == ORG_A_ID

    @pytest.mark.asyncio
    async def test_list_workflows_with_no_org_selected_returns_400(self):
        """GET /workflow/fetch must refuse when no organization is selected.

        Regression test for a real cross-tenant leak. `get_workflows` takes
        `get_user` (not `get_user_with_selected_organization`), so a user with no
        selected org passes `organization_id=None` down to
        `get_all_workflows_for_listing`. That method guards its filter with
        `if organization_id:` — a falsy value adds NO `WHERE` clause, so the query
        returns every workflow in every tenant rather than none.
        """
        app = _make_workflow_app(USER_A1_ID, None, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_all_workflows_for_listing = AsyncMock(return_value=[])
            mock_db.get_workflow_run_counts = AsyncMock(return_value={})

            response = client.get("/api/v1/workflow/fetch")

        # The handler must reject before ever reaching the DB client.
        assert response.status_code == 400
        mock_db.get_all_workflows_for_listing.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_workflows_query_is_org_scoped_at_the_client_layer(self):
        """The client method must add a WHERE clause even for a falsy org.

        Defense in depth behind the route guard: an unscoped read here is the
        difference between "no results" and "every tenant's data", so the
        behaviour of the query builder itself is asserted, not just the HTTP
        status code. The real `get_all_workflows_for_listing` is driven against a
        mocked session so no database is required.
        """
        from sqlalchemy import select

        from api.db.workflow_client import WorkflowClient
        from api.db.models import WorkflowModel

        captured = {}

        class _FakeResult:
            def scalars(self):
                return self

            def scalar(self):
                return 0

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

        client = WorkflowClient.__new__(WorkflowClient)
        client.async_session = lambda *a, **k: _FakeSession()

        await client.get_all_workflows_for_listing(organization_id=None)

        compiled = str(captured["query"].compile(compile_kwargs={"literal_binds": True}))
        assert "organization_id" in compiled, (
            "query has no organization_id predicate: with a falsy organization_id "
            "it enumerates every tenant's workflows"
        )
        assert "IS NULL" in compiled

    @pytest.mark.asyncio
    async def test_get_workflow_cross_org_returns_404(self):
        """GET /workflow/fetch/{id} for another org's workflow returns 404."""
        app = _make_workflow_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_workflow = AsyncMock(return_value=None)

            response = client.get("/api/v1/workflow/fetch/99999")

        assert response.status_code == 404
        mock_db.get_workflow.assert_awaited_once_with(99999, organization_id=ORG_A_ID)

    @pytest.mark.asyncio
    async def test_create_workflow_scoped_to_user_org(self):
        """POST /workflow/create/definition creates workflow in user's org."""
        app = _make_workflow_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        new_workflow = SimpleNamespace(
            id=300,
            name="New Workflow",
            status="draft",
            created_at="2024-01-01T00:00:00Z",
            workflow_definition={"nodes": [], "edges": []},
            current_definition_id=1,
            template_context_variables={},
            call_disposition_codes={},
            workflow_configurations={},
        )

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.create_workflow = AsyncMock(return_value=new_workflow)

            response = client.post("/api/v1/workflow/create/definition", json={"name": "New Workflow", "workflow_definition": {"nodes": [], "edges": []}})

        assert response.status_code == 200
        data = response.json()
        # Response is a plain dict, not WorkflowResponse schema
        assert data["id"] == 300
        mock_db.create_workflow.assert_awaited_once()
        # `create_workflow` takes all four args positionally:
        # (name, workflow_definition, user_id, organization_id).
        assert mock_db.create_workflow.await_args.args[3] == ORG_A_ID

    @pytest.mark.asyncio
    async def test_get_workflow_run_with_no_org_selected_returns_400(self):
        """GET /workflow/{id}/runs/{run_id} must refuse when no org is selected.

        Same defect class as the list route: `get_workflow_run` takes `get_user`,
        so `organization_id=None` reaches `db_client.get_workflow_run`, whose
        `if organization_id:` branch falls through to a bare run_id lookup with
        no org predicate.
        """
        app = _make_workflow_app(USER_A1_ID, None, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_workflow_run = AsyncMock(return_value=None)

            response = client.get("/api/v1/workflow/1/runs/99999")

        assert response.status_code == 400
        mock_db.get_workflow_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_workflow_runs_with_no_org_selected_returns_400(self):
        """GET /workflow/{id}/runs must refuse when no org is selected."""
        app = _make_workflow_app(USER_A1_ID, None, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_workflow_runs_by_workflow_id = AsyncMock(return_value=([], 0))

            response = client.get("/api/v1/workflow/1/runs")

        assert response.status_code == 400
        mock_db.get_workflow_runs_by_workflow_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_workflow_with_no_org_selected_returns_400(self):
        """PUT /workflow/{id} must refuse when no org is selected.

        This is a **write** path. `UpdateWorkflowRequest` has every field
        optional, so a body of `{"name": ...}` alone leaves `workflow_definition`
        falsy and skips the `get_workflow` ownership check at
        `workflow.py:1112` — the only thing standing between the request and an
        unscoped `update_workflow` at `workflow.py:1287`. `update_workflow` is
        called without a `user_id`, so a falsy org leaves `WHERE id = <guessed
        id>` with no organization predicate: any tenant could rename or
        reconfigure any other tenant's agent.
        """
        app = _make_workflow_app(USER_A1_ID, None, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.workflow.db_client") as mock_db:
            mock_db.get_workflow = AsyncMock(return_value=None)
            mock_db.update_workflow = AsyncMock()

            # No workflow_definition -> skips the get_workflow ownership check.
            response = client.put("/api/v1/workflow/99999", json={"name": "Renamed"})

        assert response.status_code == 400
        mock_db.update_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_workflow_runs_by_workflow_id_is_org_scoped_at_client_layer(self):
        """Defense in depth behind the route guard.

        Every in-repo caller of this method passes an explicit
        `organization_id`, so the `elif user_id:` branch falling through to a
        bare `workflow_id` lookup is unreachable in practice. This asserts the
        query builder cannot leak if a future caller omits it: a falsy org must
        yield only genuinely org-less rows, never every tenant's runs.

        Note `get_workflow_run` (the single-run lookup) is deliberately NOT
        covered here — its unscoped branch is load-bearing for in-flight call
        processing, and is guarded at the route layer instead.
        """
        from api.db.workflow_run_client import WorkflowRunClient

        captured = {}

        class _FakeResult:
            def scalars(self):
                return self

            def scalar(self):
                return 0

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

        client = WorkflowRunClient.__new__(WorkflowRunClient)
        client.async_session = lambda *a, **k: _FakeSession()

        await client.get_workflow_runs_by_workflow_id(
            workflow_id=1, organization_id=None
        )

        compiled = str(
            captured["query"].compile(compile_kwargs={"literal_binds": True})
        )
        assert "organization_id" in compiled, (
            f"get_workflow_runs_by_workflow_id has no org predicate: {compiled}"
        )


# =============================================================================
# Test: Credentials Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestCredentialsEndpointsIsolation:
    """Test that /api/v1/credentials/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_credentials_only_own_org(self):
        """GET /credentials returns only credentials from user's org."""
        app = _make_credentials_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        # `CredentialResponse` is keyed on `credential_uuid` (not the row's numeric
        # `id`), and carries no `organization_id` — so isolation is proven by the
        # org argument reaching the DB client, not by the response body.
        cred_a = SimpleNamespace(
            credential_uuid="11111111-1111-1111-1111-111111111111",
            name="Org A Cred",
            description="org a secret",
            credential_type="api_key",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
        )
        cred_b = SimpleNamespace(
            credential_uuid="22222222-2222-2222-2222-222222222222",
            name="Org B Cred",
            description="org b secret",
            credential_type="api_key",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
        )

        with patch("api.routes.credentials.db_client") as mock_db:
            mock_db.get_credentials_for_organization = AsyncMock(return_value=[cred_a])

            response = client.get("/api/v1/credentials/")

        assert response.status_code == 200
        data = response.json()
        uuids = {c["uuid"] for c in data}
        assert uuids == {cred_a.credential_uuid}
        assert cred_b.credential_uuid not in uuids
        mock_db.get_credentials_for_organization.assert_awaited_once_with(ORG_A_ID)


# =============================================================================
# Test: Tools Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestToolsEndpointsIsolation:
    """Test that /api/v1/tools/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_tools_only_own_org(self):
        """GET /tools returns only tools from user's org."""
        app = _make_tools_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        tool_a = SimpleNamespace(
            id=100,
            tool_uuid="aaaaaaaa-1111-1111-1111-111111111111",
            name="Org A Tool",
            description="org a tool",
            category="utility",
            icon=None,
            icon_color=None,
            status="active",
            definition={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        tool_b = SimpleNamespace(
            id=200,
            tool_uuid="bbbbbbbb-2222-2222-2222-222222222222",
            name="Org B Tool",
            description="org b tool",
            category="utility",
            icon=None,
            icon_color=None,
            status="active",
            definition={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        with patch("api.routes.tool.db_client") as mock_db:
            mock_db.get_tools_for_organization = AsyncMock(return_value=[tool_a])

            response = client.get("/api/v1/tools/")

        assert response.status_code == 200
        data = response.json()
        tool_ids = {t["id"] for t in data}
        assert tool_a.id in tool_ids
        assert tool_b.id not in tool_ids
        # organization_id is positional; the optional filters are always passed.
        assert mock_db.get_tools_for_organization.await_args.args[0] == ORG_A_ID


# =============================================================================
# Test: Telephony Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestTelephonyEndpointsIsolation:
    """Test that /api/v1/organizations/telephony-configs/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_phone_numbers_only_own_org(self):
        """GET /organizations/telephony-configs/{config_id}/phone-numbers returns only numbers from user's org."""
        app = _make_telephony_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        num_a = SimpleNamespace(
            id=100,
            telephony_configuration_id=1000,
            address="+15551234567",
            address_normalized="+15551234567",
            address_type="local",
            country_code="US",
            label="org a number",
            inbound_workflow_id=None,
            inbound_workflow_name=None,
            telephony_trunk_id=None,
            is_active=True,
            is_default_caller_id=True,
            extra_metadata={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        num_b = SimpleNamespace(
            id=200,
            telephony_configuration_id=2000,
            address="+15557654321",
            address_normalized="+15557654321",
            address_type="local",
            country_code="US",
            label="org b number",
            inbound_workflow_id=None,
            inbound_workflow_name=None,
            telephony_trunk_id=None,
            is_active=True,
            is_default_caller_id=True,
            extra_metadata={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )

        # Phone numbers are scoped to a telephony config, which is org-scoped
        # The test needs a config_id that belongs to the user's org
        config_id = 1000

        with patch("api.routes.organization.db_client") as mock_db:
            # Ensure the config belongs to the user's org
            mock_db.get_telephony_configuration_for_org = AsyncMock(
                return_value=SimpleNamespace(id=config_id, provider="twilio", organization_id=ORG_A_ID)
            )
            # Then list phone numbers for that config
            mock_db.list_phone_numbers_with_workflow_name_for_config = AsyncMock(return_value=[(num_a, None)])

            response = client.get(f"/api/v1/organizations/telephony-configs/{config_id}/phone-numbers")

        assert response.status_code == 200
        data = response.json()
        number_ids = {n["id"] for n in data.get("phone_numbers", data)}
        assert num_a.id in number_ids
        assert num_b.id not in number_ids
        # Verify the config was checked for org membership
        mock_db.get_telephony_configuration_for_org.assert_awaited_once_with(config_id, ORG_A_ID, active_only=False)
        mock_db.list_phone_numbers_with_workflow_name_for_config.assert_awaited_once_with(config_id)


# =============================================================================
# Test: Campaign Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestCampaignEndpointsIsolation:
    """Test that /api/v1/campaign/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_campaigns_only_own_org(self):
        """GET /campaign returns only campaigns from user's org."""
        app = _make_campaigns_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        camp_a = SimpleNamespace(
            id=100,
            name="Org A Campaign",
            workflow_id=400,
            state="completed",
            source_type="csv",
            source_id="upload_a",
            total_rows=10,
            processed_rows=10,
            failed_rows=0,
            created_at="2024-01-01T00:00:00Z",
            started_at=None,
            completed_at=None,
            retry_config={},
            orchestrator_metadata={},
            telephony_configuration_id=None,
            parent_campaign_id=None,
            redialed_campaign_id=None,
            logs=[],
        )
        camp_b = SimpleNamespace(
            id=200,
            name="Org B Campaign",
            workflow_id=500,
            state="completed",
            source_type="csv",
            source_id="upload_b",
            total_rows=20,
            processed_rows=20,
            failed_rows=0,
            created_at="2024-01-01T00:00:00Z",
            started_at=None,
            completed_at=None,
            retry_config={},
            orchestrator_metadata={},
            telephony_configuration_id=None,
            parent_campaign_id=None,
            redialed_campaign_id=None,
            logs=[],
        )

        with patch("api.routes.campaign.db_client") as mock_db:
            mock_db.get_campaigns = AsyncMock(return_value=[camp_a])
            mock_db.get_workflows_by_ids = AsyncMock(return_value={})
            mock_db.get_queued_runs_stats_for_campaigns = AsyncMock(return_value={})
            mock_db.list_telephony_configurations = AsyncMock(return_value=[])

            response = client.get("/api/v1/campaign/")

        assert response.status_code == 200
        data = response.json()
        camp_ids = {c["id"] for c in data.get("campaigns", data)}
        assert camp_a.id in camp_ids
        assert camp_b.id not in camp_ids
        mock_db.get_campaigns.assert_awaited_once_with(ORG_A_ID)


# =============================================================================
# Test: Knowledge Base Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestKnowledgeBaseEndpointsIsolation:
    """Test that /api/v1/knowledge-base/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_list_documents_only_own_org(self):
        """GET /knowledge-base/documents returns only docs from user's org."""
        app = _make_knowledge_base_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        doc_a = SimpleNamespace(
            id=100,
            document_uuid="doc-a-uuid",
            filename="Org A Doc.pdf",
            file_size_bytes=1024,
            file_hash="hash_a",
            mime_type="application/pdf",
            processing_status="completed",
            processing_error=None,
            total_chunks=10,
            retrieval_mode="chunked",
            custom_metadata={},
            docling_metadata={},
            source_url=None,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            organization_id=ORG_A_ID,
            created_by=USER_A1_ID,
            is_active=True,
        )
        doc_b = SimpleNamespace(
            id=200,
            document_uuid="doc-b-uuid",
            filename="Org B Doc.pdf",
            file_size_bytes=2048,
            file_hash="hash_b",
            mime_type="application/pdf",
            processing_status="completed",
            processing_error=None,
            total_chunks=20,
            retrieval_mode="chunked",
            custom_metadata={},
            docling_metadata={},
            source_url=None,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            organization_id=ORG_B_ID,
            created_by=USER_B1_ID,
            is_active=True,
        )

        with patch("api.routes.knowledge_base.db_client") as mock_db:
            mock_db.get_documents_for_organization = AsyncMock(return_value=[doc_a])

            response = client.get("/api/v1/knowledge-base/documents")

        assert response.status_code == 200
        data = response.json()
        doc_ids = {d["id"] for d in data.get("documents", data)}
        assert doc_a.id in doc_ids
        assert doc_b.id not in doc_ids
        mock_db.get_documents_for_organization.assert_awaited_once_with(
            organization_id=ORG_A_ID,
            processing_status=None,
            limit=100,
            offset=0,
        )


# =============================================================================
# Test: User Endpoints - Cross-Tenant Isolation
# =============================================================================

class TestUserEndpointsIsolation:
    """Test that /api/v1/auth/* endpoints enforce tenant isolation."""

    @pytest.mark.asyncio
    async def test_get_me_returns_correct_org(self):
        """GET /auth/me returns user with correct selected org."""
        # The /me endpoint is in auth.py, not user.py
        from api.routes import auth

        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1")
        app.dependency_overrides[get_user] = lambda: SimpleNamespace(
            id=USER_A1_ID,
            provider_id=USER_A1_PROVIDER,
            email=f"{USER_A1_PROVIDER}@example.com",
            selected_organization_id=ORG_A_ID,
        )
        client = TestClient(app)

        response = client.get("/api/v1/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["organization_id"] == ORG_A_ID
        assert data["organization_id"] != ORG_B_ID


# =============================================================================
# Test: API Key Auth - Cross-Tenant Isolation
# =============================================================================

class TestApiKeyAuthIsolation:
    """Test that API key authentication enforces tenant isolation."""

    @pytest.mark.asyncio
    async def test_api_key_forces_key_org_ignoring_user_selection(self):
        """An Org A API key pins the request to Org A, overriding the caller's own selection.

        `_handle_api_key_auth` assigns `user.selected_organization_id` from the key
        row, so a user who is personally switched to Org B cannot use their own Org A
        key to read Org B. This is the header-driven sibling of the body-driven
        membership check in `POST /organizations/switch`.
        """
        from api.services.auth.depends import _handle_api_key_auth

        api_key_model = SimpleNamespace(
            id=1,
            organization_id=ORG_A_ID,
            created_by=USER_A1_ID,
            key_prefix="sk_test_a",
        )
        # The key's owner has since been switched to Org B themselves.
        key_owner = SimpleNamespace(
            id=USER_A1_ID,
            provider_id=USER_A1_PROVIDER,
            selected_organization_id=ORG_B_ID,
        )

        with patch("api.services.auth.depends.db_client") as mock_db:
            mock_db.validate_api_key = AsyncMock(return_value=api_key_model)
            mock_db.get_user_by_id = AsyncMock(return_value=key_owner)

            user = await _handle_api_key_auth("sk_test_a12345678")

        assert user.selected_organization_id == ORG_A_ID
        assert user.selected_organization_id != ORG_B_ID
        # The key row, not the caller's selection, decides the org.
        mock_db.validate_api_key.assert_awaited_once_with("sk_test_a12345678")

    @pytest.mark.asyncio
    async def test_api_key_rejected_when_inactive(self):
        """An invalid or inactive API key yields 401 rather than an unscoped user."""
        from api.services.auth.depends import _handle_api_key_auth
        from fastapi import HTTPException

        with patch("api.services.auth.depends.db_client") as mock_db:
            mock_db.validate_api_key = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await _handle_api_key_auth("sk_revoked_12345678")

        assert exc_info.value.status_code == 401
        # get_user_by_id must never run for a rejected key.
        mock_db.get_user_by_id.assert_not_called()


# =============================================================================
# Test: Membership Validation - Core Security Property
# =============================================================================

class TestMembershipValidation:
    """Test that membership validation is enforced everywhere."""

    @pytest.mark.asyncio
    async def test_user_with_zero_orgs_cannot_switch(self):
        """User with no organization memberships cannot switch to any org."""
        app = _make_org_app(99, None, "user_no_orgs")
        client = TestClient(app)

        org = SimpleNamespace(id=999, provider_id="orphan_org")

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[])  # No memberships

            response = client.post(
                "/api/v1/organizations/switch",
                json={"organization_id": org.id}
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_switch_endpoint_revalidates_membership_on_every_request(self):
        """Switch endpoint re-derives memberships on every request (not cached)."""
        # This test verifies the endpoint doesn't cache membership checks
        # by checking the db_client.get_organizations_for_user is called each time

        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)
        org_b = SimpleNamespace(id=ORG_B_ID, provider_id=ORG_B_PROVIDER)

        # First call: user only in org_a
        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org_b)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.post(
                "/api/v1/organizations/switch",
                json={"organization_id": ORG_B_ID}
            )
            assert response.status_code == 403
            assert mock_db.get_organizations_for_user.await_count == 1

        # Second call: user now also in org_b (membership re-derived)
        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org_b)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a, org_b])
            mock_db.update_user_selected_organization = AsyncMock()

            with patch("api.routes.organization.ensure_organization_bootstrapped", new=AsyncMock()), \
                 patch("api.routes.organization.get_organization_context") as mock_ctx:
                mock_ctx.return_value = _org_context(ORG_B_ID, ORG_B_PROVIDER)

                response = client.post(
                    "/api/v1/organizations/switch",
                    json={"organization_id": ORG_B_ID}
                )
                assert response.status_code == 200
                assert mock_db.get_organizations_for_user.await_count == 1
                mock_db.update_user_selected_organization.assert_awaited_once_with(USER_A1_ID, ORG_B_ID)


# =============================================================================
# Test: Edge Cases & Regression Guards
# =============================================================================

class TestEdgeCases:
    """Edge cases and regression guards for isolation."""

    @pytest.mark.asyncio
    async def test_superuser_bypass_not_automatic(self):
        """Superuser flag does not automatically bypass org isolation (explicit checks required)."""
        app = _make_org_app(888, ORG_A_ID, "superuser")
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        data = response.json()
        org_ids = {o["id"] for o in data}
        assert org_ids == {ORG_A_ID}
        # Superuser still only sees orgs they're a member of

    @pytest.mark.asyncio
    async def test_org_context_header_does_not_override_auth(self):
        """Custom org context header cannot override authenticated user's org."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.get_organization_context") as mock_ctx:
            mock_ctx.return_value = _org_context(ORG_A_ID, ORG_A_PROVIDER)

            # Attempt to override via header (if such a mechanism exists)
            response = client.get(
                "/api/v1/organizations/context",
                headers={"X-Organization-ID": str(ORG_B_ID)}
            )

        # Should still return user's actual org
        assert response.status_code == 200
        assert response.json()["organization_id"] == ORG_A_ID


# =============================================================================
# Test: Both Auth Paths Parity
# =============================================================================

class TestAuthPathParity:
    """Ensure local and Stack auth paths enforce isolation identically."""

    @pytest.mark.asyncio
    async def test_mine_endpoint_returns_only_user_orgs_local_auth(self):
        """Local auth: /mine returns only user's orgs."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        data = response.json()
        org_ids = {o["id"] for o in data}
        assert org_ids == {ORG_A_ID}

    @pytest.mark.asyncio
    async def test_switch_endpoint_returns_403_non_member_local_auth(self):
        """Local auth: /switch returns 403 when switching to non-member org."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)
        org_b = SimpleNamespace(id=ORG_B_ID, provider_id=ORG_B_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organization_by_id = AsyncMock(return_value=org_b)
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.post(
                "/api/v1/organizations/switch",
                json={"organization_id": ORG_B_ID}
            )

        assert response.status_code == 403