"""Append-only repository for audit events."""

import uuid
from typing import Any

from app.db.models.operations import AuditLog
from app.db.repositories.base import Repository


class AuditLogRepository(Repository[AuditLog]):
    model = AuditLog

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Append one audit event; audit rows are never updated or deleted."""
        entry = AuditLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            detail=detail or {},
        )
        return await self.add(entry)

    async def delete(self, instance: AuditLog) -> None:
        msg = "audit logs are append-only"
        raise NotImplementedError(msg)
