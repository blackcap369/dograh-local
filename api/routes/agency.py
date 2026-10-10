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

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from api.constants import AUTH_PROVIDER, OWNER_EMAILS, TRASH_RETENTION
from api.db import db_client
from api.db.models import DeletionRequestModel, UserModel
from api.schemas.organization import OrganizationCreateRequest, OrganizationListItem
from api.services.agency_access import (
    ensure_business_access,
    is_agency_owner,
    STAFF_ROLE,
)
from api.services.auth.depends import get_user, require_agency_owner
from api.utils.auth import hash_password

from api.constants import FAILURE_WINDOW_HOURS

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
    # True while a staff member's deletion request awaits the owner's decision
    # (V2.1d). The list renders a badge; the business is untouched until the
    # owner approves.
    deletion_pending: bool = False
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
    pending = await db_client.list_organization_ids_with_pending_deletion(
        [org.id for org in organizations]
    )

    # The `name or provider_id` contract lives in `_summary_for`, shared with
    # the single-client read so the two surfaces cannot drift.
    return [
        _summary_for(org, counts.get(org.id), deletion_pending=org.id in pending)
        for org in organizations
    ]


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
    pending = await db_client.list_organization_ids_with_pending_deletion(
        [organization.id]
    )
    return _summary_for(
        organization, stats, deletion_pending=organization.id in pending
    )


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
    user: UserModel = Depends(require_agency_owner),
):
    """Move a business to the trash. Owner-only, reversible by design.

    Staff deletes go through `POST .../deletion-request` and land in the
    owner's queue; this route is the owner's own action and the approval
    path's destination. Trashing is NOT impact-guarded, because it destroys
    nothing: every default lookup filters the business out (lists, switcher,
    membership), while the row and everything pointing at it stay intact for
    the restore window. Permanent destruction is a separate, guarded act
    (`POST /agency/trash/{id}/purge` and the nightly purge job), and a
    business with work history is never destroyed by the timer -- it simply
    stays restorable forever.

    `users.selected_organization_id` is cleared for anyone still standing in
    the business: leaving it would point them at a row the default lookups
    refuse to resolve. Membership rows are kept so restore brings back who
    belonged.
    """
    organization = await _require_organization(organization_id)
    await db_client.clear_selected_organization_references(organization.id)
    trashed = await db_client.mark_organization_deleted(organization.id)
    if trashed is None:
        # Raced with another delete of the same row; the caller's outcome
        # ("no longer an active business") already holds.
        raise HTTPException(status_code=404, detail="Not found")
    return None


# =============================================================================
# Deletion requests (staff asks; the owner decides)
# =============================================================================


class DeletionRequestSummary(BaseModel):
    """One deletion request, as the owner's queue renders it."""

    id: int
    organization_id: int
    business_label: str
    requested_by_email: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    status: str


class DeletionRequestCreateRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _request_summary(
    request, organization, requester, status: str | None = None
) -> DeletionRequestSummary:
    """Render a request. `status` overrides the row's own value for the approve
    path, where the decision is stamped on without mutating the loaded row."""
    return DeletionRequestSummary(
        id=request.id,
        organization_id=organization.id,
        business_label=getattr(organization, "name", None) or organization.provider_id,
        requested_by_email=getattr(requester, "email", None),
        reason=request.reason,
        created_at=getattr(request, "created_at", None),
        status=status or request.status,
    )


@router.post(
    "/clients/{organization_id}/deletion-request",
    response_model=DeletionRequestSummary,
    status_code=201,
)
async def create_deletion_request(
    organization_id: int,
    request: DeletionRequestCreateRequest,
    user: UserModel = Depends(get_user),
):
    """A staff member asks for a business to be deleted. Nothing is destroyed.

    The owner decides from the access page: approval runs the same
    impact-guarded delete a direct owner delete would, rejection clears the
    request. A business with one pending request cannot collect another -- the
    queue stays one open question per business.
    """
    organization = await _require_organization(organization_id)
    await ensure_business_access(user, organization_id)

    try:
        created = await db_client.create_deletion_request(
            organization.id, requested_by=user.id, reason=request.reason
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="A deletion request for this business is already pending",
        )
    return _request_summary(created, organization, user)


@router.get("/deletion-requests", response_model=list[DeletionRequestSummary])
async def list_deletion_requests(user: UserModel = Depends(require_agency_owner)):
    """The owner's queue: every pending request, oldest first."""
    requests = await db_client.list_pending_deletion_requests()
    summaries = []
    for request in requests:
        organization = await db_client.get_organization_by_id(request.organization_id)
        requester = (
            await db_client.get_user_by_id(request.requested_by)
            if request.requested_by
            else None
        )
        if organization is None:
            continue
        summaries.append(_request_summary(request, organization, requester))
    return summaries


async def _resolve_deletion_request(
    request_id: int,
    decision: str,
    user: UserModel,
) -> DeletionRequestSummary:
    """Shared tail of approve/reject: load, check status, record the decision."""
    request = await db_client.get_deletion_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    if request.status != DeletionRequestModel.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"This request was already {request.status}",
        )
    resolved = await db_client.resolve_deletion_request(
        request_id, decision, resolved_by=user.id
    )
    organization = await db_client.get_organization_by_id(resolved.organization_id)
    requester = (
        await db_client.get_user_by_id(resolved.requested_by)
        if resolved.requested_by
        else None
    )
    return _request_summary(resolved, organization, requester)


@router.post(
    "/deletion-requests/{request_id}/approve",
    response_model=DeletionRequestSummary,
)
async def approve_deletion_request(
    request_id: int,
    user: UserModel = Depends(require_agency_owner),
):
    """Approve a deletion request: the business is moved to the trash.

    Approval trashes rather than destroys -- the same reversible action a
    direct owner delete performs -- so there is no impact guard here anymore:
    the guard exists because destruction was irreversible, and trashing is
    not. Permanent removal is the purge (owner-initiated or the nightly job)
    and remains impact-guarded there.
    """
    request = await db_client.get_deletion_request(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Deletion request not found")
    if request.status != DeletionRequestModel.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"This request was already {request.status}",
        )

    organization = await _require_organization(request.organization_id)
    requester = (
        await db_client.get_user_by_id(request.requested_by)
        if request.requested_by
        else None
    )
    await db_client.clear_selected_organization_references(organization.id)
    await db_client.mark_organization_deleted(organization.id)
    # The trash is the outcome; resolve the request so the queue clears. The
    # request row survives (the business row does too), which is the audit
    # trail of the decision.
    return _request_summary(request, organization, requester, status="approved")


@router.post(
    "/deletion-requests/{request_id}/reject",
    response_model=DeletionRequestSummary,
)
async def reject_deletion_request(
    request_id: int,
    user: UserModel = Depends(require_agency_owner),
):
    """Reject a deletion request. The business is untouched."""
    return await _resolve_deletion_request(request_id, "rejected", user)


# =============================================================================
# The trash (owner only): what soft delete produced, and its two exits
# =============================================================================


class TrashedClientSummary(BaseModel):
    """One trashed business, as the owner's trash renders it."""

    id: int
    provider_id: str
    label: str
    archived: bool = False
    deleted_at: Optional[datetime] = None
    # When the nightly purge may hard-delete it. None means "never": the
    # business has work history, so the impact guard will refuse the purge
    # forever and it stays restorable until manually purged from a backup.
    purge_eligible_at: Optional[datetime] = None
    workflow_count: int = 0
    run_count: int = 0
    phone_number_count: int = 0
    member_count: int = 0


async def _require_trashed_organization(organization_id: int):
    """Load a business by id, requiring that it actually is trashed."""
    organization = await db_client.get_organization_by_id(
        organization_id, include_deleted=True
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Not found")
    if organization.deleted_at is None:
        raise HTTPException(status_code=404, detail="That business is not in the trash")
    return organization


def _trashed_summary(organization, counts: dict | None) -> TrashedClientSummary:
    has_history = any(
        (counts or {}).get(k, 0) > 0 for k in _DELETE_SAFE_THRESHOLDS
    )
    deleted_at = getattr(organization, "deleted_at", None)
    return TrashedClientSummary(
        id=organization.id,
        provider_id=organization.provider_id,
        label=getattr(organization, "name", None) or organization.provider_id,
        archived=bool(getattr(organization, "archived", False)),
        deleted_at=deleted_at,
        purge_eligible_at=(
            None
            if has_history or deleted_at is None
            else deleted_at + TRASH_RETENTION
        ),
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


@router.get("/trash", response_model=list[TrashedClientSummary])
async def list_trashed_clients(user: UserModel = Depends(require_agency_owner)):
    """The owner's trash: soft-deleted businesses, newest first.

    Counts are included so the purge decision is informed -- a business with
    runs shows `purge_eligible_at: null`, meaning the nightly purge will never
    take it and only a deliberate purge attempt (which will be refused) or a
    restore can change its state.
    """
    trashed = await db_client.list_deleted_organizations()
    counts = await db_client.get_organization_resource_counts(
        [org.id for org in trashed]
    )
    return [_trashed_summary(org, counts.get(org.id)) for org in trashed]


@router.post("/trash/{organization_id}/restore", status_code=204)
async def restore_trashed_client(
    organization_id: int,
    user: UserModel = Depends(require_agency_owner),
):
    """Bring a trashed business back, exactly as it was.

    Everything survived the trash -- agents, runs, recordings, memberships --
    so restore is a single column write. Members who were standing in the
    business when it was trashed must reselect it from the switcher; that is
    the only visible difference.
    """
    organization = await _require_trashed_organization(organization_id)
    restored = await db_client.restore_organization(organization.id)
    if restored is None:
        raise HTTPException(status_code=404, detail="Not found")
    return None


@router.post("/trash/{organization_id}/purge", status_code=204)
async def purge_trashed_client(
    organization_id: int,
    user: UserModel = Depends(require_agency_owner),
):
    """Destroy a trashed business permanently. Owner-only, impact-guarded.

    This is the one irreversible act in the agency surface, so the guard that
    used to sit on plain delete lives here: a business with work history is
    refused with the counts and stays restorable. The nightly purge job runs
    the same guard for expired businesses and leaves guarded ones alone.
    """
    organization = await _require_trashed_organization(organization_id)
    stats = await _stats_for(organization.id)
    blocking = [k for k in _DELETE_SAFE_THRESHOLDS if stats[k] > 0]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This business has work history and cannot be destroyed. "
                    "It stays in the trash and remains restorable -- restore it "
                    "instead."
                ),
                **stats,
            },
        )

    await db_client.clear_selected_organization_references(organization.id)
    await db_client.clear_organization_users(organization.id)
    await db_client.delete_organization(organization.id)
    return None


# =============================================================================
# Run health & failure alerts (V2.6) — the agency learns before the client
# =============================================================================


class RunHealthEntry(BaseModel):
    organization_id: int
    label: str
    runs_24h: int
    failed_24h: int
    last_failure: Optional[dict] = None


class FailureAlertEntry(BaseModel):
    """One open failure alert, as the health card renders it."""

    id: int
    organization_id: int
    business_label: str
    workflow_id: int
    agent_name: str
    failure_count: int
    last_error: Optional[str] = None
    last_failed_run_id: Optional[int] = None
    updated_at: Optional[datetime] = None


class RunHealthResponse(BaseModel):
    window_hours: int
    businesses: list[RunHealthEntry]
    alerts: list[FailureAlertEntry]


@router.get("/health", response_model=RunHealthResponse)
async def get_agency_run_health(user: UserModel = Depends(get_user)):
    """Per-business run health over the last 24h, plus open failure alerts.

    Role-scoped like the Clients list: owners see every business, staff see
    only their assignments (scoped in the query). The health card on the
    Creative dashboard is this endpoint's only consumer.
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

    org_ids = [org.id for org in organizations]
    health = await db_client.get_run_failure_health(
        org_ids, FAILURE_WINDOW_HOURS
    )
    alerts = await db_client.list_active_failure_alerts(org_ids)
    counts = await db_client.get_organization_resource_counts(org_ids)

    labels = {org.id: _summary_for(org, counts.get(org.id)).label for org in organizations}
    return RunHealthResponse(
        window_hours=FAILURE_WINDOW_HOURS,
        businesses=[
            RunHealthEntry(
                organization_id=org_id,
                label=labels.get(org_id, f"org {org_id}"),
                runs_24h=health.get(org_id, {}).get("runs_24h", 0),
                failed_24h=health.get(org_id, {}).get("failed_24h", 0),
                last_failure=health.get(org_id, {}).get("last_failure"),
            )
            for org_id in org_ids
        ],
        alerts=alerts,
    )


@router.post("/failure-alerts/{alert_id}/acknowledge", status_code=204)
async def acknowledge_failure_alert(
    alert_id: int,
    user: UserModel = Depends(get_user),
):
    """Acknowledge an open failure alert. The agent stays monitored: the next
    failure opens a fresh alert. Staff may acknowledge alerts for their
    assigned businesses; owners for any."""
    alert = await db_client.get_run_failure_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    await ensure_business_access(user, alert.organization_id)
    await db_client.acknowledge_failure_alert(
        alert_id, alert.organization_id, user.id
    )
    return None


# =============================================================================
# Staff management (owner only)
# =============================================================================


class AssignedClient(BaseModel):
    id: int
    label: str


class StaffAccountSummary(BaseModel):
    """One staff account, as the access-management page renders it."""

    id: int
    email: Optional[str] = None
    name: Optional[str] = None
    suspended: bool = False
    created_at: Optional[datetime] = None
    assigned_clients: list[AssignedClient] = []


class StaffCreateRequest(BaseModel):
    """Body for creating a staff account.

    The owner picks the password and hands it over out-of-band; there is no
    email dispatch in this fork. No organization is created and no bootstrap
    runs -- a staff account is an access grant, not a tenant.
    """

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value


class StaffAssignmentsRequest(BaseModel):
    """The staff member's full assignment set; the saved list replaces the old."""

    organization_ids: list[int]


class StaffPasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value


class StaffSuspendRequest(BaseModel):
    suspended: bool


def _staff_summary(user_row, assigned_orgs: list) -> StaffAccountSummary:
    return StaffAccountSummary(
        id=user_row.id,
        email=getattr(user_row, "email", None),
        name=getattr(user_row, "name", None),
        suspended=bool(getattr(user_row, "is_suspended", False)),
        created_at=getattr(user_row, "created_at", None),
        assigned_clients=[
            AssignedClient(
                id=org.id,
                label=getattr(org, "name", None) or org.provider_id,
            )
            for org in assigned_orgs
        ],
    )


async def _require_staff_account(staff_user_id: int) -> UserModel:
    """Load the target of a staff-management route, with the guards that are
    the same for every one of them."""
    target = await db_client.get_user_by_id(staff_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    if is_agency_owner(target):
        raise HTTPException(
            status_code=400,
            detail="That account is the agency owner and cannot be managed here",
        )
    return target


@router.get("/staff", response_model=list[StaffAccountSummary])
async def list_staff(user: UserModel = Depends(require_agency_owner)):
    """Every staff account with its assignments.

    One assignments query per staff member: the access page shows each
    account's businesses, and the account count is small by construction.
    If staff ever numbers in the hundreds, this is the query to batch --
    not before.
    """
    staff_users = await db_client.list_staff_users()
    summaries = []
    for account in staff_users:
        assigned = await db_client.list_organizations_for_staff(account.id)
        summaries.append(_staff_summary(account, assigned))
    return summaries


@router.post("/staff", response_model=StaffAccountSummary, status_code=201)
async def create_staff_account(
    request: StaffCreateRequest,
    user: UserModel = Depends(require_agency_owner),
):
    """Create a staff account. The owner hands the password to the hire.

    An email on OWNER_EMAILS is refused here even though the account would be
    created as staff: the one-way promotion at auth time would make it the
    owner on first login, which is not what a staff-creation form should ever
    do by surprise.
    """
    if request.email.strip().lower() in OWNER_EMAILS:
        raise HTTPException(
            status_code=400,
            detail="That email is reserved for the agency owner",
        )

    existing = await db_client.get_user_by_email(request.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    created = await db_client.create_user_with_email(
        email=request.email,
        password_hash=hash_password(request.password),
        name=request.name,
        agency_role=STAFF_ROLE,
    )
    return _staff_summary(created, [])


@router.patch("/staff/{staff_user_id}/suspended", response_model=StaffAccountSummary)
async def set_staff_suspended(
    staff_user_id: int,
    request: StaffSuspendRequest,
    user: UserModel = Depends(require_agency_owner),
):
    """Suspend or reactivate a staff account.

    Suspension is the offboarding primitive: it is checked on every auth path
    (login, token, API key), so access dies immediately even for an already-
    issued JWT -- which assignment revocation alone cannot do.
    """
    target = await _require_staff_account(staff_user_id)
    await db_client.set_user_suspended(staff_user_id, request.suspended)
    target.is_suspended = request.suspended
    assigned = await db_client.list_organizations_for_staff(staff_user_id)
    return _staff_summary(target, assigned)


@router.post("/staff/{staff_user_id}/reset-password", status_code=204)
async def reset_staff_password(
    staff_user_id: int,
    request: StaffPasswordResetRequest,
    user: UserModel = Depends(require_agency_owner),
):
    """Overwrite a staff password. The owner delivers the new one directly."""
    target = await _require_staff_account(staff_user_id)
    del target  # guards only; the write is by id
    await db_client.set_user_password(
        staff_user_id, hash_password(request.new_password)
    )
    return None


@router.put("/staff/{staff_user_id}/assignments", response_model=StaffAccountSummary)
async def replace_staff_assignments(
    staff_user_id: int,
    request: StaffAssignmentsRequest,
    user: UserModel = Depends(require_agency_owner),
):
    """Replace the staff member's client assignments with the submitted set.

    The saved list is the whole truth, not a delta -- a checkbox list that
    applied item-by-item could leave half of an edit in force after a failure.
    Unknown business ids are refused before anything is written.
    """
    target = await _require_staff_account(staff_user_id)

    unique_ids = list(dict.fromkeys(request.organization_ids))
    for organization_id in unique_ids:
        if await db_client.get_organization_by_id(organization_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Organization {organization_id} not found",
            )

    await db_client.set_staff_assignments(staff_user_id, unique_ids)
    assigned = await db_client.list_organizations_for_staff(staff_user_id)
    return _staff_summary(target, assigned)


@router.delete("/staff/{staff_user_id}", status_code=204)
async def delete_staff_account(
    staff_user_id: int,
    user: UserModel = Depends(require_agency_owner),
):
    """Delete a staff account outright -- refused if they built any agents.

    `workflows.user_id` carries no ondelete, so an account with agents cannot
    be deleted at the database level; the refusal is surfaced with a count and
    the suspend alternative rather than as a 500. Assignments cascade via FK.
    """
    target = await _require_staff_account(staff_user_id)
    del target
    workflow_count = await db_client.count_workflows_owned_by_user(staff_user_id)
    if workflow_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This account has built agents and cannot be deleted. "
                    "Suspend it instead -- that removes access immediately "
                    "while keeping its agent history."
                ),
                "workflow_count": workflow_count,
            },
        )
    await db_client.delete_user(staff_user_id)
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


def _summary_for(
    organization,
    counts: dict | None,
    deletion_pending: bool = False,
) -> AgencyClientSummary:
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
        deletion_pending=deletion_pending,
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
