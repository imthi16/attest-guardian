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
from app.db.models.operations import AuditLog
from app.storage.s3 import S3ObjectStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.apptools import Account, build_client, make_account

TEST_BUCKET = "nambikkai-test-documents"
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
