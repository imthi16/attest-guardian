"""The storage contract the application codes against."""

from collections.abc import Sequence
from typing import Protocol


class ObjectStorage(Protocol):
    """Minimal private-object operations used by the document workflows."""

    async def put_object(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def delete_object(self, key: str) -> None: ...

    async def list_keys(self, prefix: str) -> Sequence[str]:
        """Every stored key under `prefix`.

        Permanent deletion uses this rather than trusting the database to know
        what was written: a page image reaches storage before its row is
        committed, so a crashed run can leave content whose only record is the
        key itself.
        """
        ...

    async def presigned_get_url(self, key: str, expires_in_seconds: int) -> str:
        """A time-limited download URL; the bucket itself is never public."""
        ...
