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

from app.auth.permissions import WorkspaceAction, allows
from app.db.models.documents import Document
from app.db.models.enums import DocumentStatus, IngestionStatus, MembershipRole
from app.db.models.operations import IngestionJob
from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.documents import DocumentRepository, DocumentVersionRepository
from app.db.repositories.ingestion import IngestionJobRepository
from app.documents.keys import document_prefix
from app.documents.purge import collect_purge
from app.ingestion.queue import JobMessage, JobQueue
from app.observability.context import current_traceparent


class DocumentNotFoundError(Exception):
    """No such document in this workspace (or it is another tenant's)."""


class DocumentArchivedError(Exception):
    """The document is archived; restore it before processing it again."""


class DocumentNotRetryableError(Exception):
    """Only a failed ingestion may be started again on request."""


class DocumentPermanentlyFailedError(Exception):
    """The failure was deterministic; the same bytes cannot succeed."""


class DocumentProcessingError(Exception):
    """A worker is mid-run on this document; deletion must wait for it."""


class DeleteRequiresArchiveError(Exception):
    """Permanent deletion is only offered for an already archived document."""


def may_retry(
    document: Document,
    *,
    permanent_failure: bool,
    role: MembershipRole,
) -> bool:
    """Whether *this* caller may ask for another ingestion run right now.

    The one predicate behind every `retryable` field the API reports, so a
    client is never offered a control the endpoint would refuse. It answers the
    same three questions `retry_ingestion` does — is the document in a state
    that can be retried, could another run over the same bytes plausibly
    succeed, and does this caller hold `UPLOAD_DOCUMENTS` — because a viewer
    told "retryable" would get a 403, and a deterministically failed document
    would get a 409.
    """
    return (
        document.archived_at is None
        and document.status is DocumentStatus.FAILED
        and not permanent_failure
        and allows(role, WorkspaceAction.UPLOAD_DOCUMENTS)
    )


async def _load(
    documents: DocumentRepository,
    document_id: uuid.UUID,
) -> Document:
    document = await documents.get(document_id)
    if document is None:
        raise DocumentNotFoundError
    return document


async def _load_locked(
    documents: DocumentRepository,
    document_id: uuid.UUID,
) -> Document:
    """Load a document holding its row lock for the rest of the transaction.

    Used by the transitions that branch on state and then act on that branch —
    retry and delete — so two concurrent callers cannot both read the
    pre-transition value and both proceed.
    """
    document = await documents.get_for_update(document_id)
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

    The document row is locked for the whole transition. The worker's claim is
    a compare-and-set on one job id, so it deduplicates duplicate *delivery* of
    a single job but not two distinct jobs; without the lock, two concurrent
    retries would each read `FAILED`, each insert a job, and two workers would
    then race over the same pages and chunks.

    A permanent failure is refused: those are deterministic — a stored-object
    hash mismatch, an unparseable file, a provenance violation — so another run
    over the same unchanged bytes would fail in exactly the same way.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load_locked(documents, document_id)
    if document.archived_at is not None:
        raise DocumentArchivedError
    if document.status is not DocumentStatus.FAILED:
        raise DocumentNotRetryableError

    jobs = IngestionJobRepository(session, workspace_id)
    latest = await jobs.get_latest_for_document(document.id)
    if latest is not None and latest.permanent_failure:
        raise DocumentPermanentlyFailedError

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
    # The enqueueing request's trace travels with the job, so the worker's
    # lines join the upload the user is still waiting on.
    await queue.enqueue(
        JobMessage(
            job_id=job.id,
            workspace_id=workspace_id,
            traceparent=current_traceparent(),
        )
    )
    return job


async def delete_document(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Permanently delete an archived document and schedule its bytes for purge.

    Requires the document to be archived first: that state has already removed
    it from evidence and is reversible, so nothing is destroyed on the strength
    of a single click. Deleting the row cascades to versions, pages, chunks,
    and embeddings; the audit event is written first and survives because audit
    rows reference resources by id rather than by foreign key.

    Refused while a worker is mid-run on the document: the cascade would take
    the claimed job row out from under it, leaving it writing stages to a row
    that no longer exists. The document row is locked for the whole check, so a
    worker cannot claim a queued job in the gap; the worker also tolerates a
    vanished row, which covers a row removed by any other means.

    No object-storage call happens here. Rows and objects cannot be deleted in
    one transaction, and either ordering strands something on failure — a
    document that still issues download links for bytes that are gone, or bytes
    that outlive their document. Instead the deletion commits a `StoragePurge`
    record with the rows, and the sweeper in `app.documents.purge` deletes the
    objects afterwards and retries until it succeeds. The instruction is
    durable, so a storage outage delays the purge rather than losing it.

    The record carries the document's key *prefix*, not only the keys the rows
    knew: a page image is written to storage before its `pages` row is
    committed, so a run that crashed mid-OCR leaves content the database never
    recorded. Purging the prefix removes those too — otherwise a "permanent"
    deletion could leave pictures of the document's pages readable forever.
    """
    documents = DocumentRepository(session, workspace_id)
    document = await _load_locked(documents, document_id)
    if document.archived_at is None:
        raise DeleteRequiresArchiveError
    if await IngestionJobRepository(session, workspace_id).has_running_for_document(document.id):
        raise DocumentProcessingError

    version_repository = DocumentVersionRepository(session)
    versions = await version_repository.list_for_document(document.id)
    known_keys = [version.storage_key for version in versions]
    known_keys.extend(await version_repository.list_page_image_keys(document.id))
    prefix = document_prefix(workspace_id, document.id)
    session.add(
        collect_purge(
            workspace_id=workspace_id,
            document_id=document.id,
            keys=known_keys,
            key_prefix=prefix,
        )
    )
    await AuditLogRepository(session).record(
        action="document.deleted",
        resource_type="document",
        resource_id=document.id,
        workspace_id=workspace_id,
        actor_user_id=actor_id,
        detail={
            "sha256": document.sha256,
            "size_bytes": document.size_bytes,
            "version_count": len(versions),
            "recorded_object_count": len(known_keys),
            "purge_prefix": prefix,
        },
    )
    await documents.delete(document)


__all__ = [
    "DeleteRequiresArchiveError",
    "DocumentArchivedError",
    "DocumentNotFoundError",
    "DocumentNotRetryableError",
    "DocumentPermanentlyFailedError",
    "DocumentProcessingError",
    "archive_document",
    "delete_document",
    "may_retry",
    "restore_document",
    "retry_ingestion",
]
