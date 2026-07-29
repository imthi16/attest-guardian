"""Secure-upload flows against real PostgreSQL and MinIO.

These tests exercise the whole workflow: validation, deduplication, object
storage, presigned downloads, authorization, and audit events. They require
`make infra-up` (or the CI containers) and use a dedicated test bucket.
"""

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.db.models.documents import Document, DocumentVersion, Page
from app.db.models.enums import DocumentStatus, IngestionStatus
from app.db.models.operations import AuditLog, IngestionJob
from app.storage.s3 import S3ObjectStorage
from botocore.exceptions import ClientError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.apptools import Account, build_client, make_account

TEST_BUCKET = "attest-test-documents"
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def storage_settings() -> Settings:
    prefix = f"test:api:{uuid.uuid4().hex}"
    return Settings(
        auth_rate_limit_attempts=1000,
        s3_bucket=TEST_BUCKET,
        ingestion_queue_key=f"{prefix}:queue",
        ingestion_dead_letter_key=f"{prefix}:dead",
    )


def make_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


@pytest.fixture(scope="session")
def object_storage() -> S3ObjectStorage:
    import asyncio

    storage = S3ObjectStorage(storage_settings())
    try:
        asyncio.run(storage.ensure_bucket())
    except Exception as error:  # noqa: BLE001 - fail fast with instructions
        pytest.fail(f"MinIO is required for storage tests; start it with `make infra-up` ({error})")
    return storage


@pytest.fixture
async def client(
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> AsyncIterator[httpx.AsyncClient]:
    async with build_client(db_session, storage_settings()) as instance:
        yield instance


async def make_workspace(client: httpx.AsyncClient, account: Account) -> str:
    response = await client.post(
        "/api/v1/workspaces",
        json={"name": "Uploads"},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["id"]
    return workspace_id


async def upload(
    client: httpx.AsyncClient,
    account: Account,
    workspace_id: str,
    *,
    filename: str = "report.pdf",
    content: bytes = PDF_BYTES,
    mime: str = "application/pdf",
) -> httpx.Response:
    return await client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": (filename, content, mime)},
        headers=account.headers,
    )


def error_code(response: httpx.Response) -> str:
    code: str = response.json()["detail"]["code"]
    return code


async def add_member(
    client: httpx.AsyncClient,
    owner: Account,
    workspace_id: str,
    invitee: Account,
    role: str,
) -> None:
    added = await client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": invitee.email, "role": role},
        headers=owner.headers,
    )
    assert added.status_code == 201, added.text


async def force_status(
    db_session: AsyncSession,
    document_id: str,
    status: DocumentStatus,
) -> None:
    """Put a document in a terminal ingestion state without running a worker."""
    document = await db_session.get(Document, uuid.UUID(document_id))
    assert document is not None
    document.status = status
    await db_session.flush()


async def test_upload_download_roundtrip_with_audit(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)

    uploaded = await upload(client, owner, workspace_id)
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    assert document["source_filename"] == "report.pdf"
    assert document["mime_type"] == "application/pdf"
    assert document["status"] == "pending"
    assert document["size_bytes"] == len(PDF_BYTES)

    link = await client.get(
        f"/api/v1/workspaces/{workspace_id}/documents/{document['id']}/download",
        headers=owner.headers,
    )
    assert link.status_code == 200, link.text
    async with httpx.AsyncClient() as raw_client:
        fetched = await raw_client.get(link.json()["url"])
    assert fetched.status_code == 200
    assert fetched.content == PDF_BYTES

    actions = (
        await db_session.scalars(
            select(AuditLog.action).where(AuditLog.resource_type == "document")
        )
    ).all()
    assert set(actions) == {"document.uploaded", "document.download_link_issued"}


async def test_docx_and_markdown_uploads_pass(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)

    docx = await upload(
        client,
        owner,
        workspace_id,
        filename="minutes.docx",
        content=make_docx_bytes(),
        mime=DOCX_MIME,
    )
    assert docx.status_code == 201, docx.text

    markdown = await upload(
        client,
        owner,
        workspace_id,
        filename="notes.md",
        content="# வணக்கம்".encode(),
        mime="text/plain",
    )
    assert markdown.status_code == 201, markdown.text


async def test_spoofed_uploads_are_rejected(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)

    cases: list[tuple[dict[str, Any], str]] = [
        ({"filename": "evil.pdf", "content": b"MZ\x90 executable"}, "content_mismatch"),
        ({"filename": "evil.exe", "content": b"anything"}, "unsupported_file_type"),
        ({"filename": "evil.pdf", "mime": "text/plain"}, "mime_mismatch"),
        ({"filename": "fake.docx", "content": b"not a zip", "mime": DOCX_MIME}, "content_mismatch"),
        (
            {"filename": "bad.txt", "content": b"\xff\xfe broken", "mime": "text/plain"},
            "content_mismatch",
        ),
        ({"filename": "empty.txt", "content": b"", "mime": "text/plain"}, "empty_file"),
    ]
    for overrides, expected_code in cases:
        response = await upload(client, owner, workspace_id, **overrides)
        assert response.status_code == 422, f"{overrides} -> {response.status_code}"
        assert error_code(response) == expected_code

    traversal = await upload(client, owner, workspace_id, filename="../../etc/cred.pdf")
    assert traversal.status_code == 201
    assert traversal.json()["source_filename"] == "cred.pdf"


async def test_oversized_uploads_are_rejected(db_session: AsyncSession) -> None:
    settings = Settings(
        auth_rate_limit_attempts=1000,
        s3_bucket=TEST_BUCKET,
        max_upload_bytes=64,
    )
    async with build_client(db_session, settings) as client:
        owner = await make_account(client, "owner@example.com")
        workspace_id = await make_workspace(client, owner)
        response = await upload(client, owner, workspace_id, content=b"%PDF-" + b"x" * 128)
        assert response.status_code == 413
        assert error_code(response) == "file_too_large"


async def test_duplicate_content_is_rejected_per_workspace(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    first = await upload(client, owner, workspace_id)
    assert first.status_code == 201

    duplicate = await upload(client, owner, workspace_id, filename="renamed.pdf")
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "duplicate_document"

    other_workspace = await make_workspace(client, owner)
    elsewhere = await upload(client, owner, other_workspace)
    assert elsewhere.status_code == 201


async def test_upload_authorization_matrix(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    viewer = await make_account(client, "viewer@example.com")
    outsider = await make_account(client, "outsider@example.com")
    workspace_id = await make_workspace(client, owner)
    added = await client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=owner.headers,
    )
    assert added.status_code == 201

    refused = await upload(client, viewer, workspace_id)
    assert refused.status_code == 403
    assert error_code(refused) == "insufficient_role"

    invisible = await upload(client, outsider, workspace_id)
    assert invisible.status_code == 404
    assert error_code(invisible) == "workspace_not_found"

    anonymous = await client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
    )
    assert anonymous.status_code == 401


async def test_documents_are_invisible_across_workspaces(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    other = await make_account(client, "other@example.com")
    workspace_id = await make_workspace(client, owner)
    other_workspace = await make_workspace(client, other)

    uploaded = await upload(client, owner, workspace_id)
    document_id = uploaded.json()["id"]

    # The other user asks for the same document id under their own workspace.
    cross = await client.get(
        f"/api/v1/workspaces/{other_workspace}/documents/{document_id}",
        headers=other.headers,
    )
    assert cross.status_code == 404
    assert error_code(cross) == "document_not_found"

    cross_download = await client.get(
        f"/api/v1/workspaces/{other_workspace}/documents/{document_id}/download",
        headers=other.headers,
    )
    assert cross_download.status_code == 404

    listing = await client.get(
        f"/api/v1/workspaces/{other_workspace}/documents",
        headers=other.headers,
    )
    assert listing.json() == []


async def test_upload_enqueues_ingestion_and_reports_progress(
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> None:
    from app.ingestion.queue import RedisJobQueue

    settings = storage_settings()
    async with build_client(db_session, settings) as client:
        owner = await make_account(client, "owner@example.com")
        workspace_id = await make_workspace(client, owner)
        uploaded = await upload(client, owner, workspace_id)
        document_id = uploaded.json()["id"]

        progress = await client.get(
            f"/api/v1/workspaces/{workspace_id}/documents/{document_id}/status",
            headers=owner.headers,
        )
        assert progress.status_code == 200, progress.text
        body = progress.json()
        assert body["status"] == "pending"
        assert body["job_status"] == "queued"
        assert body["stage"] == "uploaded"
        assert body["attempts"] == 0

        queue = RedisJobQueue(
            settings.redis_url,
            queue_key=settings.ingestion_queue_key,
            dead_letter_key=settings.ingestion_dead_letter_key,
        )
        try:
            message = await queue.dequeue(0)
            assert message is not None
            assert str(message.workspace_id) == workspace_id
        finally:
            await queue.aclose()

        missing = await client.get(
            f"/api/v1/workspaces/{workspace_id}/documents/{uuid.uuid4()}/status",
            headers=owner.headers,
        )
        assert missing.status_code == 404


async def test_archive_hides_a_document_and_restore_returns_it(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    archived = await client.post(f"{base}/{document_id}/archive", headers=owner.headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    # Archiving must not rewrite the ingestion outcome; provenance stays put.
    assert archived.json()["status"] == "pending"

    listing = await client.get(base, headers=owner.headers)
    assert listing.json() == []
    with_archived = await client.get(f"{base}?include_archived=true", headers=owner.headers)
    assert [entry["id"] for entry in with_archived.json()] == [document_id]

    # The detail and status routes still resolve, so the UI can explain the state.
    progress = await client.get(f"{base}/{document_id}/status", headers=owner.headers)
    assert progress.json()["archived"] is True
    assert progress.json()["retryable"] is False

    # Archiving twice keeps the first withdrawal timestamp.
    again = await client.post(f"{base}/{document_id}/archive", headers=owner.headers)
    assert again.json()["archived_at"] == archived.json()["archived_at"]

    restored = await client.post(f"{base}/{document_id}/restore", headers=owner.headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    reappeared = await client.get(base, headers=owner.headers)
    assert [entry["id"] for entry in reappeared.json()] == [document_id]

    actions = (
        await db_session.scalars(
            select(AuditLog.action).where(AuditLog.resource_type == "document")
        )
    ).all()
    assert "document.archived" in actions
    assert "document.restored" in actions


async def test_retry_only_reprocesses_a_failed_document(
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> None:
    from app.ingestion.queue import RedisJobQueue

    settings = storage_settings()
    async with build_client(db_session, settings) as client:
        owner = await make_account(client, "owner@example.com")
        workspace_id = await make_workspace(client, owner)
        document_id = (await upload(client, owner, workspace_id)).json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/documents"

        # A pending document has nothing to retry, and a second run would race
        # the first over the same rows.
        too_early = await client.post(f"{base}/{document_id}/retry", headers=owner.headers)
        assert too_early.status_code == 409
        assert error_code(too_early) == "document_not_retryable"

        # A scanner verdict is terminal: quarantined content is never handed
        # back to the pipeline on request.
        await force_status(db_session, document_id, DocumentStatus.QUARANTINED)
        quarantined = await client.post(f"{base}/{document_id}/retry", headers=owner.headers)
        assert quarantined.status_code == 409
        assert error_code(quarantined) == "document_not_retryable"

        await force_status(db_session, document_id, DocumentStatus.FAILED)
        # An archived document must be restored before it is processed again.
        await client.post(f"{base}/{document_id}/archive", headers=owner.headers)
        while_archived = await client.post(f"{base}/{document_id}/retry", headers=owner.headers)
        assert while_archived.status_code == 409
        assert error_code(while_archived) == "document_archived"
        await client.post(f"{base}/{document_id}/restore", headers=owner.headers)

        queue = RedisJobQueue(
            settings.redis_url,
            queue_key=settings.ingestion_queue_key,
            dead_letter_key=settings.ingestion_dead_letter_key,
        )
        try:
            assert await queue.dequeue(0) is not None  # the original upload
            retried = await client.post(f"{base}/{document_id}/retry", headers=owner.headers)
            assert retried.status_code == 200, retried.text
            body = retried.json()
            assert body["status"] == "pending"
            assert body["job_status"] == "queued"
            assert body["attempts"] == 0

            message = await queue.dequeue(0)
            assert message is not None
            assert str(message.workspace_id) == workspace_id
        finally:
            await queue.aclose()

        # The failed run is kept: a retry adds a job rather than rewriting history.
        job_count = await db_session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .where(IngestionJob.document_id == uuid.UUID(document_id))
        )
        assert job_count == 2

        missing = await client.post(f"{base}/{uuid.uuid4()}/retry", headers=owner.headers)
        assert missing.status_code == 404
        assert error_code(missing) == "document_not_found"


async def test_delete_requires_archive_and_purges_content(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    storage_key = await db_session.scalar(
        select(DocumentVersion.storage_key).where(
            DocumentVersion.document_id == uuid.UUID(document_id)
        )
    )
    assert storage_key is not None

    refused = await client.delete(f"{base}/{document_id}", headers=owner.headers)
    assert refused.status_code == 409
    assert error_code(refused) == "document_delete_requires_archive"
    assert await object_storage.get_object(storage_key) == PDF_BYTES

    await client.post(f"{base}/{document_id}/archive", headers=owner.headers)
    deleted = await client.delete(f"{base}/{document_id}", headers=owner.headers)
    assert deleted.status_code == 204, deleted.text

    gone = await client.get(f"{base}/{document_id}", headers=owner.headers)
    assert gone.status_code == 404
    assert await db_session.get(Document, uuid.UUID(document_id)) is None
    with pytest.raises(ClientError, match="NoSuchKey"):
        await object_storage.get_object(storage_key)

    # The audit trail outlives the document it describes.
    logged = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.action == "document.deleted",
                AuditLog.resource_id == uuid.UUID(document_id),
            )
        )
    ).all()
    assert len(logged) == 1
    assert logged[0].detail["version_count"] == 1


async def test_lifecycle_authorization_matrix(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    member = await make_account(client, "member@example.com")
    viewer = await make_account(client, "viewer@example.com")
    outsider = await make_account(client, "outsider@example.com")
    workspace_id = await make_workspace(client, owner)
    await add_member(client, owner, workspace_id, member, "member")
    await add_member(client, owner, workspace_id, viewer, "viewer")

    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    # Withdrawing or destroying evidence is owner/admin work, so a member who
    # may upload still cannot archive, restore, or delete.
    for path in (f"{base}/{document_id}/archive", f"{base}/{document_id}/restore"):
        refused = await client.post(path, headers=member.headers)
        assert refused.status_code == 403, path
        assert error_code(refused) == "insufficient_role"
    refused_delete = await client.delete(f"{base}/{document_id}", headers=member.headers)
    assert refused_delete.status_code == 403
    assert error_code(refused_delete) == "insufficient_role"

    # Retrying reprocesses bytes the workspace already accepted, so it follows
    # the upload capability: members may, viewers may not.
    refused_retry = await client.post(f"{base}/{document_id}/retry", headers=viewer.headers)
    assert refused_retry.status_code == 403
    assert error_code(refused_retry) == "insufficient_role"

    # A non-member learns nothing about the workspace, let alone the document.
    for method, path in (
        ("POST", f"{base}/{document_id}/archive"),
        ("POST", f"{base}/{document_id}/retry"),
        ("DELETE", f"{base}/{document_id}"),
    ):
        invisible = await client.request(method, path, headers=outsider.headers)
        assert invisible.status_code == 404, path
        assert error_code(invisible) == "workspace_not_found"

    anonymous = await client.post(f"{base}/{document_id}/archive")
    assert anonymous.status_code == 401


async def test_listing_and_detail_for_members(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    uploaded = await upload(client, owner, workspace_id)
    document_id = uploaded.json()["id"]

    listing = await client.get(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=owner.headers,
    )
    assert [entry["id"] for entry in listing.json()] == [document_id]

    detail = await client.get(
        f"/api/v1/workspaces/{workspace_id}/documents/{document_id}",
        headers=owner.headers,
    )
    assert detail.status_code == 200
    assert detail.json()["sha256"] == uploaded.json()["sha256"]


async def test_delete_purges_rendered_page_images(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> None:
    """Page images are document content and must not outlive a deletion.

    When `ingestion_store_page_images` is on, the worker renders a PNG per page
    and records its key on the `pages` row. Deleting the document cascades those
    rows away, so a purge that only collected version keys would leave pictures
    of the document's pages readable in the bucket forever.
    """
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    version = await db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(document_id))
    )
    assert version is not None

    image_key = f"{version.storage_key}.page-1.png"
    await object_storage.put_object(image_key, b"\x89PNG\r\n\x1a\n", "image/png")
    db_session.add(
        Page(
            document_version_id=version.id,
            page_number=1,
            text="rendered page",
            image_storage_key=image_key,
        )
    )
    await db_session.flush()

    await client.post(f"{base}/{document_id}/archive", headers=owner.headers)
    deleted = await client.delete(f"{base}/{document_id}", headers=owner.headers)
    assert deleted.status_code == 204, deleted.text

    with pytest.raises(ClientError, match="NoSuchKey"):
        await object_storage.get_object(image_key)
    with pytest.raises(ClientError, match="NoSuchKey"):
        await object_storage.get_object(version.storage_key)

    logged = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "document.deleted",
            AuditLog.resource_id == uuid.UUID(document_id),
        )
    )
    assert logged is not None
    # One version, two stored objects: the upload and its rendered page.
    assert logged.detail["version_count"] == 1
    assert logged.detail["object_count"] == 2


async def test_delete_is_refused_while_a_worker_is_mid_run(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Deleting a claimed job would pull the row out from under the worker."""
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"
    await client.post(f"{base}/{document_id}/archive", headers=owner.headers)

    job = await db_session.scalar(
        select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
    )
    assert job is not None
    job.status = IngestionStatus.RUNNING
    await db_session.flush()

    refused = await client.delete(f"{base}/{document_id}", headers=owner.headers)
    assert refused.status_code == 409
    assert error_code(refused) == "document_processing"
    assert await db_session.get(Document, uuid.UUID(document_id)) is not None

    # A merely queued job is not blocking: the worker's claim already drops a
    # message whose row has gone, and refusing here would make a document
    # undeletable whenever its queue is backed up.
    job.status = IngestionStatus.QUEUED
    await db_session.flush()
    deleted = await client.delete(f"{base}/{document_id}", headers=owner.headers)
    assert deleted.status_code == 204, deleted.text


async def test_permanent_failures_are_not_retryable(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A deterministic failure would fail identically on the same bytes.

    The worker records both exhausted-transient and permanent failures as
    `FAILED`; only the transient kind can plausibly succeed on another run.
    """
    owner = await make_account(client, "owner@example.com")
    workspace_id = await make_workspace(client, owner)
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    await force_status(db_session, document_id, DocumentStatus.FAILED)
    job = await db_session.scalar(
        select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
    )
    assert job is not None
    job.status = IngestionStatus.FAILED
    job.permanent_failure = True
    job.error = "stored object hash mismatch"
    await db_session.flush()

    refused = await client.post(f"{base}/{document_id}/retry", headers=owner.headers)
    assert refused.status_code == 409
    assert error_code(refused) == "document_permanently_failed"

    # ...and the status endpoint says so rather than offering a doomed button.
    progress = await client.get(f"{base}/{document_id}/status", headers=owner.headers)
    assert progress.json()["retryable"] is False

    # A transient failure that merely exhausted its attempts stays retryable.
    job.permanent_failure = False
    await db_session.flush()
    progress = await client.get(f"{base}/{document_id}/status", headers=owner.headers)
    assert progress.json()["retryable"] is True


async def test_retryable_reflects_the_callers_own_capability(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """`retryable` must mean "you may retry", not "someone may".

    A viewer holds no `UPLOAD_DOCUMENTS`, so reporting the document state alone
    would advertise a button the same caller is refused.
    """
    owner = await make_account(client, "owner@example.com")
    viewer = await make_account(client, "viewer@example.com")
    workspace_id = await make_workspace(client, owner)
    await add_member(client, workspace_id, owner, viewer, "viewer")
    document_id = (await upload(client, owner, workspace_id)).json()["id"]
    base = f"/api/v1/workspaces/{workspace_id}/documents"

    await force_status(db_session, document_id, DocumentStatus.FAILED)

    as_owner = await client.get(f"{base}/{document_id}/status", headers=owner.headers)
    assert as_owner.json()["retryable"] is True

    as_viewer = await client.get(f"{base}/{document_id}/status", headers=viewer.headers)
    assert as_viewer.status_code == 200
    assert as_viewer.json()["retryable"] is False

    # And the flag matches what the endpoint actually does for that caller.
    refused = await client.post(f"{base}/{document_id}/retry", headers=viewer.headers)
    assert refused.status_code == 403


async def test_upload_policy_reports_the_deployed_limits(client: httpx.AsyncClient) -> None:
    """Clients read the effective limits instead of mirroring the defaults."""
    owner = await make_account(client, "owner@example.com")
    viewer = await make_account(client, "viewer@example.com")
    workspace_id = await make_workspace(client, owner)
    await add_member(client, workspace_id, owner, viewer, "viewer")

    # Readable by any member: a viewer never uploads, but the same page renders
    # the limits, and a 403 there would be a confusing way to say "read only".
    policy = await client.get(
        f"/api/v1/workspaces/{workspace_id}/documents/policy",
        headers=viewer.headers,
    )
    assert policy.status_code == 200, policy.text
    body = policy.json()
    assert body["max_upload_bytes"] == 25 * 1024 * 1024
    assert body["max_filename_length"] == 255
    assert sorted(body["accepted_extensions"]) == [".docx", ".markdown", ".md", ".pdf", ".txt"]

    # The literal path must not be captured as a document id.
    assert "document_not_found" not in policy.text

    outsider = await make_account(client, "outsider@example.com")
    hidden = await client.get(
        f"/api/v1/workspaces/{workspace_id}/documents/policy",
        headers=outsider.headers,
    )
    assert hidden.status_code == 404
