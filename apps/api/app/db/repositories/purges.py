"""Access to the durable purge records permanent deletion leaves behind.

Unlike the tenant repositories, this one is not workspace-scoped: a purge
record describes storage keys for a document that no longer exists, and the
sweeper that acts on it runs as a system component across every workspace (the
same reason `requeue_stale` does). Nothing here is reachable from an API route,
so no request ever reads another tenant's record through it.
"""

from sqlalchemy import select

from app.db.models.operations import StoragePurge
from app.db.repositories.base import Repository


class StoragePurgeRepository(Repository[StoragePurge]):
    model = StoragePurge

    async def claim_pending(self) -> StoragePurge | None:
        """Lock the oldest unfinished purge, skipping ones another sweeper holds.

        `SKIP LOCKED` is what makes concurrent sweepers safe: two processes take
        different records rather than both deleting the same prefix and both
        reporting it done.
        """
        statement = (
            select(StoragePurge)
            .where(StoragePurge.completed_at.is_(None))
            .order_by(StoragePurge.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.scalars(statement)
        return result.first()
