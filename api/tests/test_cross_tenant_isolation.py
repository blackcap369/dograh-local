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
from api.routes import organization, workflow, credentials, tool, telephony, campaign, knowledge_base, user, auth


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
# Test: Organization Display Name
# =============================================================================

class TestOrganizationName:
    """`organizations.name` is the user-facing label for a client organization.

    Before this column existed the only identifier was `provider_id`, an opaque
    machine string (`org_oss_1756200000_ab12cd34`). The sidebar rendered that
    directly, so an agency operator saw ids instead of client names.
    """

    @pytest.mark.asyncio
    async def test_mine_returns_org_name(self):
        """GET /organizations/mine surfaces the display name alongside the id."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(
            id=ORG_A_ID, provider_id=ORG_A_PROVIDER, name="Acme Corp"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Acme Corp"
        assert data[0]["id"] == ORG_A_ID
        assert data[0]["provider_id"] == ORG_A_PROVIDER

    @pytest.mark.asyncio
    async def test_mine_tolerates_org_without_a_name(self):
        """An org with no name still lists, with `name: null` rather than a 500.

        The column is nullable, and pre-existing rows are backfilled by migration
        -- but a row created through any path that predates the backfill, or by a
        caller that passes no name, must not break the switcher.
        """
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        # No `name` attribute at all -- matches an ORM row from a stale model.
        org_legacy = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_legacy])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] is None
        # The switcher falls back to provider_id, so it must still be present.
        assert data[0]["provider_id"] == ORG_A_PROVIDER

    @pytest.mark.asyncio
    async def test_mine_does_not_leak_name_across_tenants(self):
        """Only the caller's own orgs are named in the response."""
        app = _make_org_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        org_a = SimpleNamespace(
            id=ORG_A_ID, provider_id=ORG_A_PROVIDER, name="Acme Corp"
        )
        org_b = SimpleNamespace(
            id=ORG_B_ID, provider_id=ORG_B_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.get_organizations_for_user = AsyncMock(return_value=[org_a])

            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200
        names = {o["name"] for o in response.json()}
        assert names == {"Acme Corp"}
        assert "Globex" not in names

    @pytest.mark.asyncio
    async def test_signup_creates_org_with_the_supplied_name(self):
        """The signup form's name seeds the org, not just the user."""
        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1")
        client = TestClient(app)

        created_user = SimpleNamespace(
            id=USER_A1_ID,
            provider_id=USER_A1_PROVIDER,
            email="owner@acme-corp.com",
        )
        created_org = SimpleNamespace(id=ORG_A_ID, provider_id=ORG_A_PROVIDER)

        with (
            patch("api.routes.auth.ENABLE_SIGNUP", True),
            patch("api.routes.auth.db_client") as mock_db,
            patch("api.routes.auth.ensure_organization_bootstrapped", new=AsyncMock()),
        ):
            mock_db.get_user_by_email = AsyncMock(return_value=None)
            mock_db.create_user_with_email = AsyncMock(return_value=created_user)
            mock_db.get_or_create_organization_by_provider_id = AsyncMock(
                return_value=(created_org, True)
            )
            mock_db.add_user_to_organization = AsyncMock()
            mock_db.update_user_selected_organization = AsyncMock()

            response = client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "owner@acme-corp.com",
                    "password": "correct-horse-battery-staple",
                    "name": "Acme Corp",
                },
            )

        assert response.status_code in (200, 201), response.text
        _, kwargs = (
            mock_db.get_or_create_organization_by_provider_id.await_args
        )
        assert kwargs.get("name") == "Acme Corp", (
            "signup must pass the submitted name through to the org, otherwise the "
            "sidebar falls back to the opaque provider_id forever"
        )


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


# =============================================================================
# Test: Organization Creation ("New Business")
# =============================================================================

NEW_ORG_ID = 900
NEW_ORG_PROVIDER = "org_local_10_deadbeef"


def _make_create_app(user_id: int, org_id: int, provider_id: str) -> FastAPI:
    """App for org-creation, with the caller maybe already inside an organization.

    Identical to `_make_org_app` in construction; a separate name only because
    creation is the one org route that must also work for a user with no organization
    at all, so `org_id` is passed as None in that case.
    """
    app = FastAPI()
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=provider_id,
        selected_organization_id=org_id,
    )
    return app


class TestOrganizationCreation:
    """`POST /organizations` is how an agency onboards client #2, #3, ... .

    Until it existed, the only org-creating calls in the repo were signup (id =
    `org_{user.provider_id}`, and a duplicate email 409s) and the dead Stack path. So
    onboarding a second client meant signing up with a second email address -- a second
    *user* who is not a member of the first business and who cannot be added to it.
    """

    @pytest.mark.asyncio
    async def test_create_organization_returns_the_new_org(self):
        """The endpoint echoes the org it just created, name included.

        Returning the row (rather than a bare 201) is what lets the switcher add the
        option immediately without a second round trip.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={"name": "Globex"})

        assert response.status_code in (200, 201), response.text
        data = response.json()
        assert data["id"] == NEW_ORG_ID
        assert data["name"] == "Globex"
        assert data["provider_id"] == NEW_ORG_PROVIDER

    @pytest.mark.asyncio
    async def test_creator_is_added_as_a_member(self):
        """The creator must be a member of the org they just made.

        Without the membership row the new org would not appear in GET
        /organizations/mine, so the switcher could never offer it -- the create would
        look like it silently did nothing.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            client.post("/api/v1/organizations", json={"name": "Globex"})

            mock_db.add_user_to_organization.assert_awaited_once_with(
                USER_A1_ID, NEW_ORG_ID
            )

    @pytest.mark.asyncio
    async def test_new_org_appears_in_mine(self):
        """End-to-end of the two halves: create, then list."""
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )
        org_a = SimpleNamespace(
            id=ORG_A_ID, provider_id=ORG_A_PROVIDER, name="Acme Corp"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()
            mock_db.get_organizations_for_user = AsyncMock(
                return_value=[org_a, created]
            )

            create_response = client.post(
                "/api/v1/organizations", json={"name": "Globex"}
            )
            mine_response = client.get("/api/v1/organizations/mine")

        assert create_response.status_code in (200, 201)
        assert mine_response.status_code == 200
        assert {o["id"] for o in mine_response.json()} == {ORG_A_ID, NEW_ORG_ID}

    @pytest.mark.asyncio
    async def test_provider_id_is_minted_server_side_not_taken_from_body(self):
        """The caller cannot choose the lookup key.

        `provider_id` is the only key organizations are looked up by, so a
        request-supplied value would let one tenant collide with, or impersonate,
        another's org. It is generated here and the body is name-only.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post(
                "/api/v1/organizations",
                json={"name": "Globex", "provider_id": ORG_B_PROVIDER},
            )

        assert response.status_code in (200, 201), response.text
        _, kwargs = mock_db.create_organization.await_args
        assert kwargs.get("provider_id") != ORG_B_PROVIDER, (
            "a caller-supplied provider_id would collide with another tenant's org"
        )
        assert str(kwargs.get("provider_id", "")).startswith("org_local_")

    @pytest.mark.asyncio
    async def test_two_creates_yield_two_distinct_orgs(self):
        """One user holds many businesses, so the id cannot be user-derived.

        Signup's `org_{user.provider_id}` is 1:1 with a user and would collide the
        moment the same user created a second business. This is the regression guard
        for that.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        id=900, provider_id="org_local_10_aaaaaaaa", name="A"
                    ),
                    SimpleNamespace(
                        id=901, provider_id="org_local_10_bbbbbbbb", name="B"
                    ),
                ]
            )
            mock_db.add_user_to_organization = AsyncMock()

            first = client.post("/api/v1/organizations", json={"name": "A"})
            second = client.post("/api/v1/organizations", json={"name": "B"})

        assert first.status_code in (200, 201), first.text
        assert second.status_code in (200, 201), second.text
        assert first.json()["id"] != second.json()["id"]
        assert first.json()["provider_id"] != second.json()["provider_id"]

        minted = [
            c.kwargs.get("provider_id")
            for c in mock_db.create_organization.await_args_list
        ]
        assert len(set(minted)) == 2, (
            f"both creates minted the same provider_id {minted} -- the second would "
            "silently return the first business instead of creating a new one"
        )

    @pytest.mark.asyncio
    async def test_create_does_not_switch_the_active_organization(self):
        """Creating client #3 while working in #1 must not yank you into #3.

        An auto-switch would silently change every org-scoped query the page makes
        next, so an agent created moments later would land in the wrong business. The
        dropdown should simply gain an option.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()
            mock_db.update_user_selected_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={"name": "Globex"})

            mock_db.update_user_selected_organization.assert_not_awaited()

        assert response.status_code in (200, 201), response.text

    @pytest.mark.asyncio
    async def test_create_mints_no_api_key(self):
        """A new business starts with zero API keys.

        Org creation used to auto-mint a "Default API Key" whose raw value is stored
        only as a hash and is therefore shown to nobody -- an unusable secret that
        cannot be recovered. At onboarding volume (one per client) that is a key per
        business nobody can ever read back. Keys are created explicitly on the
        Developers page instead.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={"name": "Globex"})

            # The status assertion is what makes this test non-vacuous: without the
            # route, `assert_not_called` would pass against a router that does nothing
            # at all, which is exactly the failure this test exists to rule out.
            assert response.status_code in (200, 201), response.text
            mock_db.create_api_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_works_with_no_organization_selected(self):
        """A user with no business can still create their first one.

        This is why the route takes `get_user` and not
        `get_user_with_selected_organization`, which 400s on a null selection.
        """
        app = _make_create_app(USER_A1_ID, None, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={"name": "Globex"})

        assert response.status_code in (200, 201), response.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_name", ["", "   ", "x" * 101])
    async def test_blank_whitespace_and_oversized_names_are_rejected(self, bad_name):
        """The label is the only thing distinguishing clients in a dropdown.

        An empty row or a one-character row is unusable, and there is no server-side
        cap on the column, so the bound is enforced here.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock()
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={"name": bad_name})

        assert response.status_code in (400, 422), response.text
        mock_db.create_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_name_is_required(self):
        """A missing name is a validation error, not a nameless org."""
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        with patch("api.routes.organization.db_client") as mock_db:
            mock_db.create_organization = AsyncMock()
            mock_db.add_user_to_organization = AsyncMock()

            response = client.post("/api/v1/organizations", json={})

        assert response.status_code in (400, 422), response.text
        mock_db.create_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_is_404_under_non_local_auth(self):
        """Under Stack auth the active team is owned by Stack, not by us.

        Mirrors the gate on POST /switch: an org created here would not be the
        org `get_user` resolves to, so the write would be invisible. 404 rather than
        403 so the route does not advertise itself in a deployment that cannot use it.
        """
        app = _make_create_app(USER_A1_ID, ORG_A_ID, USER_A1_PROVIDER)
        client = TestClient(app)

        created = SimpleNamespace(
            id=NEW_ORG_ID, provider_id=NEW_ORG_PROVIDER, name="Globex"
        )

        with (
            patch("api.routes.organization.AUTH_PROVIDER", "stack"),
            patch("api.routes.organization.db_client") as mock_db,
        ):
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            gated = client.post("/api/v1/organizations", json={"name": "Globex"})

        assert gated.status_code == 404
        mock_db.create_organization.assert_not_awaited()

        # Same app, same body, local auth: proves the 404 above came from the gate
        # rather than the route simply not existing -- which would also be a 404, and
        # would make this test pass against an implementation that is never mounted.
        with (
            patch("api.routes.organization.AUTH_PROVIDER", "local"),
            patch("api.routes.organization.db_client") as mock_db,
        ):
            mock_db.create_organization = AsyncMock(return_value=created)
            mock_db.add_user_to_organization = AsyncMock()

            allowed = client.post("/api/v1/organizations", json={"name": "Globex"})

        assert allowed.status_code in (200, 201), (
            f"under local auth the same request must succeed; got {allowed.status_code} "
            "-- the 404 above may just be a missing route"
        )