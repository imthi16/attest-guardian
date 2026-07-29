"""Post-upload document lifecycle: archive, restore, reprocess, delete.

Every operation here changes whether a document may be used as evidence, so
each one records an audit event and each one is decided from the document's
own state rather than from what the caller's UI believed. Archival is the
reversible withdrawal: the row and its provenance are untouched, but
`evidence_eligible` stops matching it, so retrieval, citation resolution, and
answers drop it immediately.

Permanent deletion is deliberately a second step behind archival. Bytes and
provenance cannot be recovered, so the caller must first put the document in
the reversible state that already removed it from evidence.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.documents import Document
from app.db.models.enums import DocumentStatus, IngestionStatus
from app.db.models.operations import IngestionJob
from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.documents import DocumentRepository, DocumentVersionRepository
from app.ingestion.queue import JobMessage, JobQueue
from app.storage.base import ObjectStorage


class DocumentNotFoundError(Exception):
    """No such document in this workspace (or it is another tenant's)."""


class DocumentArchivedError(Exception):
    """The document is archived; restore it before processing it again."""


class DocumentNotRetryableError(Exception):
    """Only a failed ingestion may be started again on request."""


class DeleteRequiresArchiveError(Exception):
    """Permanent deletion is only offered for an already archived document."""


async def _load(
    documents: DocumentRepository,
    document_id: uuid.UUID,
) -> Document:
    document = await documents.get(document_id)
    if document is None:
        raise DocumentNotFoundError
    return document


async def archive_document(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document:
    """Withdraw a document from evidence, keeping it restorable.

    Idempotent: archiving an archived document keeps the original timestamp,
    so a duplicate click cannot rewrite when the withdrawal happened.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load(documents, document_id)
    if document.archived_at is not None:
        return document

    document.archived_at = datetime.now(UTC)
    await AuditLogRepository(session).record(
        action="document.archived",
        resource_type="document",
        resource_id=document.id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        detail={"status": document.status.value},
    )
    return document


async def restore_document(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
) -> Document:
    """Return an archived document to evidence.

    Idempotent for the same reason as archival. No reprocessing is needed:
    archival never touched the chunks or their provenance.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load(documents, document_id)
    if document.archived_at is None:
        return document

    document.archived_at = None
    await AuditLogRepository(session).record(
        action="document.restored",
        resource_type="document",
        resource_id=document.id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        detail={"status": document.status.value},
    )
    return document


async def retry_ingestion(
    *,
    session: AsyncSession,
    queue: JobQueue,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
) -> IngestionJob:
    """Queue a fresh ingestion run for a failed document.

    Only `FAILED` documents qualify. A quarantined document is never
    reprocessed on request — the scanner's verdict is terminal, and retrying it
    would hand rejected content back to the pipeline. A pending, processing, or
    ready document has nothing to retry, and starting a second run would race
    the first over the same rows.

    The failed job row is left as it is and a new one is inserted, so the
    failure history survives and the worker's compare-and-set claim still sees
    a clean `QUEUED` row.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load(documents, document_id)
    if document.archived_at is not None:
        raise DocumentArchivedError
    if document.status is not DocumentStatus.FAILED:
        raise DocumentNotRetryableError

    document.status = DocumentStatus.PENDING
    job = IngestionJob(
        workspace_id=workspace_id,
        document_id=document.id,
        status=IngestionStatus.QUEUED,
    )
    session.add(job)
    await AuditLogRepository(session).record(
        action="document.ingestion_retried",
        resource_type="document",
        resource_id=document.id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        detail={},
    )
    await session.flush()
    # As with the initial upload, a worker may dequeue before this transaction
    # commits; it finds no row, drops the message, and `requeue_stale` picks
    # the job up later. Duplicate delivery stays safe because claiming is a
    # compare-and-set.
    await queue.enqueue(JobMessage(job_id=job.id, workspace_id=workspace_id))
    return job


async def delete_document(
    *,
    session: AsyncSession,
    storage: ObjectStorage,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Permanently delete an archived document, its rows, and its bytes.

    Requires the document to be archived first: that state has already removed
    it from evidence and is reversible, so nothing is destroyed on the strength
    of a single click. Deleting the row cascades to versions, pages, chunks,
    and embeddings; the audit event is written first and survives because audit
    rows reference resources by id rather than by foreign key.

    Rows are removed before the stored objects so a storage failure rolls the
    whole request back rather than leaving a downloadable document whose bytes
    are gone. Uploads currently create exactly one version, so the purge is a
    single object and cannot half-succeed; multi-version documents would need
    the purge moved behind a committed deletion marker.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load(documents, document_id)
    if document.archived_at is None:
        raise DeleteRequiresArchiveError

    versions = await DocumentVersionRepository(session).list_for_document(document.id)
    storage_keys = [version.storage_key for version in versions]
    await AuditLogRepository(session).record(
        action="document.deleted",
        resource_type="document",
        resource_id=document.id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        detail={
            "sha256": document.sha256,
            "size_bytes": document.size_bytes,
            "version_count": len(storage_keys),
        },
    )
    await documents.delete(document)
    for key in storage_keys:
        await storage.delete_object(key)


__all__ = [
    "DeleteRequiresArchiveError",
    "DocumentArchivedError",
    "DocumentNotFoundError",
    "DocumentNotRetryableError",
    "archive_document",
    "delete_document",
    "restore_document",
    "retry_ingestion",
]
