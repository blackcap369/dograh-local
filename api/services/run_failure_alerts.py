"""Failed-run alert evaluation (V2.6).

Called from the completion task after every workflow run: a failed run bumps
(or creates) the open alert for its business+agent; a successful run
auto-clears any open alert. Best-effort by contract -- monitoring must never
break the completion pipeline it watches.
"""

from loguru import logger

from api.db import db_client


def _failure_detail(run) -> str | None:
    """The error text for a failed run, from the shapes the failure paths
    write (mark_workflow_run_failed and the mid-call error handler)."""
    gathered = getattr(run, "gathered_context", None)
    if not isinstance(gathered, dict):
        return None
    return gathered.get("error") or (
        "call_status: " + gathered["call_status"]
        if gathered.get("call_status")
        else None
    )


def _is_failed(run) -> bool:
    if not getattr(run, "is_completed", False):
        return False
    gathered = getattr(run, "gathered_context", None)
    if not isinstance(gathered, dict):
        return False
    return gathered.get("call_status") == "error" or "error" in gathered


async def evaluate_run_completion_for_alerts(workflow_run_id: int) -> None:
    """After a run completes: bump/clear its business's failure alert.

    Never raises -- callers wrap in try/except anyway, but the intent is that
    a monitoring bug must not fail the completion job.
    """
    try:
        run = await db_client.get_workflow_run_by_id(workflow_run_id)
        if run is None:
            return
        workflow = await db_client.get_workflow_by_id(run.workflow_id)
        if workflow is None or workflow.organization_id is None:
            return

        if _is_failed(run):
            await db_client.upsert_run_failure_alert(
                organization_id=workflow.organization_id,
                workflow_id=run.workflow_id,
                failed_run_id=run.id,
                error=_failure_detail(run),
            )
            logger.warning(
                f"Run {run.id} of agent {run.workflow_id} failed "
                f"(business {workflow.organization_id}): "
                f"{_failure_detail(run)}"
            )
        elif getattr(run, "is_completed", False):
            # Only a COMPLETED SUCCESSFUL run clears the alert. An in-flight
            # run (initialized/running) proves nothing either way -- clearing
            # on it would hide a dying agent mid-call.
            await db_client.resolve_run_failure_alerts(
                workflow.organization_id, run.workflow_id
            )
    except Exception as e:  # noqa: BLE001 - monitoring is best-effort
        logger.error(
            f"Failed to evaluate run-failure alert for run {workflow_run_id}: {e}"
        )
