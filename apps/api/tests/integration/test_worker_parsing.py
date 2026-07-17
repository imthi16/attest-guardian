"""Parsing and OCR inside the worker: page provenance end to end."""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from app.config import Settings
from app.db.models.documents import Chunk, Document, DocumentVersion, Page
from app.db.models.enums import DocumentStatus, IngestionStatus
from app.db.models.operations import IngestionJob
from app.ingestion.queue import JobMessage, RedisJobQueue
from app.ingestion.scanner import SignatureScanner
from app.ingestion.worker import IngestionWorker
from app.parsing.types import OcrBlock, OcrResult
from app.storage.s3 import S3ObjectStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from tests.integration import factories
from tests.integration.dbtools import alembic, provision_database
from tests.pdftools import digital_pdf

PARSING_DB = "nambikkai_parsing_test"
TEST_BUCKET = "nambikkai-test-documents"
TAMIL_TEXT = "வணக்கம் — இது ஒரு சோதனை ஆவணம்."


@pytest.fixture(scope="module")
def parsing_db_url() -> str:
    url = provision_database(PARSING_DB)
    result = alembic(["upgrade", "head"], url)
    assert result.returncode == 0, result.stderr
    return url


@pytest.fixture
async def engine(parsing_db_url: str) -> AsyncIterator[AsyncEngine]:
    instance = create_async_engine(parsing_db_url, poolclass=NullPool)
    yield instance
    await instance.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def storage() -> S3ObjectStorage:
    instance = S3ObjectStorage(Settings(s3_bucket=TEST_BUCKET))
    try:
        asyncio.run(instance.ensure_bucket())
    except Exception as error:  # noqa: BLE001 - fail fast with instructions
        pytest.fail(f"MinIO is required; start it with `make infra-up` ({error})")
    return instance


@pytest.fixture
async def queue() -> AsyncIterator[RedisJobQueue]:
    prefix = f"test:parsing:{uuid.uuid4().hex}"
    instance = RedisJobQueue(
        Settings().redis_url,
        queue_key=f"{prefix}:queue",
        dead_letter_key=f"{prefix}:dead",
    )
    try:
        yield instance
    finally:
        await instance.aclose()


class FakeTamilOcr:
    """Deterministic OCR stand-in with Tamil output and block provenance."""

    name = "fake-tamil-ocr"

    async def recognize(self, image_png: bytes) -> OcrResult:
        assert image_png.startswith(b"\x89PNG\r\n")
        return OcrResult(
            text=TAMIL_TEXT,
            confidence=0.87,
            blocks=[OcrBlock(text=TAMIL_TEXT, confidence=0.87, bbox=(10, 20, 300, 40))],
        )


@dataclass(frozen=True)
class Seeded:
    message: JobMessage
    document_id: uuid.UUID
    version_id: uuid.UUID


async def seed(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    *,
    content: bytes,
    filename: str,
    mime_type: str,
) -> Seeded:
    sha256 = hashlib.sha256(content).hexdigest()
    async with factory() as session, session.begin():
        owner = await factories.make_user(session)
        workspace = await factories.make_workspace(session, owner)
        document = Document(
            workspace_id=workspace.id,
            created_by=owner.id,
            title=filename,
            source_filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256,
        )
        session.add(document)
        await session.flush()
        storage_key = f"workspaces/{workspace.id}/documents/{document.id}/v1-{uuid.uuid4().hex}"
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            storage_key=storage_key,
            sha256=sha256,
            size_bytes=len(content),
        )
        session.add(version)
        await session.flush()
        job = IngestionJob(workspace_id=workspace.id, document_id=document.id)
        session.add(job)
        await session.flush()
        seeded = Seeded(
            message=JobMessage(job_id=job.id, workspace_id=workspace.id),
            document_id=document.id,
            version_id=version.id,
        )
    await storage.put_object(storage_key, content, mime_type)
    return seeded


def build_worker(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
    *,
    ocr: FakeTamilOcr | None = None,
) -> IngestionWorker:
    return IngestionWorker(
        session_factory=factory,
        storage=storage,
        queue=queue,
        scanner=SignatureScanner(),
        ocr_engine=ocr,
    )


async def pages_for(
    factory: async_sessionmaker[AsyncSession],
    version_id: uuid.UUID,
) -> list[Page]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(Page)
                    .where(Page.document_version_id == version_id)
                    .order_by(Page.page_number)
                )
            ).all()
        )


async def state_of(
    factory: async_sessionmaker[AsyncSession],
    seeded: Seeded,
) -> tuple[Document, DocumentVersion, IngestionJob]:
    async with factory() as session:
        document = (
            await session.scalars(select(Document).where(Document.id == seeded.document_id))
        ).one()
        version = (
            await session.scalars(
                select(DocumentVersion).where(DocumentVersion.id == seeded.version_id)
            )
        ).one()
        job = (
            await session.scalars(
                select(IngestionJob).where(IngestionJob.id == seeded.message.job_id)
            )
        ).one()
        return document, version, job


async def test_digital_pdf_persists_page_text_without_ocr(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=digital_pdf("Digital page one with plenty of text.", "And digital page two."),
        filename="digital.pdf",
        mime_type="application/pdf",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue).process_next(0)

    document, version, job = await state_of(factory, seeded)
    assert job.status is IngestionStatus.SUCCEEDED
    assert document.status is DocumentStatus.READY
    assert version.page_count == 2

    pages = await pages_for(factory, seeded.version_id)
    assert [page.page_number for page in pages] == [1, 2]
    assert "Digital page one" in (pages[0].text or "")
    assert pages[0].ocr_engine is None
    assert pages[0].ocr_confidence is None
    assert pages[0].image_storage_key is None


async def test_scanned_pages_get_ocr_provenance_and_image_refs(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=digital_pdf("A digital page with more than enough text.", ""),
        filename="mixed.pdf",
        mime_type="application/pdf",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue, ocr=FakeTamilOcr()).process_next(0)

    pages = await pages_for(factory, seeded.version_id)
    digital, scanned = pages
    assert digital.ocr_engine is None
    assert scanned.text == TAMIL_TEXT
    assert scanned.ocr_engine == "fake-tamil-ocr"
    assert scanned.ocr_confidence == pytest.approx(0.87)
    assert scanned.ocr_blocks == [
        {"text": TAMIL_TEXT, "confidence": 0.87, "bbox": [10, 20, 300, 40]}
    ]
    assert scanned.image_storage_key is not None
    stored_image = await storage.get_object(scanned.image_storage_key)
    assert stored_image.startswith(b"\x89PNG\r\n")


async def test_scanned_page_without_engine_keeps_unavailable_marker(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=digital_pdf(""),
        filename="scan-only.pdf",
        mime_type="application/pdf",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue).process_next(0)

    pages = await pages_for(factory, seeded.version_id)
    assert pages[0].ocr_engine == "unavailable"
    assert pages[0].text == ""
    assert pages[0].ocr_confidence is None


async def test_malformed_pdf_fails_permanently(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=b"%PDF-1.4\nnot really a pdf body",
        filename="broken.pdf",
        mime_type="application/pdf",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue).process_next(0)

    document, _, job = await state_of(factory, seeded)
    assert job.status is IngestionStatus.FAILED
    assert document.status is DocumentStatus.FAILED
    assert await queue.list_dead() == [seeded.message]


async def test_tamil_text_document_becomes_a_page(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=TAMIL_TEXT.encode(),
        filename="tamil.txt",
        mime_type="text/plain",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue).process_next(0)

    pages = await pages_for(factory, seeded.version_id)
    assert len(pages) == 1
    assert pages[0].text == TAMIL_TEXT


async def chunks_for(
    factory: async_sessionmaker[AsyncSession],
    version_id: uuid.UUID,
) -> list[Chunk]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.document_version_id == version_id)
                    .order_by(Chunk.chunk_index)
                )
            ).all()
        )


async def test_chunks_are_persisted_with_verified_provenance(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    markdown = (
        "# அறிமுகம்\n\n"
        f"{TAMIL_TEXT}\n\n"
        "## Details\n\nAn English paragraph with enough words to count tokens."
    )
    seeded = await seed(
        factory,
        storage,
        content=markdown.encode(),
        filename="notes.md",
        mime_type="text/markdown",
    )
    await queue.enqueue(seeded.message)
    await build_worker(factory, storage, queue).process_next(0)

    pages = await pages_for(factory, seeded.version_id)
    chunks = await chunks_for(factory, seeded.version_id)
    assert chunks, "chunks must be persisted"
    page_text = pages[0].text or ""
    for index, chunk in enumerate(chunks):
        assert chunk.chunk_index == index
        assert chunk.workspace_id == seeded.message.workspace_id
        assert chunk.page_number == 1
        assert chunk.token_count > 0
        assert page_text[chunk.char_start : chunk.char_end] == chunk.content
        assert hashlib.sha256(chunk.content.encode()).hexdigest() == chunk.content_hash
    assert chunks[0].section == "அறிமுகம்"
    assert any(chunk.section == "அறிமுகம் > Details" for chunk in chunks)


async def test_reprocessing_replaces_pages_without_duplicates(
    factory: async_sessionmaker[AsyncSession],
    storage: S3ObjectStorage,
    queue: RedisJobQueue,
) -> None:
    seeded = await seed(
        factory,
        storage,
        content=digital_pdf("Reprocessed content page, long enough to be digital."),
        filename="reprocess.pdf",
        mime_type="application/pdf",
    )
    worker = build_worker(factory, storage, queue)
    await queue.enqueue(seeded.message)
    await worker.process_next(0)

    async with factory() as session, session.begin():
        job = IngestionJob(
            workspace_id=seeded.message.workspace_id,
            document_id=seeded.document_id,
        )
        session.add(job)
        await session.flush()
        second_message = JobMessage(job_id=job.id, workspace_id=seeded.message.workspace_id)
    await queue.enqueue(second_message)
    await worker.process_next(0)

    pages = await pages_for(factory, seeded.version_id)
    assert len(pages) == 1
    chunks = await chunks_for(factory, seeded.version_id)
    assert len(chunks) == 1  # replaced, not duplicated
