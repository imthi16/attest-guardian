"""Workspace-scoped repository for ingestion jobs (the progress API's view).

The worker itself operates across workspaces as a trusted system component
and manages its own sessions; see `app.ingestion.worker`.
"""

import uuid

from sqlalchemy import select

from app.db.models.enums import IngestionStatus
from app.db.models.operations import IngestionJob
from app.db.repositories.base import WorkspaceScopedRepository


class IngestionJobRepository(WorkspaceScopedRepository[IngestionJob]):
    model = IngestionJob

    async def has_running_for_document(self, document_id: uuid.UUID) -> bool:
        """Whether a worker has claimed a job for this document and is mid-run.

        Permanent deletion consults this: cascading a claimed job row out from
        under a running worker leaves it writing stages to a row that no longer
        exists. A merely `QUEUED` job is deliberately not blocking — the
        worker's claim already drops a message whose row has gone, so deleting
        one is safe, and refusing would make a document undeletable whenever
        its queue is backed up.
        """
        statement = (
            select(IngestionJob.id)
            .where(
                IngestionJob.workspace_id == self.workspace_id,
                IngestionJob.document_id == document_id,
                IngestionJob.status == IngestionStatus.RUNNING,
            )
            .limit(1)
        )
        return await self._session.scalar(statement) is not None

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
