"""The deferred purge that finishes a permanent deletion.

These cover the parts that need no database: the key layout the purge depends
on, and how one record behaves when storage misbehaves.
`tests/integration/test_documents_api.py` covers the committed path.
"""

import uuid
from collections.abc import Sequence

from app.db.models.operations import StoragePurge
from app.documents.keys import document_prefix, page_image_key, version_key
from app.documents.purge import collect_purge, purge_one

WORKSPACE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
SHA256 = "a" * 64


class FakeStorage:
    """An in-memory bucket that can be told to fail a particular operation."""

    def __init__(
        self,
        keys: dict[str, bytes] | None = None,
        *,
        fail_list: bool = False,
        fail_delete_of: str | None = None,
    ) -> None:
        self.objects = dict(keys or {})
        self.deleted: list[str] = []
        self._fail_list = fail_list
        self._fail_delete_of = fail_delete_of

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def get_object(self, key: str) -> bytes:
        return self.objects[key]

    async def delete_object(self, key: str) -> None:
        if key == self._fail_delete_of:
            msg = "storage is unreachable"
            raise RuntimeError(msg)
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def list_keys(self, prefix: str) -> Sequence[str]:
        if self._fail_list:
            msg = "listing is unavailable"
            raise RuntimeError(msg)
        return [key for key in self.objects if key.startswith(prefix)]

    async def presigned_get_url(self, key: str, expires_in_seconds: int) -> str:
        return f"https://storage.invalid/{key}?ttl={expires_in_seconds}"


def is_complete(purge: StoragePurge) -> bool:
    """Read the verdict through a call so a narrowed `None` cannot stick."""
    return purge.completed_at is not None


def make_purge(*, keys: list[str]) -> StoragePurge:
    return collect_purge(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        keys=keys,
        key_prefix=document_prefix(WORKSPACE_ID, DOCUMENT_ID),
    )


class TestKeyLayout:
    def test_every_document_object_sits_under_the_document_prefix(self) -> None:
        """The invariant the purge depends on.

        Permanent deletion sweeps one prefix rather than replaying rows, so a
        key built outside it would survive a "permanent" deletion. Anything that
        stores document content must build its key here.
        """
        prefix = document_prefix(WORKSPACE_ID, DOCUMENT_ID)
        keys = [
            version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256),
            version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=7, sha256=SHA256),
            page_image_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, page_number=1),
            page_image_key(WORKSPACE_ID, DOCUMENT_ID, version_number=2, page_number=311),
        ]
        for key in keys:
            assert key.startswith(prefix)
        # Distinct objects must not collide, or a purge or an upload would
        # silently destroy another version's content.
        assert len(set(keys)) == len(keys)

    def test_a_prefix_cannot_match_another_document(self) -> None:
        other = uuid.UUID("55555555-5555-4555-8555-555555555555")
        assert not document_prefix(WORKSPACE_ID, other).startswith(
            document_prefix(WORKSPACE_ID, DOCUMENT_ID)
        )

    def test_keys_carry_no_caller_supplied_text(self) -> None:
        # Keys are built from server-chosen identifiers only; an uploaded
        # filename never reaches object storage.
        key = version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256)
        assert key == f"{document_prefix(WORKSPACE_ID, DOCUMENT_ID)}v1-{SHA256[:16]}"


class TestPurgeOne:
    async def test_purges_recorded_and_unrecorded_objects(self) -> None:
        """A page image can reach storage before its row exists.

        `_stage_ocr` writes each PNG and persists the `pages` rows only after the
        loop, so a crashed run leaves images the database never recorded. The
        prefix listing is what finds them.
        """
        recorded = version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256)
        orphan = page_image_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, page_number=2)
        untouched = "workspaces/other/documents/keep-me"
        storage = FakeStorage(
            {recorded: b"pdf", orphan: b"png", untouched: b"someone else's document"}
        )
        purge = make_purge(keys=[recorded])

        assert await purge_one(storage=storage, purge=purge)

        assert sorted(storage.deleted) == sorted([recorded, orphan])
        assert untouched in storage.objects
        assert is_complete(purge)
        assert purge.attempts == 1
        assert purge.last_error is None

    async def test_a_delete_failure_keeps_the_record_pending(self) -> None:
        recorded = version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256)
        storage = FakeStorage({recorded: b"pdf"}, fail_delete_of=recorded)
        purge = make_purge(keys=[recorded])

        assert not await purge_one(storage=storage, purge=purge)

        assert not is_complete(purge)
        assert purge.attempts == 1
        first_error = purge.last_error
        assert first_error is not None and "unreachable" in first_error

        # The next pass finishes it: the record, not the request, carries the work.
        storage = FakeStorage({recorded: b"pdf"})
        assert await purge_one(storage=storage, purge=purge)
        assert is_complete(purge)
        assert purge.attempts == 2
        assert purge.last_error is None

    async def test_a_listing_failure_still_deletes_what_the_rows_knew(self) -> None:
        """Half the job is better than none, but it is not "done".

        Without a successful listing there is no proof that nothing unrecorded
        was left behind, so the record stays pending even though the uploaded
        bytes are already gone.
        """
        recorded = version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256)
        storage = FakeStorage({recorded: b"pdf"}, fail_list=True)
        purge = make_purge(keys=[recorded])

        assert not await purge_one(storage=storage, purge=purge)

        assert storage.deleted == [recorded]
        assert not is_complete(purge)
        assert purge.last_error is not None and "unavailable" in purge.last_error

    async def test_re_running_a_finished_purge_is_harmless(self) -> None:
        """Idempotence is what makes retrying safe at all."""
        recorded = version_key(WORKSPACE_ID, DOCUMENT_ID, version_number=1, sha256=SHA256)
        storage = FakeStorage({recorded: b"pdf"})
        purge = make_purge(keys=[recorded])

        assert await purge_one(storage=storage, purge=purge)
        assert await purge_one(storage=storage, purge=purge)
        assert purge.attempts == 2
