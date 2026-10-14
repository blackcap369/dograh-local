"""Agency audit log (V2.1c): who did what, to which business, when.

Every destructive or management action on the Creative surface writes one
append-only row. Writes are best-effort by contract: an audit failure must
never fail the action being audited.
"""

from typing import Optional

from loguru import logger

from api.db import db_client
from api.db.models import UserModel


async def record_audit(
    action: str,
    actor: Optional[UserModel],
    organization_id: Optional[int] = None,
    **detail,
) -> None:
    """Append one audit entry. Never raises."""
    try:
        await db_client.record_audit(
            action=action,
            actor_user_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", None),
            organization_id=organization_id,
            detail=detail,
        )
    except Exception as e:  # noqa: BLE001 - auditing is best-effort
        logger.error(f"Audit write failed for action {action}: {e}")
