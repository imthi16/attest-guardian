"""Workspace-scoped repository for ingestion jobs (the progress API's view).

The worker itself operates across workspaces as a trusted system component
and manages its own sessions; see `app.ingestion.worker`.
"""

import uuid

from sqlalchemy import func, select

from app.db.models.enums import IngestionStatus
from app.db.models.operations import IngestionJob
from app.db.repositories.base import WorkspaceScopedRepository

# "Latest run" ordering, shared so the status endpoint and the list endpoint can
# never disagree about which run decides a document's retryability. `created_at`
# is `now()`, which in PostgreSQL is transaction-start time, so two jobs inserted
# in one transaction tie on it; the id breaks the tie arbitrarily but
# consistently, which is what matters when two queries must pick the same row.
_LATEST_FIRST = (IngestionJob.created_at.desc(), IngestionJob.id.desc())


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

    async def permanently_failed_document_ids(self) -> set[uuid.UUID]:
        """Documents whose *most recent* run failed deterministically.

        One query rather than a lookup per row: the list endpoint reports
        retryability for every document it returns, and only the latest run
        decides it — an earlier permanent failure followed by a transient one
        must not make the document look doomed.
        """
        ranked = (
            select(
                IngestionJob.document_id.label("document_id"),
                IngestionJob.permanent_failure.label("permanent_failure"),
                func.row_number()
                .over(
                    partition_by=IngestionJob.document_id,
                    order_by=_LATEST_FIRST,
                )
                .label("recency"),
            )
            .where(IngestionJob.workspace_id == self.workspace_id)
            .subquery()
        )
        statement = select(ranked.c.document_id).where(
            ranked.c.recency == 1,
            ranked.c.permanent_failure.is_(True),
        )
        result = await self._session.scalars(statement)
        return set(result.all())

    async def get_latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        statement = (
            select(IngestionJob)
            .where(
                IngestionJob.workspace_id == self.workspace_id,
                IngestionJob.document_id == document_id,
            )
            .order_by(*_LATEST_FIRST)
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.first()
