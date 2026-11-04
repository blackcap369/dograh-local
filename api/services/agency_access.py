"""Agency access: the owner role and the staff-assignment authorization.

Two distinct questions are answered here, and keeping them apart is the point:

- "What is this account?" -- `users.agency_role`. The owner (from
  OWNER_EMAILS, promoted one-way at auth time) sees and can enter every
  business on the instance. A staff account sees only what it is assigned.
- "May this account touch THIS business from the agency surface?" --
  `require_owner` / `ensure_business_access`. Owners pass by identity; staff
  pass only with a row in `staff_client_assignments`.

Neither question is answered by `organization_users` membership: membership
means "can stand inside this business once selected", not "may manage it from
the cross-organization agency surface".
"""

from fastapi import HTTPException

from api.constants import AUTH_PROVIDER, OWNER_EMAILS
from api.db.models import UserModel

OWNER_ROLE = "owner"
STAFF_ROLE = "staff"


def resolve_agency_role(email: str | None) -> str:
    """The role a user with this email holds at creation time."""
    if email and email.strip().lower() in OWNER_EMAILS:
        return OWNER_ROLE
    return STAFF_ROLE


def is_agency_owner(user: UserModel) -> bool:
    """Whether this account holds the owner role.

    getattr, not attribute access: test doubles build users as
    SimpleNamespace, and an older user row predating the column must fail
    closed (staff) rather than raise.
    """
    return getattr(user, "agency_role", None) == OWNER_ROLE


async def promote_to_owner_if_listed(user: UserModel) -> None:
    """Upgrade the user's stored role when their email is in OWNER_EMAILS.

    Called from the auth paths (signup, and the per-request OSS auth that
    re-reads the user row), so an email added to OWNER_EMAILS is honored the
    next time that account authenticates -- no migration or manual step.

    One-way on purpose: role checks read the column, not the env, so removing
    an email from OWNER_EMAILS later cannot silently demote an existing owner.
    Demotion is a deliberate manual action.
    """
    if not user.email or user.email.strip().lower() not in OWNER_EMAILS:
        return
    if is_agency_owner(user):
        return

    from api.db import db_client

    await db_client.update_user_agency_role(user.id, OWNER_ROLE)
    user.agency_role = OWNER_ROLE


async def ensure_business_access(user: UserModel, organization_id: int) -> None:
    """Authorization for any agency route aimed at ONE business.

    Owners pass by identity. Staff pass only with an explicit assignment row
    -- re-derived from the database on every call, never from a list the
    client saw earlier, the same discipline the /switch endpoint applies to
    membership. A non-assigned staff member gets 403; a business that does
    not exist at all never reaches this check (callers 404 first via
    `_require_organization`).

    Plain coroutine, not a FastAPI dependency: routes call it after loading
    the business, so the 404-before-403 ordering stays in the route where it
    belongs.
    """
    if AUTH_PROVIDER != "local":
        raise HTTPException(status_code=404, detail="Not found")
    if is_agency_owner(user):
        return

    from api.db import db_client

    assigned = await db_client.is_user_assigned_to_organization(
        user.id, organization_id
    )
    if not assigned:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to that business",
        )
