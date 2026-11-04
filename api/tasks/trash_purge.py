"""Nightly purge of trashed organizations past their retention window.

The trash is the recovery mechanism; this job is what makes the retention
window real. It deliberately destroys as little as possible:

- A business whose impact guard refuses a permanent delete (workflows, runs,
  or phone numbers present) is skipped entirely and stays trashed --
  restorable forever rather than destroyed on a timer. The guard is the same
  one the owner-facing purge route uses.
- An expired business that passes the guard gets the full hard-delete
  sequence: member selections cleared, membership rows cleared, row deleted
  (which cascades keys, configs, and call records -- the same set a direct
  owner purge would take).

Run daily by the ARQ worker; see WorkerSettings in api/tasks/arq.py.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from api.constants import TRASH_RETENTION
from api.db import db_client


async def purge_expired_trashed_organizations(ctx: dict) -> dict:
    """Hard-delete trashed businesses past TRASH_RETENTION that are purge-safe."""
    cutoff = datetime.now(timezone.utc) - TRASH_RETENTION
    expired = await db_client.list_expired_trashed_organizations(cutoff)
    if not expired:
        return {"purged": [], "skipped": []}

    purged: list[int] = []
    skipped: list[dict] = []
    for organization in expired:
        counts = await db_client.get_organization_resource_counts([organization.id])
        stats = counts.get(organization.id) or {
            "workflow_count": 0,
            "run_count": 0,
            "phone_number_count": 0,
            "member_count": 0,
        }
        blocking = [
            key
            for key in ("workflow_count", "run_count", "phone_number_count")
            if stats[key] > 0
        ]
        if blocking:
            # Stays trashed and restorable. Nothing about the business is
            # lost by waiting; destroying it would be.
            skipped.append({"organization_id": organization.id, **stats})
            continue

        await db_client.clear_selected_organization_references(organization.id)
        await db_client.clear_organization_users(organization.id)
        await db_client.delete_organization(organization.id)
        purged.append(organization.id)

    if purged:
        logger.info(f"Trash purge: permanently deleted businesses {purged}")
    if skipped:
        logger.info(
            f"Trash purge: kept {len(skipped)} expired businesses with work "
            f"history restorable: {skipped}"
        )
    return {"purged": purged, "skipped": skipped}
