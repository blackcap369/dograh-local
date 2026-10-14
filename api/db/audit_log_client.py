"""DB access for the agency audit log.

Append-only: the application never updates or deletes rows. The service
layer (api/services/audit.py) makes writes best-effort -- an audit failure
must never fail the action being audited.
"""

from typing import Optional

from sqlalchemy import select

from api.db.base_client import BaseDBClient
from api.db.models import AuditLogModel


class AuditLogClient(BaseDBClient):
    async def record_audit(
        self,
        action: str,
        actor_user_id: Optional[int],
        actor_email: Optional[str],
        organization_id: Optional[int],
        detail: dict,
    ) -> AuditLogModel:
        """Append one audit row."""
        async with self.async_session() as session:
            row = AuditLogModel(
                action=action,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                organization_id=organization_id,
                detail=detail,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_recent_audit_entries(
        self, limit: int = 50
    ) -> list[AuditLogModel]:
        """The most recent audit entries, newest first."""
        async with self.async_session() as session:
            result = await session.execute(
                select(AuditLogModel)
                .order_by(AuditLogModel.id.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
