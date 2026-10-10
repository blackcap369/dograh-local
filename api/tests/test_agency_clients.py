"""Creative Mode: the agency-operator surface over every business on the instance.

Creative Mode is not itself an organization. It is a cross-org view the agency
operator uses to onboard, rename, archive, and remove *clients*, and it is
deliberately kept out of the org switcher and the per-organization pages: managing
client #4 is an operator's job, and surfacing it inside client #2's Models page is
exactly the chaos this mode exists to remove.

These tests follow the repo convention (bare FastAPI app + TestClient +
`patch(db_client)` with AsyncMock) established in test_cross_tenant_isolation.py.

Coverage:
  - list every business, with per-business resource counts
  - archive hides a business from the org switcher while keeping its data
  - rename changes the display label and never the lookup key
  - delete is refused for a business with real work, and permitted for an empty one
"""

import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.depends import get_user
from api.routes import agency, organization


# =============================================================================
# Fixtures / helpers
# =============================================================================

OPERATOR_ID = 10
OPERATOR_PROVIDER = "user_operator"

ACME = SimpleNamespace(
    id=1, provider_id="org_oss_1_acme", name="Acme Dental", archived=False
)
GLOBEX = SimpleNamespace(
    id=2, provider_id="org_oss_2_globex", name="Globex Legal", archived=False
)
INITIATIVE = SimpleNamespace(
    id=3, provider_id="org_oss_3_initech", name="Initech", archived=True
)


def _make_agency_app(
    user_id: int = OPERATOR_ID,
    org_id: int | None = None,
    agency_role: str = "owner",
) -> FastAPI:
    """App exposing both routers, as api/app.py does.

    `org_id` is the operator's *selected* organization, which is irrelevant to the
    agency routes on purpose: Creative Mode is not scoped to it. It is set anyway so
    a regression that starts reading `selected_organization_id` is visible.

    `agency_role` defaults to owner because the suite was written when the
    operator gate passed every authenticated user -- these tests assert what an
    OWNER can do. Staff behavior has its own suite (test_agency_roles.py); a
    default of staff here would have flipped every test in this file to 403 in
    one silent step.
    """
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=OPERATOR_PROVIDER,
        selected_organization_id=org_id,
        agency_role=agency_role,
    )
    return app


def _all_clients() -> list:
    """Every non-archived business, as `list_all_organizations` returns them."""
    return [ACME, GLOBEX]


def _counts() -> dict:
    """Per-business resource counts.

    Acme is the worked-in business: agents, calls, and phone numbers, so it is the
    one the delete guard must refuse. Globex is the freshly-onboarded one -- zero of
    everything -- so it is the one the guard must allow. That contrast is the whole
    test surface; a business that is neither is not represented.

    `member_count` is included but is deliberately NOT a delete blocker: the
    creator is always a member, so a business with nothing else in it still has one.
    Blocking on members would make every freshly-created business undeletable and
    the guard useless.
    """
    return {
        1: {
            "workflow_count": 4,
            "run_count": 128,
            "phone_number_count": 2,
            "member_count": 3,
        },
        2: {
            "workflow_count": 0,
            "run_count": 0,
            "phone_number_count": 0,
            "member_count": 1,
        },
    }


def _patched_client(active_org_id: int | None = None):
    """A db_client mock with every agency read wired, for the happy paths."""
    mock_db = AsyncMock()
    mock_db.list_all_organizations = AsyncMock(return_value=_all_clients())
    mock_db.get_organization_resource_counts = AsyncMock(return_value=_counts())
    mock_db.get_organizations_for_user = AsyncMock(return_value=_all_clients())
    mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
    return mock_db


# =============================================================================
# Listing every business
# =============================================================================


class TestAgencyClientListing:
    """`GET /agency/clients` is the Clients page's only read.

    It is the one deliberately cross-organization query in this fork. Everything else
    derives `organization_id` from the session; this list is scoped by nothing but
    the operator gate, which is why that gate is a single named check rather than an
    inline condition.
    """

    @pytest.mark.asyncio
    async def test_lists_every_business_with_counts(self):
        app = _make_agency_app()
        client = TestClient(app)

        with patch("api.routes.agency.db_client", _patched_client()):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        body = response.json()
        ids = [c["id"] for c in body]
        assert ids == [ACME.id, GLOBEX.id], "every business must be listed"

        acme = next(c for c in body if c["id"] == ACME.id)
        assert acme["workflow_count"] == 4
        assert acme["run_count"] == 128
        assert acme["phone_number_count"] == 2

    @pytest.mark.asyncio
    async def test_label_falls_back_to_provider_id_when_unnamed(self):
        """An org predating the `name` column must still render a usable label.

        `name` is nullable by design, so the agency listing cannot assume it.
        """
        app = _make_agency_app()
        client = TestClient(app)

        unnamed = SimpleNamespace(
            id=7, provider_id="org_oss_7_legacy", name=None, archived=False
        )
        mock_db = _patched_client()
        mock_db.list_all_organizations = AsyncMock(return_value=[unnamed])
        mock_db.get_organization_resource_counts = AsyncMock(return_value={})

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        assert response.json()[0]["label"] == "org_oss_7_legacy"

    @pytest.mark.asyncio
    async def test_archived_businesses_are_excluded(self):
        """Archived means "out of the way", not "gone".

        Initech is archived in the fixture; it must not be offered as a client to
        work on, and its counts must not be fetched at all.

        The mock deliberately returns an archived row so the route is forced to
        drop it. That is the belt; the braces are the query filter, pinned
        separately by `test_mine_asks_the_client_for_unarchived_rows_only`. An
        earlier draft of this test asserted the opposite -- that a route-level
        filter would "hide a missing WHERE clause" -- which is not a property
        worth having. Dropping an archived row twice is free; leaking one is not.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        # Deliberately does NOT filter client-side: the exclusion is the query's
        # job, so a client-side filter would hide a missing WHERE clause.
        mock_db.list_all_organizations = AsyncMock(
            return_value=[ACME, GLOBEX, INITIATIVE]
        )

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        assert {c["id"] for c in response.json()} == {ACME.id, GLOBEX.id}

    @pytest.mark.asyncio
    async def test_counts_default_to_zero_for_a_business_missing_from_the_map(self):
        """A brand-new business has no rows; absence must render 0, not crash.

        The counts query groups by organization, so an org with no workflows simply
        has no group. Treating that as a lookup error would make the page fail the
        instant the operator creates their first client.
        """
        app = _make_agency_app()
        client = TestClient(app)

        fresh = SimpleNamespace(
            id=99, provider_id="org_local_10_fresh01", name="Fresh Co", archived=False
        )
        mock_db = _patched_client()
        mock_db.list_all_organizations = AsyncMock(return_value=[fresh])
        mock_db.get_organization_resource_counts = AsyncMock(return_value={})

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients")

        assert response.status_code == 200, response.text
        row = response.json()[0]
        assert row["workflow_count"] == 0
        assert row["run_count"] == 0


# =============================================================================
# Renaming
# =============================================================================


class TestAgencyClientRename:
    """`PATCH /agency/clients/{id}` renames the display label only."""

    @pytest.mark.asyncio
    async def test_rename_updates_the_label(self):
        app = _make_agency_app()
        client = TestClient(app)

        renamed = SimpleNamespace(
            id=ACME.id, provider_id=ACME.provider_id, name="Acme Dental Group"
        )
        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.rename_organization = AsyncMock(return_value=renamed)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}",
                json={"name": "Acme Dental Group"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Acme Dental Group"

    @pytest.mark.asyncio
    async def test_rename_never_changes_provider_id(self):
        """The regression guard for the whole reason rename is a separate concern.

        `provider_id` is the sole key organizations are looked up by. A rename that
        touched it would break every stored reference to the business -- the
        selected org on each member, the org stamped on every workflow and call
        record. The route takes `provider_id` from the row, never from the body.
        """
        app = _make_agency_app()
        client = TestClient(app)

        renamed = SimpleNamespace(
            id=ACME.id, provider_id=ACME.provider_id, name="Renamed"
        )
        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.rename_organization = AsyncMock(return_value=renamed)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}",
                json={"name": "Renamed", "provider_id": "org_oss_9_hijacked"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["provider_id"] == ACME.provider_id

        _, kwargs = mock_db.rename_organization.await_args
        assert "provider_id" not in kwargs, (
            "rename must not be able to write provider_id"
        )

    @pytest.mark.asyncio
    async def test_rename_rejects_a_blank_name(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.rename_organization = AsyncMock()

        with patch("api.routes.agency.db_client", mock_db):
            response = client.patch(
                f"/api/v1/agency/clients/{ACME.id}", json={"name": "   "}
            )

        assert response.status_code == 422, response.text
        mock_db.rename_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rename_of_a_missing_business_is_404(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=None)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.patch(
                "/api/v1/agency/clients/4242", json={"name": "Ghost"}
            )

        assert response.status_code == 404, response.text


# =============================================================================
# Deleting
# =============================================================================


class TestAgencyClientDeleteGuard:
    """Delete trashes a business: reversible, so nothing is guarded here.

    The V2.1e recovery trash moved the impact guard off delete and onto the
    purge: trashing destroys nothing (every default lookup filters the row
    out), so a business with work history is trashed exactly like an empty
    one. What delete must still do is clear member selections -- anyone left
    standing in a trashed business would point at a row the default lookups
    refuse to resolve -- and it must NOT clear memberships or the row, so a
    restore brings everything back.
    """

    @pytest.mark.asyncio
    async def test_delete_impact_reports_what_would_be_lost(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get(f"/api/v1/agency/clients/{ACME.id}/delete-impact")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["workflow_count"] == 4
        assert body["run_count"] == 128
        assert body["deletable"] is False

    @pytest.mark.asyncio
    async def test_delete_trashes_a_business_with_work(self):
        """Acme has 4 workflows and 128 call runs. Trashing it is still safe.

        The old impact guard lived here because delete destroyed data. It
        destroys nothing now -- the row and its history survive in the trash
        -- so history is no longer a reason to refuse. The guard moved to the
        purge, where destruction is real (see TestTrashPurge).
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.mark_organization_deleted = AsyncMock(return_value=ACME)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/clients/{ACME.id}")

        assert response.status_code in (200, 204), response.text
        mock_db.mark_organization_deleted.assert_awaited_once_with(ACME.id)
        mock_db.delete_organization.assert_not_awaited(), (
            "trash must never hard-delete the row"
        )

    @pytest.mark.asyncio
    async def test_delete_succeeds_for_an_empty_business(self):
        """The empty-business case trashes identically to the full one."""
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=GLOBEX)
        mock_db.mark_organization_deleted = AsyncMock(return_value=GLOBEX)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/clients/{GLOBEX.id}")

        assert response.status_code in (200, 204), response.text
        mock_db.mark_organization_deleted.assert_awaited_once_with(GLOBEX.id)

    @pytest.mark.asyncio
    async def test_delete_clears_member_selection(self):
        """`users.selected_organization_id` must not keep pointing at a trashed row.

        The default lookups refuse a trashed business, so a member still standing
        in it would turn every subsequent request into a failure. Selections are
        cleared at trash time; memberships are not, because restore has to bring
        the team back with the business.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=GLOBEX)
        mock_db.clear_selected_organization_references = AsyncMock()
        mock_db.mark_organization_deleted = AsyncMock(return_value=GLOBEX)

        with patch("api.routes.agency.db_client", mock_db):
            client.delete(f"/api/v1/agency/clients/{GLOBEX.id}")

        mock_db.clear_selected_organization_references.assert_awaited_once_with(
            GLOBEX.id
        )

    @pytest.mark.asyncio
    async def test_delete_keeps_membership_rows_for_restore(self):
        """Trash must not touch `organization_users`.

        The entire point of the recovery trash is that restore brings the
        business back exactly as it was -- its member list included. Clearing
        memberships here would make restore a partial recovery; the membership
        cleanup belongs to the purge, where the business is really leaving.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=GLOBEX)
        mock_db.clear_selected_organization_references = AsyncMock()
        mock_db.clear_organization_users = AsyncMock()
        mock_db.mark_organization_deleted = AsyncMock(return_value=GLOBEX)

        with patch("api.routes.agency.db_client", mock_db):
            client.delete(f"/api/v1/agency/clients/{GLOBEX.id}")

        mock_db.clear_organization_users.assert_not_awaited()
        mock_db.delete_organization.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_of_a_missing_business_is_404(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=None)
        mock_db.delete_organization = AsyncMock()

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete("/api/v1/agency/clients/4242")

        assert response.status_code == 404, response.text
        mock_db.delete_organization.assert_not_awaited()


# =============================================================================
# Archiving
# =============================================================================


class TestAgencyClientArchive:
    """Archive is the safe default action: it hides, it does not destroy."""

    @pytest.mark.asyncio
    async def test_archive_flags_the_business(self):
        app = _make_agency_app()
        client = TestClient(app)

        archived = SimpleNamespace(
            id=ACME.id, provider_id=ACME.provider_id, name=ACME.name, archived=True
        )
        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.set_organization_archived = AsyncMock(return_value=archived)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(f"/api/v1/agency/clients/{ACME.id}/archive")

        assert response.status_code in (200, 204), response.text
        mock_db.set_organization_archived.assert_awaited_once_with(ACME.id, True)

    @pytest.mark.asyncio
    async def test_unarchive_restores_it(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=INITIATIVE)
        mock_db.set_organization_archived = AsyncMock(return_value=ACME)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.post(f"/api/v1/agency/clients/{INITIATIVE.id}/unarchive")

        assert response.status_code in (200, 204), response.text
        mock_db.set_organization_archived.assert_awaited_once_with(
            INITIATIVE.id, False
        )

    @pytest.mark.asyncio
    async def test_archiving_does_not_touch_the_business_data(self):
        """Archive must be reversible, so it cannot cascade.

        The assertion is on what the route does *not* call: if archiving invoked any
        of the cascade-on-delete paths, un-archiving would come back to an empty
        business.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.set_organization_archived = AsyncMock()

        with patch("api.routes.agency.db_client", mock_db):
            client.post(f"/api/v1/agency/clients/{ACME.id}/archive")

        mock_db.delete_organization.assert_not_awaited()


# =============================================================================
# The org switcher stays clean
# =============================================================================


class TestSwitcherStaysClean:
    """The switcher lists businesses to *work in*. It does not manage them.

    This is the user's correction made testable: create/rename/archive/delete belong
    to Creative Mode, so the switcher's read path filters archived businesses out and
    exposes no mutation of its own.
    """

    @pytest.mark.asyncio
    async def test_mine_excludes_archived_businesses(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organizations_for_user = AsyncMock(return_value=[ACME, GLOBEX])

        with patch("api.routes.organization.db_client", mock_db):
            response = client.get("/api/v1/organizations/mine")

        assert response.status_code == 200, response.text
        assert {o["id"] for o in response.json()} == {ACME.id, GLOBEX.id}

    @pytest.mark.asyncio
    async def test_mine_asks_the_client_for_unarchived_rows_only(self):
        """The filter belongs in the query, not in a post-hoc `if not o.archived`.

        A client-side filter would still ship the archived business's name over the
        wire; the test asserts the flag reaches the database layer.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organizations_for_user = AsyncMock(return_value=[ACME])

        with patch("api.routes.organization.db_client", mock_db):
            client.get("/api/v1/organizations/mine")

        _, kwargs = mock_db.get_organizations_for_user.await_args
        assert kwargs.get("include_archived") is False, (
            "the switcher read must exclude archived businesses at the query"
        )

    @pytest.mark.asyncio
    async def test_no_rename_or_delete_routes_under_the_organizations_prefix(self):
        """Managing a business is an agency action, so it must not be org-scoped.

        An org-scoped rename would authorize on the operator's *selected*
        organization, which is arbitrary in Creative Mode -- the business being
        renamed is usually not the one they are standing in.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.rename_organization = AsyncMock()
        mock_db.delete_organization = AsyncMock()

        with patch("api.routes.organization.db_client", mock_db), patch(
            "api.routes.agency.db_client", mock_db
        ):
            patch_response = client.patch(
                f"/api/v1/organizations/{ACME.id}", json={"name": "Nope"}
            )
            delete_response = client.delete(f"/api/v1/organizations/{ACME.id}")

        assert patch_response.status_code == 404
        assert delete_response.status_code == 404
        mock_db.rename_organization.assert_not_awaited()
        mock_db.delete_organization.assert_not_awaited()


# =============================================================================
# The real count queries (regression: mock-invisible SQL)
# =============================================================================


class TestResourceCountsQueries:
    """The real resource-count queries must build and be org-scoped.

    The route tests above mock `db_client` wholesale, which is exactly how a
    query referencing a nonexistent column shipped green: `workflow_runs` has
    no `organization_id` (runs scope through their workflow), so the committed
    run-count query raised `AttributeError` the first time a real browser hit
    the Clients page. These tests drive the actual
    `get_organization_resource_counts` against a mocked session -- no database,
    but the real query objects are built and inspected, which is where that bug
    lived.
    """

    @pytest.mark.asyncio
    async def test_count_queries_build_against_real_models(self):
        from api.db.organization_client import OrganizationClient

        captured = []

        class _FakeResult:
            def all(self):
                return []

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, query):
                captured.append(query)
                return _FakeResult()

        client = OrganizationClient.__new__(OrganizationClient)
        client.async_session = lambda *a, **k: _FakeSession()

        counts = await client.get_organization_resource_counts([1, 2])

        # No rows came back, so every count is zero -- but the dict itself must
        # still be complete for every requested id. A sparse entry here became a
        # KeyError deep in the delete guard for a business that had members but
        # nothing else (the member query creates the entry; nothing else does).
        assert counts == {
            1: {
                "workflow_count": 0,
                "run_count": 0,
                "phone_number_count": 0,
                "member_count": 0,
            },
            2: {
                "workflow_count": 0,
                "run_count": 0,
                "phone_number_count": 0,
                "member_count": 0,
            },
        }
        # workflows, workflow_runs (via join), phone numbers, members.
        assert len(captured) == 4

    @pytest.mark.asyncio
    async def test_partial_rows_still_yield_complete_counts(self):
        """A business with only members gets full keys, not a one-key dict.

        Each grouped query contributes only the rows it finds, so a naive
        build-the-dict-as-you-go approach leaves every other key missing. The
        delete guard indexes three of the four keys unconditionally.
        """
        from api.db.organization_client import OrganizationClient

        # Simulate the real pattern: only the member query finds a row.
        responses = iter([[], [], [], [(7, 1)]])

        class _FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, query):
                return _FakeResult(next(responses))

        client = OrganizationClient.__new__(OrganizationClient)
        client.async_session = lambda *a, **k: _FakeSession()

        counts = await client.get_organization_resource_counts([7])

        assert counts == {
            7: {
                "workflow_count": 0,
                "run_count": 0,
                "phone_number_count": 0,
                "member_count": 1,
            }
        }

    @pytest.mark.asyncio
    async def test_run_count_is_scoped_through_the_workflows_join(self):
        """Run counts must come from workflow_runs JOIN workflows.

        A run belongs to the org of the workflow it executed. The compiled SQL
        is asserted directly: the join supplies the org column, and the WHERE
        clause carries the organization predicate, so a run of another tenant
        can never enter this business's numbers.
        """
        from api.db.organization_client import OrganizationClient

        captured = []

        class _FakeResult:
            def all(self):
                return []

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, query):
                captured.append(query)
                return _FakeResult()

        client = OrganizationClient.__new__(OrganizationClient)
        client.async_session = lambda *a, **k: _FakeSession()

        await client.get_organization_resource_counts([1, 2])

        # Pick the run-count query by what it queries, not by position: the
        # method issues one query per table and their order is not the contract.
        run_queries = [
            q
            for q in captured
            if "workflow_runs" in str(q.compile(compile_kwargs={"literal_binds": True}))
        ]
        assert len(run_queries) == 1, (
            f"expected exactly one workflow_runs query, got {len(run_queries)}"
        )
        run_query_sql = str(
            run_queries[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "JOIN workflows" in run_query_sql, (
            f"run count must scope through the workflows join: {run_query_sql}"
        )
        assert "organization_id" in run_query_sql, (
            f"run count has no organization predicate: {run_query_sql}"
        )


# =============================================================================
# The single-client read
# =============================================================================


class TestAgencyClientGet:
    """GET /agency/clients/{id} returns one business, archived included.

    The list filters archived businesses because it *offers* places to work.
    The detail read must not filter, because the operator who archived a
    business still needs to open it and restore it -- without an
    archived-readable read, unarchive exists only as a raw API call.
    """

    @pytest.mark.asyncio
    async def test_get_returns_the_business_with_counts(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get(f"/api/v1/agency/clients/{ACME.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == ACME.id
        assert body["label"] == "Acme Dental"
        assert body["workflow_count"] == 4
        assert body["run_count"] == 128
        assert body["archived"] is False

    @pytest.mark.asyncio
    async def test_archived_business_is_readable_for_restore(self):
        """The archived row comes back from the detail read.

        INITIATIVE is the archived business in the fixtures. The list excludes
        it (pinned in TestSwitcherStaysClean); this read must not.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=INITIATIVE)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get(f"/api/v1/agency/clients/{INITIATIVE.id}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["archived"] is True
        assert body["label"] == "Initech"

    @pytest.mark.asyncio
    async def test_get_of_a_missing_business_is_404(self):
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=None)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.get("/api/v1/agency/clients/4242")

        assert response.status_code == 404, response.text
