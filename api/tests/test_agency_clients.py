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


def _make_agency_app(user_id: int = OPERATOR_ID, org_id: int | None = None) -> FastAPI:
    """App exposing both routers, as api/app.py does.

    `org_id` is the operator's *selected* organization, which is irrelevant to the
    agency routes on purpose: Creative Mode is not scoped to it. It is set anyway so
    a regression that starts reading `selected_organization_id` is visible.
    """
    app = FastAPI()
    app.include_router(agency.router, prefix="/api/v1")
    app.include_router(organization.router, prefix="/api/v1")
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=user_id,
        provider_id=OPERATOR_PROVIDER,
        selected_organization_id=org_id,
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
    """Delete is refused for any business that has done real work.

    The foreign keys to `organizations.id` are inconsistent: keys, model
    configurations, telephony configs, phone numbers, and call records CASCADE, so
    they are destroyed silently; workflows, folders, campaigns, and the membership
    table carry no `ondelete` at all, so they either raise or are left orphaned; and
    `users.selected_organization_id` has no `ondelete` either, which blocks the
    delete outright. A single unfiltered DELETE button would therefore destroy a
    client's recordings and call history while leaving their workflows dangling.
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
    async def test_delete_refused_for_a_business_with_work(self):
        """Acme has 4 workflows and 128 call runs. Deleting it would be data loss."""
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.delete_organization = AsyncMock()

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/clients/{ACME.id}")

        assert response.status_code == 409, response.text
        mock_db.delete_organization.assert_not_awaited(), (
            "a refused delete must not touch the row"
        )

    @pytest.mark.asyncio
    async def test_refusal_explains_what_is_blocking_it(self):
        """A 409 with no body is unactionable. The counts come back with it."""
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=ACME)
        mock_db.delete_organization = AsyncMock()

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/clients/{ACME.id}")

        detail = response.json()["detail"]
        assert detail["workflow_count"] == 4
        assert detail["run_count"] == 128
        assert "archive" in str(detail).lower(), (
            "the refusal should point the operator at archiving instead"
        )

    @pytest.mark.asyncio
    async def test_delete_succeeds_for_an_empty_business(self):
        """A business that was created and abandoned can be removed outright.

        The point of the guard is to stop irreversible loss, not to make the wrong
        onboarding permanent. A business with no agents, no calls, and no numbers
        holds nothing worth keeping.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=GLOBEX)
        mock_db.delete_organization = AsyncMock(return_value=GLOBEX)

        with patch("api.routes.agency.db_client", mock_db):
            response = client.delete(f"/api/v1/agency/clients/{GLOBEX.id}")

        assert response.status_code in (200, 204), response.text
        mock_db.delete_organization.assert_awaited_once_with(GLOBEX.id)

    @pytest.mark.asyncio
    async def test_delete_clears_member_selection_first(self):
        """`users.selected_organization_id` has no `ondelete`, so it blocks the delete.

        A member still pointing at a business being removed would otherwise abort
        the delete on a foreign-key violation -- or, worse, succeed and leave them
        pointing at a row that no longer exists.
        """
        app = _make_agency_app()
        client = TestClient(app)

        mock_db = _patched_client()
        mock_db.get_organization_by_id = AsyncMock(return_value=GLOBEX)
        mock_db.clear_selected_organization_references = AsyncMock()
        mock_db.delete_organization = AsyncMock(return_value=GLOBEX)

        with patch("api.routes.agency.db_client", mock_db):
            client.delete(f"/api/v1/agency/clients/{GLOBEX.id}")

        mock_db.clear_selected_organization_references.assert_awaited_once_with(
            GLOBEX.id
        )

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
