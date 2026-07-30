"""The deferred half of permanent deletion: removing the stored bytes.

Deleting database rows and deleting object-storage keys cannot be one atomic
step, and whichever order a request picks, a failure between the two leaves the
system inconsistent — either a document that still issues download links for
bytes that are gone, or bytes that outlive the document that referenced them.

So the request does not attempt the storage half at all. It commits the row
deletion together with a `StoragePurge` record, and this sweeper performs the
deletions afterwards. That makes the cross-system step retryable: a storage
outage or a crashed process delays the purge and leaves a record saying exactly
what still has to go, instead of losing the instruction.

The purge is idempotent by construction — deleting an absent key is a no-op —
so re-running an interrupted record is always safe. It works from the
document's key *prefix* rather than the keys the deleted rows knew about,
because a page image reaches storage before its `pages` row is committed: a run
that crashed mid-OCR leaves content the database never recorded.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.operations import StoragePurge
from app.db.repositories.purges import StoragePurgeRepository
from app.db.session import session_scope
from app.storage.base import ObjectStorage

logger = logging.getLogger("app.documents.purge")


async def purge_one(
    *,
    session: AsyncSession,
    storage: ObjectStorage,
    purge: StoragePurge,
) -> bool:
    """Delete one record's objects and mark it complete; False if it must retry.

    Recorded keys are deleted even when listing fails, so a storage endpoint
    that refuses `list_objects_v2` still gets the uploaded bytes removed — but
    the record stays pending, because only a successful listing proves nothing
    unrecorded was left behind.
    """
    purge.attempts += 1
    keys: set[str] = set(purge.keys)
    listing_failed: Exception | None = None
    try:
        keys.update(await storage.list_keys(purge.key_prefix))
    except Exception as error:  # noqa: BLE001 - a listing failure must not lose the record
        listing_failed = error

    try:
        for key in sorted(keys):
            await storage.delete_object(key)
    except Exception as error:  # noqa: BLE001 - the record survives to be retried
        purge.last_error = f"{type(error).__name__}: {error}"
        logger.warning(
            "storage purge failed; will retry",
            extra={"purge_id": str(purge.id), "attempts": purge.attempts},
        )
        return False

    if listing_failed is not None:
        purge.last_error = f"{type(listing_failed).__name__}: {listing_failed}"
        logger.warning(
            "storage purge could not list the document prefix; will retry",
            extra={"purge_id": str(purge.id), "attempts": purge.attempts},
        )
        return False

    purge.last_error = None
    purge.completed_at = datetime.now(UTC)
    logger.info(
        "storage purge complete",
        extra={
            "purge_id": str(purge.id),
            "document_id": str(purge.document_id),
            "object_count": len(keys),
        },
    )
    return True


async def run_pending_purges(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    limit: int = 20,
) -> int:
    """Complete as many pending purges as possible; returns how many finished.

    Each record gets its own transaction so one unreachable key cannot roll back
    the records that did succeed. Records are claimed `FOR UPDATE SKIP LOCKED`,
    so two sweepers never delete the same prefix at once.

    This scans across workspaces, like `requeue_stale`, so the deployed worker's
    database role needs BYPASSRLS.
    """
    completed = 0
    for _ in range(limit):
        async with session_scope(session_factory) as session:
            purge = await StoragePurgeRepository(session).claim_pending()
            if purge is None:
                return completed
            if await purge_one(session=session, storage=storage, purge=purge):
                completed += 1
    return completed


def collect_purge(
    *,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    keys: Sequence[str],
    key_prefix: str,
) -> StoragePurge:
    """Build the record a permanent deletion commits alongside its row deletion."""
    return StoragePurge(
        workspace_id=workspace_id,
        document_id=document_id,
        key_prefix=key_prefix,
        keys=list(keys),
    )


__all__ = ["collect_purge", "purge_one", "run_pending_purges"]
