"""Credit billing service: per-run deduction and the zero-balance gate.

1 credit = 1 minute of successful run time, rounded up (a 10-second
successful call still costs 1 minute -- the line connected). Failed runs
never deduct. The zero-balance block happens at run creation, so a business
out of credits cannot start new calls while any in-flight run finishes
(its completion deduction may take the balance to exactly zero or a little
below).
"""

import math

from fastapi import HTTPException
from loguru import logger

from api.db import db_client


async def apply_run_credit_deduction(workflow_run_id: int) -> None:
    """Deduct credits for a completed successful run. Best-effort by
    contract: billing must never fail the completion pipeline."""
    try:
        run = await db_client.get_workflow_run_by_id(workflow_run_id)
        if run is None or not getattr(run, "is_completed", False):
            return
        gathered = getattr(run, "gathered_context", None)
        if isinstance(gathered, dict) and (
            gathered.get("call_status") == "error" or "error" in gathered
        ):
            return  # failed runs never deduct

        workflow = await db_client.get_workflow_by_id(run.workflow_id)
        if workflow is None or workflow.organization_id is None:
            return

        usage = getattr(run, "usage_info", None)
        seconds = 0
        if isinstance(usage, dict):
            seconds = int(usage.get("call_duration_seconds") or 0)
        minutes = max(1, math.ceil(seconds / 60))

        await db_client.deduct_for_run(
            organization_id=workflow.organization_id,
            minutes=minutes,
            run_id=run.id,
        )
        logger.info(
            f"Credits: deducted {minutes} min for run {run.id} "
            f"(business {workflow.organization_id})"
        )
    except Exception as e:  # noqa: BLE001 - billing is best-effort
        logger.error(
            f"Failed to deduct credits for run {workflow_run_id}: {e}"
        )


async def ensure_organization_has_credits(organization_id: int) -> None:
    """The zero-balance gate at run creation. Raises 402 when the business
    is out of credits -- the telephony provider or API caller receives the
    rejection, the same way quota failures propagate."""
    has = await db_client.has_credits(organization_id)
    if not has:
        raise HTTPException(
            status_code=402,
            detail="This business is out of credits. Top up to continue.",
        )
