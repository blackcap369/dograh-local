"""DB access for failed-run alerts and the agency run-health aggregate.

Failure definition: a run whose gathered_context carries an error or a
call_status of "error" (the shapes mark_workflow_run_failed and the pipeline
error paths write). The health aggregate counts runs in a window and joins
workflows for agent names and organization attribution.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func, select, text, update

from api.db.base_client import BaseDBClient
from api.db.models import (
    OrganizationModel,
    RunFailureAlertModel,
    WorkflowModel,
    WorkflowRunModel,
)

FAILURE_WINDOW_HOURS = 24

# The failure predicate, shared by both aggregate queries. mark_workflow_run_failed
# writes call_status="error" plus an "error" message into gathered_context; the
# mid-call pipeline error path writes "error" directly.
_FAILED_CONDITION = text(
    "(workflow_runs.gathered_context->>'call_status' = 'error' "
    "OR workflow_runs.gathered_context::jsonb ? 'error')"
)


class RunFailureAlertClient(BaseDBClient):
    async def upsert_run_failure_alert(
        self,
        organization_id: int,
        workflow_id: int,
        failed_run_id: int,
        error: str | None,
    ) -> RunFailureAlertModel:
        """Bump the open alert for this business+agent, or create it.

        The partial unique index on open rows makes this atomic: concurrent
        failures of the same agent bump the same row instead of stacking
        duplicates. `updated_at` is refreshed so the dashboard can show how
        fresh the problem is.
        """
        now = datetime.now(timezone.utc)
        async with self.async_session() as session:
            result = await session.execute(
                select(RunFailureAlertModel).where(
                    RunFailureAlertModel.organization_id == organization_id,
                    RunFailureAlertModel.workflow_id == workflow_id,
                    RunFailureAlertModel.resolved_at.is_(None),
                    RunFailureAlertModel.acknowledged_at.is_(None),
                )
            )
            alert = result.scalars().first()
            if alert is None:
                alert = RunFailureAlertModel(
                    organization_id=organization_id,
                    workflow_id=workflow_id,
                    first_failed_run_id=failed_run_id,
                    last_failed_run_id=failed_run_id,
                    failure_count=1,
                    last_error=error,
                    created_at=now,
                    updated_at=now,
                )
                session.add(alert)
            else:
                alert.failure_count = (alert.failure_count or 0) + 1
                alert.last_failed_run_id = failed_run_id
                alert.last_error = error or alert.last_error
                alert.updated_at = now
            await session.commit()
            await session.refresh(alert)
            return alert

    async def resolve_run_failure_alerts(
        self, organization_id: int, workflow_id: int
    ) -> int:
        """Auto-clear open alerts for this agent after a successful run.

        Returns how many rows were closed.
        """
        async with self.async_session() as session:
            result = await session.execute(
                update(RunFailureAlertModel)
                .where(
                    RunFailureAlertModel.organization_id == organization_id,
                    RunFailureAlertModel.workflow_id == workflow_id,
                    RunFailureAlertModel.resolved_at.is_(None),
                )
                .values(resolved_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return result.rowcount or 0

    async def list_active_failure_alerts(
        self, organization_ids: list[int]
    ) -> list[dict]:
        """Open, unacknowledged alerts with agent and business labels.

        The Creative dashboard's alert list. An empty id list means an empty
        result, not every organization.
        """
        if not organization_ids:
            return []
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    RunFailureAlertModel,
                    WorkflowModel.name.label("agent_name"),
                    OrganizationModel.name.label("business_label"),
                )
                .join(
                    WorkflowModel,
                    WorkflowModel.id == RunFailureAlertModel.workflow_id,
                )
                .join(
                    OrganizationModel,
                    OrganizationModel.id == RunFailureAlertModel.organization_id,
                )
                .where(
                    RunFailureAlertModel.organization_id.in_(organization_ids),
                    RunFailureAlertModel.resolved_at.is_(None),
                    RunFailureAlertModel.acknowledged_at.is_(None),
                )
                .order_by(RunFailureAlertModel.updated_at.desc())
            )
            rows = result.all()
            return [
                {
                    "id": alert.id,
                    "organization_id": alert.organization_id,
                    "business_label": business_label,
                    "workflow_id": alert.workflow_id,
                    "agent_name": agent_name,
                    "failure_count": alert.failure_count,
                    "last_error": alert.last_error,
                    "last_failed_run_id": alert.last_failed_run_id,
                    "updated_at": alert.updated_at,
                }
                for alert, agent_name, business_label in rows
            ]

    async def get_run_failure_alert_by_id(self, alert_id: int) -> Optional[RunFailureAlertModel]:
        """Load an alert row by id (any organization -- the route authorizes
        against the row's organization via ensure_business_access before
        acting)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(RunFailureAlertModel).where(RunFailureAlertModel.id == alert_id)
            )
            return result.scalars().first()

    async def acknowledge_failure_alert(
        self, alert_id: int, organization_id: int, acknowledged_by: int
    ) -> bool:
        """Acknowledge one alert within the caller's organization.

        Returns False when the id does not exist there (the route turns that
        into a 404).
        """
        async with self.async_session() as session:
            result = await session.execute(
                update(RunFailureAlertModel)
                .where(
                    RunFailureAlertModel.id == alert_id,
                    RunFailureAlertModel.organization_id == organization_id,
                    RunFailureAlertModel.resolved_at.is_(None),
                )
                .values(
                    acknowledged_at=datetime.now(timezone.utc),
                    acknowledged_by=acknowledged_by,
                )
            )
            await session.commit()
            return (result.rowcount or 0) > 0

    async def get_run_failure_health(
        self, organization_ids: list[int], window_hours: int = FAILURE_WINDOW_HOURS
    ) -> dict[int, dict]:
        """Per-organization run health inside the window: total runs, failed
        runs, and the most recent failure's detail.

        One grouped query for the counts and one DISTINCT ON for the latest
        failure per organization. Absent organizations zero-fill at the
        caller.
        """
        if not organization_ids:
            return {}
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

        async with self.async_session() as session:
            totals = await session.execute(
                select(
                    WorkflowModel.organization_id,
                    func.count(WorkflowRunModel.id).label("runs"),
                    func.sum(case((_FAILED_CONDITION, 1), else_=0)).label("failed"),
                )
                .join(
                    WorkflowRunModel,
                    WorkflowRunModel.workflow_id == WorkflowModel.id,
                )
                .where(
                    WorkflowModel.organization_id.in_(organization_ids),
                    WorkflowRunModel.created_at >= since,
                )
                .group_by(WorkflowModel.organization_id)
            )
            health: dict[int, dict] = {
                org_id: {"runs_24h": int(runs), "failed_24h": int(failed or 0)}
                for org_id, runs, failed in totals.all()
            }

            latest = await session.execute(
                select(
                    WorkflowModel.organization_id,
                    WorkflowRunModel.id.label("run_id"),
                    WorkflowModel.name.label("agent_name"),
                    WorkflowRunModel.gathered_context,
                    WorkflowRunModel.created_at,
                )
                .join(
                    WorkflowRunModel,
                    WorkflowRunModel.workflow_id == WorkflowModel.id,
                )
                .where(
                    WorkflowModel.organization_id.in_(organization_ids),
                    WorkflowRunModel.created_at >= since,
                    _FAILED_CONDITION,
                )
                # PostgreSQL DISTINCT ON: one row per organization, the most
                # recent failed run first.
                .distinct(WorkflowModel.organization_id)
                .order_by(
                    WorkflowModel.organization_id,
                    WorkflowRunModel.created_at.desc(),
                )
            )
            for org_id, run_id, agent_name, gathered, created_at in latest.all():
                error = None
                if isinstance(gathered, dict):
                    error = gathered.get("error") or (
                        "call_status: " + gathered["call_status"]
                        if gathered.get("call_status")
                        else None
                    )
                health.setdefault(org_id, {"runs_24h": 0, "failed_24h": 0})[
                    "last_failure"
                ] = {
                    "run_id": run_id,
                    "agent_name": agent_name,
                    "error": error,
                    "at": created_at,
                }

            for org_id in organization_ids:
                health.setdefault(
                    org_id, {"runs_24h": 0, "failed_24h": 0, "last_failure": None}
                ).setdefault("last_failure", None)

            return health
