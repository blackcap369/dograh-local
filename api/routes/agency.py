"""Creative Mode: the agency operator's cross-organization surface.

This router is NOT organization-scoped. Every other route in this service derives
`organization_id` from the authenticated user's selected organization and authorizes
against it. The routes here do the opposite: they read across organizations on
the instance, because the person using them is the agency operator managing clients,
not a user working inside one client.

That inversion is why the router exists as a separate surface rather than as more
routes on the organization router. An org-scoped rename would authorize on the
operator's *selected* organization, which is arbitrary here -- the business being
renamed is usually not the one they are standing in.

Authorization is two-layered (see api/services/agency_access.py):

- `require_agency_owner` gates the owner-only writes (creating a client, and
  later the access-management settings). Only `users.agency_role == 'owner'`
  passes -- the role is claimed via OWNER_EMAILS and promoted one-way at auth
  time.
- `ensure_business_access` gates every route aimed at one business. An owner
  passes by identity; a staff member passes only with a row in
  `staff_client_assignments`. The Clients *list* is scoped the same way at the
  query: a staff member's unassigned businesses never leave the database.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.constants import AUTH_PROVIDER
from api.db import db_client
from api.db.models import UserModel
from api.schemas.organization import OrganizationCreateRequest, OrganizationListItem
from api.services.agency_access import ensure_business_access, is_agency_owner
from api.services.auth.depends import get_user, require_agency_owner

router = APIRouter(
    prefix="/agency",
    tags=["agency"],
    responses={404: {"description": "Not found"}},
)

# Resource counts that make a business unsafe to delete outright. Anything with
# history is refused and must be archived instead -- see `_stats_for`.
_DELETE_SAFE_THRESHOLDS = ("workflow_count", "run_count", "phone_number_count")


# =============================================================================
# Schemas
# =============================================================================


class AgencyClientSummary(BaseModel):
    """One business, as the Clients page renders it.

    `label` is `name or provider_id`. `organizations.name` is nullable by design --
    it post-dates the backfill and Stack-created orgs never set it -- so the
    fallback is the contract here rather than a defensive nicety.
    """

    id: int
    provider_id: str
    name: Optional[str] = None
    label: str
    archived: bool = False
    workflow_count: int = 0
    run_count: int = 0
    phone_number_count: int = 0
    member_count: int = 0


class AgencyClientDeleteImpact(BaseModel):
    """What deleting a business would destroy, and whether it is allowed.

    Returned ahead of any delete so the UI can show a breakdown rather than a
    confirm dialog that either works or 409s with nothing to explain it.
    """

    id: int
    workflow_count: int
    run_count: int
    phone_number_count: int
    member_count: int
    deletable: bool
    blocking_reason: Optional[str] = None


class AgencyClientRenameRequest(BaseModel):
    """Body for renaming a business.

    Name only. `provider_id` is the sole key organizations are looked up by, so
    accepting one here would be a cross-tenant collision and impersonation
    primitive -- and a rename that touched it would break the org stamped on every
    workflow and call record that references this business.
    """

    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


# =============================================================================
# Reads
# =============================================================================


@router.get("/clients", response_model=list[AgencyClientSummary])
async def list_agency_clients(
    user: UserModel = Depends(get_user),
):
    """Every business this account may see, with its resource counts.

    Owners see the whole instance -- the one deliberately cross-organization
    query in this fork. Staff see only their assignments, and the scoping
    happens in the query (`list_organizations_for_staff`), not in Python: an
    unassigned business's name must never leave the database for a staff
    caller, exactly as the archived filter is applied at the query for
    everyone.

    The archived filter is applied twice on purpose, at the query
    (`list_all_organizations`) and again here. The query filter is the one that
    matters -- it stops the name ever leaving the database -- and it is pinned
    separately by `test_mine_asks_the_client_for_unarchived_rows_only`. This
    second pass is the cheap belt to that pair of braces: an archived business
    reaching this list would be offered to the operator as somewhere to work,
    and a retired client's name showing up in a list of live clients is the kind
    of bug nobody reports until it is expensive. It also keeps this route correct
    if `list_all_organizations` is ever called with `include_archived=True`.
    """
    if is_agency_owner(user):
        organizations = [
            org
            for org in await db_client.list_all_organizations()
            if not getattr(org, "archived", False)
        ]
    else:
        organizations = [
            org
            for org in await db_client.list_organizations_for_staff(user.id)
            if not getattr(org, "archived", False)
        ]
    counts = await db_client.get_organization_resource_counts(
        [org.id for org in organizations]
    )

    # The `name or provider_id` contract lives in `_summary_for`, shared with
    # the single-client read so the two surfaces cannot drift.
    return [_summary_for(org, counts.get(org.id)) for org in organizations]


@router.get(
    "/clients/{organization_id}/delete-impact",
    response_model=AgencyClientDeleteImpact,
)
async def get_agency_client_delete_impact(
    organization_id: int,
    user: UserModel = Depends(get_user),
):
    """Report what a delete would destroy, before anything is destroyed.

    The foreign keys to `organizations.id` are inconsistent. API keys, model
    configurations, telephony configurations, phone numbers, and call records
    CASCADE, so they are destroyed silently. Workflows, folders, campaigns, and the
    membership table carry no `ondelete` at all, so they either raise or are left
    orphaned. `users.selected_organization_id` also has no `ondelete`, which blocks
    the delete outright. An unfiltered DELETE button would therefore destroy a
    client's recordings and call history while leaving their workflows dangling --
    so this endpoint exists to make the cost visible first.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    stats = await _stats_for(organization_id)

    blocking = [k for k in _DELETE_SAFE_THRESHOLDS if stats[k] > 0]
    return AgencyClientDeleteImpact(
        id=organization.id,
        **stats,
        deletable=not blocking,
        blocking_reason=(
            None
            if not blocking
            else "This business has work history. Archive it instead of deleting it."
        ),
    )


# =============================================================================
# Writes
# =============================================================================


@router.get("/clients/{organization_id}", response_model=AgencyClientSummary)
async def get_agency_client(
    organization_id: int,
    user: UserModel = Depends(get_user),
):
    """One business by id, archived included.

    The list route filters archived businesses because it *offers* places to
    work; this detail route deliberately does not filter, because the operator
    who archived a business must still be able to open it and restore it --
    without an archived-readable read, unarchive would be reachable only
    through raw API calls.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    stats = await _stats_for(organization.id)
    return _summary_for(organization, stats)


@router.post("/clients", response_model=OrganizationListItem, status_code=201)
async def create_agency_client(
    request: OrganizationCreateRequest,
    user: UserModel = Depends(require_agency_owner),
):
    """Add a new client business.

    Same contract as `POST /organizations` -- `provider_id` minted server-side,
    creator added as a member, no auto-switch -- reached through the agency surface
    because onboarding a client is an operator's job, not a per-organization one.

    No auto-switch is deliberate: creating client #3 while working in #1 must not
    re-point every org-scoped query the page makes next, or an agent created moments
    later would land in the wrong business.
    """
    from uuid import uuid4

    organization = await db_client.create_organization(
        name=request.name,
        provider_id=f"org_local_{user.id}_{uuid4().hex[:8]}",
    )
    await db_client.add_user_to_organization(user.id, organization.id)
    return OrganizationListItem(
        id=organization.id,
        provider_id=organization.provider_id,
        name=getattr(organization, "name", None),
    )


@router.patch("/clients/{organization_id}", response_model=OrganizationListItem)
async def rename_agency_client(
    organization_id: int,
    request: AgencyClientRenameRequest,
    user: UserModel = Depends(get_user),
):
    """Rename a business's display label.

    `provider_id` is never read from the body and never written. It is the only key
    organizations are looked up by, and it is stamped onto every workflow, call
    record, and member selection that points at this business.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    renamed = await db_client.rename_organization(organization.id, name=request.name)
    return OrganizationListItem(
        id=renamed.id,
        provider_id=renamed.provider_id,
        name=getattr(renamed, "name", None),
    )


@router.post("/clients/{organization_id}/archive", status_code=204)
async def archive_agency_client(
    organization_id: int,
    user: UserModel = Depends(get_user),
):
    """Hide a business from the switcher and the Clients list, keeping all data.

    The safe default action, and reversible -- which is why it does not cascade. An
    archived business keeps every agent, run, and recording, and returns intact on
    unarchive.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    await db_client.set_organization_archived(organization.id, True)
    return None


@router.post("/clients/{organization_id}/unarchive", status_code=204)
async def unarchive_agency_client(
    organization_id: int,
    user: UserModel = Depends(get_user),
):
    """Return an archived business to the switcher."""
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    await db_client.set_organization_archived(organization.id, False)
    return None


@router.delete("/clients/{organization_id}", status_code=204)
async def delete_agency_client(
    organization_id: int,
    user: UserModel = Depends(get_user),
):
    """Delete a business outright. Refused if it holds any work history.

    Archive is what an operator should normally reach for. This exists so that a
    business created and immediately abandoned -- a duplicate onboarding, a typo --
    can still be removed, without giving a one-click button the power to destroy a
    client's call history.

    Returns 409 with the blocking counts so the refusal is actionable rather than a
    bare status code.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)
    stats = await _stats_for(organization.id)

    blocking = [k for k in _DELETE_SAFE_THRESHOLDS if stats[k] > 0]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This business has work history and cannot be deleted. "
                    "Archive it instead -- archiving hides it everywhere but keeps "
                    "every agent, call, and recording, and is reversible."
                ),
                **stats,
            },
        )

    # `users.selected_organization_id` has no `ondelete`, so a member still pointing
    # here would abort the delete on a foreign-key violation -- or leave them
    # pointing at a row that no longer exists. Clear it first.
    await db_client.clear_selected_organization_references(organization.id)
    # Same story for the membership table: `organization_users` carries no
    # `ondelete` either, so its rows must go explicitly or they survive as
    # orphans pointing at a business that no longer exists.
    await db_client.clear_organization_users(organization.id)
    await db_client.delete_organization(organization.id)
    return None


# =============================================================================
# Shared helpers
# =============================================================================


async def _require_organization(organization_id: int):
    """Load a business by id or 404.

    Agency routes are not scoped to a selected organization, so this is a plain
    lookup. Every one of them must call it first: acting on a row that was never
    confirmed to exist is how a 404 turns into a 500 deep in the delete path.
    """
    organization = await db_client.get_organization_by_id(organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Not found")
    return organization


def _summary_for(organization, counts: dict | None) -> AgencyClientSummary:
    """One business as the Clients surfaces render it.

    `label` is `name or provider_id` -- `organizations.name` is nullable by
    design (it post-dates the backfill and Stack-created orgs never set it), so
    the fallback is the contract here rather than a defensive nicety. A business
    with no rows has no group in the counts query, so absence means zero -- not
    a lookup failure. Getting that backwards would break the page the instant
    the operator creates their first client, which is the most likely moment
    anyone is watching.
    """
    return AgencyClientSummary(
        id=organization.id,
        provider_id=organization.provider_id,
        name=getattr(organization, "name", None),
        label=getattr(organization, "name", None) or organization.provider_id,
        archived=bool(getattr(organization, "archived", False)),
        **(
            counts
            or {
                "workflow_count": 0,
                "run_count": 0,
                "phone_number_count": 0,
                "member_count": 0,
            }
        ),
    )


async def _stats_for(organization_id: int) -> dict:
    """The four counts the delete guard reasons about, zero-filled."""
    counts = await db_client.get_organization_resource_counts([organization_id])
    return counts.get(organization_id) or {
        "workflow_count": 0,
        "run_count": 0,
        "phone_number_count": 0,
        "member_count": 0,
    }
