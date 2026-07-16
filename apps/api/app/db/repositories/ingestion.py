"""Workspace-scoped repository for ingestion jobs (the progress API's view).

The worker itself operates across workspaces as a trusted system component
and manages its own sessions; see `app.ingestion.worker`.
"""

import uuid

from sqlalchemy import select

from app.db.models.operations import IngestionJob
from app.db.repositories.base import WorkspaceScopedRepository


class IngestionJobRepository(WorkspaceScopedRepository[IngestionJob]):
    model = IngestionJob

    async def get_latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        statement = (
            select(IngestionJob)
            .where(
                IngestionJob.workspace_id == self.workspace_id,
                IngestionJob.document_id == document_id,
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.first()
