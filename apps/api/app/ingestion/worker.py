"""The ingestion worker: deterministic stage transitions with safe retries.

Design notes:

- The database is the source of truth; the queue only carries pointers, so
  duplicate delivery is always safe — claiming is a compare-and-set on the
  job row and terminal states are never reprocessed.
- Each stage transition commits its own transaction, making progress
  observable through the status API while a job runs.
- Failures split into quarantine (malware verdicts — terminal, never
  retried), permanent (integrity/content violations — terminal, dead-letter),
  and transient (everything else — retried up to `max_attempts`, then
  dead-letter).
- `requeue_stale` recovers jobs whose worker died mid-run and queued jobs
  whose enqueue was lost. It scans across workspaces, so a deployed worker
  needs a database role with BYPASSRLS; per-job work binds the workspace
  from the queue message instead.

Run standalone with `python -m app.ingestion.worker` (see `make dev-worker`).
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chunking.chunker import PageInput, chunk_pages
from app.chunking.provenance import ProvenanceError, validate_chunk_provenance
from app.db.models.documents import Chunk, Document, DocumentVersion, Page
from app.db.models.enums import DocumentStatus, IngestionStage, IngestionStatus
from app.db.models.operations import IngestionJob
from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.embeddings import ChunkEmbeddingRepository
from app.db.session import bind_workspace, session_scope
from app.documents.keys import page_image_key
from app.documents.purge import run_pending_purges
from app.documents.validation import UploadRejectedError, detect_kind, verify_content
from app.embeddings.service import EmbeddingService, build_embedding_provider
from app.embeddings.types import DimensionMismatchError, EmbeddingVector
from app.ingestion.queue import JobMessage, JobQueue
from app.ingestion.scanner import MalwareScanner
from app.language import detect_language
from app.parsing.ocr import NullOcrEngine, OcrEngine
from app.parsing.pdf import parse_pdf, render_pdf_page_png
from app.parsing.text import parse_docx, parse_text
from app.parsing.types import ParsedDocument, ParserError
from app.safety.detector import InjectionDetector
from app.safety.scanner import DocumentSafetyReport, InjectionScanner
from app.safety.types import InjectionPolicyConfig
from app.security.events import log_security_event
from app.storage.base import ObjectStorage

logger = logging.getLogger("app.ingestion")

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class JobVanishedError(Exception):
    """The job row disappeared while this worker was processing it.

    Permanent deletion refuses to run while a job is queued or claimed, so this
    is not the ordinary path — but the check and the cascade are not one atomic
    step, and a row can also be removed administratively. Losing the row means
    there is nothing left to record the outcome on, so the worker abandons the
    job quietly instead of failing on an assertion and taking the process down
    with it.
    """


class QuarantinedError(Exception):
    """The scanner flagged the content; the document must be quarantined."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PermanentIngestionError(Exception):
    """The job can never succeed (integrity or content violation)."""


@dataclass(frozen=True)
class _LoadedContent:
    document_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    mime_type: str
    data: bytes


class IngestionWorker:
    """Processes queued ingestion jobs one at a time."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        queue: JobQueue,
        scanner: MalwareScanner,
        ocr_engine: OcrEngine | None = None,
        injection_scanner: InjectionScanner | None = None,
        embedding_service: EmbeddingService | None = None,
        scan_injection: bool = True,
        store_page_images: bool = True,
        chunk_max_chars: int = 1200,
        chunk_overlap_chars: int = 150,
        max_attempts: int = 3,
        stale_after_seconds: int = 300,
    ) -> None:
        self._factory = session_factory
        self._storage = storage
        self._queue = queue
        self._scanner = scanner
        self._ocr_engine = ocr_engine or NullOcrEngine()
        self._embeddings = embedding_service or EmbeddingService()
        self._injection_scanner = injection_scanner or InjectionScanner()
        self._scan_injection = scan_injection
        self._store_page_images = store_page_images
        self._chunk_max_chars = chunk_max_chars
        self._chunk_overlap_chars = chunk_overlap_chars
        self._max_attempts = max_attempts
        self._stale_after = timedelta(seconds=stale_after_seconds)

    async def process_next(self, timeout_seconds: float = 1.0) -> bool:
        """Take one message off the queue; returns False when idle."""
        message = await self._queue.dequeue(timeout_seconds)
        if message is None:
            return False
        await self.process(message)
        return True

    async def process(self, message: JobMessage) -> None:
        if not await self._claim(message):
            return
        try:
            await self._run_stages(message)
        except JobVanishedError:
            logger.info(
                "job row vanished mid-flight; nothing left to record",
                extra={"job_id": str(message.job_id)},
            )
        except QuarantinedError as verdict:
            await self._quarantine(message, verdict.reason)
        except PermanentIngestionError as error:
            await self._fail(message, str(error), retry=False)
        except Exception as error:  # noqa: BLE001 - the worker must survive any job error
            await self._fail(message, f"{type(error).__name__}: {error}", retry=True)
        else:
            await self._finish(message)

    async def _lock_job_and_document(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
    ) -> tuple[IngestionJob | None, Document | None]:
        """Lock a job and its document, document first, and return both.

        The order matters and is a repository-wide invariant: the lifecycle's
        retry and permanent-delete paths lock the *document* and then touch its
        jobs, so a worker that locked the job row first would deadlock with them.
        PostgreSQL would then abort one of the two — the worker at a point where
        it cannot record anything, or the delete request as a 500.

        Locking the document first also makes the delete-time "is a job running?"
        check meaningful. Holding that lock, a delete blocks any claim, so a job
        it saw as merely `QUEUED` cannot become `RUNNING` behind its back; and a
        claim that arrives after the cascade finds no job row and drops the
        message.

        The job's `document_id` is read without a lock only to find *which*
        document to lock; it never changes for a given job.
        """
        document_id = await session.scalar(
            select(IngestionJob.document_id).where(IngestionJob.id == job_id)
        )
        document = (
            None
            if document_id is None
            else await session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
        )
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
        )
        return job, document

    async def _claim(self, message: JobMessage) -> bool:
        """Compare-and-set QUEUED -> RUNNING; anything else is a duplicate."""
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            job, document = await self._lock_job_and_document(session, message.job_id)
            if job is None:
                logger.warning("ingestion job missing", extra={"job_id": str(message.job_id)})
                return False
            if job.status is not IngestionStatus.QUEUED:
                logger.info(
                    "duplicate or in-flight delivery ignored",
                    extra={"job_id": str(job.id), "status": job.status.value},
                )
                return False
            job.status = IngestionStatus.RUNNING
            job.started_at = datetime.now(UTC)
            job.attempts += 1
            job.error = None
            if document is not None:
                document.status = DocumentStatus.PROCESSING
            logger.info(
                "ingestion started",
                extra={"job_id": str(job.id), "attempt": job.attempts},
            )
            return True

    async def _run_stages(self, message: JobMessage) -> None:
        """Walk the stages in the order `IngestionStage` declares them.

        Normalization runs before chunking because the chunker copies each
        page's detected language onto every chunk it cuts from that page.
        Embedding runs after chunking because it needs the persisted chunk ids.
        """
        content = await self._stage_validate(message)
        await self._stage_scan(message, content)
        parsed = await self._stage_parse(message, content)
        await self._stage_ocr(message, content, parsed)
        languages = await self._stage_normalize(message, content, parsed)
        await self._stage_chunk(message, content, parsed, languages)
        embedded = await self._stage_embed(message, content)
        await self._stage_index(message, content, embedded)

    async def _advance_stage(self, message: JobMessage, stage: IngestionStage) -> None:
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            job = await session.get(IngestionJob, message.job_id)
            if job is None:
                raise JobVanishedError
            job.stage = stage
        logger.info(
            "stage reached",
            extra={"job_id": str(message.job_id), "stage": stage.value},
        )

    async def _stage_validate(self, message: JobMessage) -> _LoadedContent:
        await self._advance_stage(message, IngestionStage.VALIDATING)
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            job = await session.get(IngestionJob, message.job_id)
            if job is None:
                raise JobVanishedError
            document = await session.get(Document, job.document_id)
            if document is None:
                msg = "document row is gone"
                raise PermanentIngestionError(msg)
            version = await session.scalar(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.version_number.desc())
                .limit(1)
            )
            if version is None:
                msg = "document has no stored version"
                raise PermanentIngestionError(msg)
            storage_key = version.storage_key
            expected_sha256 = version.sha256
            filename = document.source_filename
            loaded = _LoadedContent(
                document_id=document.id,
                version_id=version.id,
                version_number=version.version_number,
                mime_type=document.mime_type,
                data=b"",
            )

        data = await self._storage.get_object(storage_key)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            msg = "stored object does not match its recorded hash"
            raise PermanentIngestionError(msg)
        try:
            verify_content(detect_kind(filename), data)
        except UploadRejectedError as rejection:
            raise PermanentIngestionError(rejection.message) from rejection
        return _LoadedContent(
            document_id=loaded.document_id,
            version_id=loaded.version_id,
            version_number=loaded.version_number,
            mime_type=loaded.mime_type,
            data=data,
        )

    async def _stage_scan(self, message: JobMessage, content: _LoadedContent) -> None:
        await self._advance_stage(message, IngestionStage.SCANNING)
        verdict = await self._scanner.scan(content.data)
        if not verdict.clean:
            raise QuarantinedError(verdict.reason or "malware detected")

    async def _stage_parse(self, message: JobMessage, content: _LoadedContent) -> ParsedDocument:
        await self._advance_stage(message, IngestionStage.PARSING)
        try:
            if content.mime_type == "application/pdf":
                parsed = parse_pdf(content.data)
            elif content.mime_type == _DOCX_MIME:
                parsed = parse_docx(content.data)
            else:
                parsed = parse_text(content.data)
        except ParserError as error:
            raise PermanentIngestionError(str(error)) from error
        logger.info(
            "parsed document",
            extra={
                "job_id": str(message.job_id),
                "parser": parsed.parser,
                "pages": len(parsed.pages),
                "scanned_pages": sum(1 for page in parsed.pages if page.needs_ocr),
            },
        )
        return parsed

    async def _stage_ocr(
        self,
        message: JobMessage,
        content: _LoadedContent,
        parsed: ParsedDocument,
    ) -> None:
        await self._advance_stage(message, IngestionStage.OCR)
        for page in parsed.pages:
            if not page.needs_ocr:
                continue
            image_png = render_pdf_page_png(content.data, page.page_number)
            if self._store_page_images:
                # Built from the shared key module so the object lands under the
                # document prefix a permanent deletion purges: this write
                # precedes the `pages` row that records it, so a run that fails
                # here leaves content the database never learns about.
                image_key = page_image_key(
                    message.workspace_id,
                    content.document_id,
                    version_number=content.version_number,
                    page_number=page.page_number,
                )
                await self._storage.put_object(image_key, image_png, "image/png")
                page.image_storage_key = image_key
            result = await self._ocr_engine.recognize(image_png)
            page.text = result.text
            page.ocr_engine = self._ocr_engine.name
            page.ocr_confidence = result.confidence
            page.ocr_blocks = result.blocks or None
            logger.info(
                "page ocr complete",
                extra={
                    "job_id": str(message.job_id),
                    "page": page.page_number,
                    "engine": self._ocr_engine.name,
                    "confidence": result.confidence,
                },
            )
        await self._persist_pages(message, content, parsed)

    async def _persist_pages(
        self,
        message: JobMessage,
        content: _LoadedContent,
        parsed: ParsedDocument,
    ) -> None:
        """Replace the version's pages atomically; reprocessing never duplicates."""
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            await session.execute(
                delete(Page).where(Page.document_version_id == content.version_id)
            )
            for page in parsed.pages:
                session.add(
                    Page(
                        document_version_id=content.version_id,
                        page_number=page.page_number,
                        text=page.text,
                        ocr_engine=page.ocr_engine,
                        ocr_confidence=page.ocr_confidence,
                        image_storage_key=page.image_storage_key,
                        ocr_blocks=(
                            [block.as_provenance() for block in page.ocr_blocks]
                            if page.ocr_blocks
                            else None
                        ),
                    )
                )
            version = await session.get(DocumentVersion, content.version_id)
            if version is not None:
                version.page_count = len(parsed.pages)

    async def _stage_normalize(
        self,
        message: JobMessage,
        content: _LoadedContent,
        parsed: ParsedDocument,
    ) -> dict[int, str]:
        """Detect each page's language and record it as provenance.

        Stored text is *not* rewritten. Chunk content must stay byte-identical
        to `page_text[char_start:char_end]` — `validate_chunk_provenance`
        enforces that, and consumers apply `normalize_for_match` when they
        compare rather than relying on a normalized copy in the database. So
        normalization here means classification: the canonical form is used to
        decide the language, and only the verdict is persisted.

        An undetectable page records `unknown` rather than `NULL`. The
        distinction is worth keeping: `unknown` is a verdict on a page with no
        classifiable letters, while `NULL` means this stage never ran.
        """
        await self._advance_stage(message, IngestionStage.NORMALIZING)
        languages = {
            page.page_number: detect_language(page.text).language.value for page in parsed.pages
        }
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            for page_number, language in languages.items():
                await session.execute(
                    update(Page)
                    .where(
                        Page.document_version_id == content.version_id,
                        Page.page_number == page_number,
                    )
                    .values(language=language)
                )
        logger.info(
            "detected page languages",
            extra={
                "job_id": str(message.job_id),
                "languages": sorted(set(languages.values())),
                "pages": len(languages),
            },
        )
        return languages

    async def _stage_embed(
        self,
        message: JobMessage,
        content: _LoadedContent,
    ) -> list[tuple[uuid.UUID, EmbeddingVector]]:
        """Embed this version's persisted chunks, preserving chunk order.

        Reads the chunks back rather than embedding the drafts, so a vector is
        only ever produced for text that actually reached the table with valid
        provenance.

        A provider failure propagates as `EmbeddingError`, which `process`
        treats as transient and retries; a `DimensionMismatchError` is raised as
        permanent instead, because a provider returning the wrong width will do
        so again on the same input and no number of retries will fix it.
        """
        await self._advance_stage(message, IngestionStage.EMBEDDING)
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            rows = (
                await session.execute(
                    select(Chunk.id, Chunk.content)
                    .where(Chunk.document_version_id == content.version_id)
                    .order_by(Chunk.chunk_index)
                )
            ).all()

        if not rows:
            logger.info("no chunks to embed", extra={"job_id": str(message.job_id)})
            return []

        try:
            result = self._embeddings.embed_texts([row.content for row in rows])
        except DimensionMismatchError as error:
            raise PermanentIngestionError(f"embedding provider misconfigured: {error}") from error

        return [(row.id, vector) for row, vector in zip(rows, result.vectors, strict=True)]

    async def _stage_index(
        self,
        message: JobMessage,
        content: _LoadedContent,
        embedded: Sequence[tuple[uuid.UUID, EmbeddingVector]],
    ) -> None:
        """Persist the vectors so dense retrieval can reach this document.

        `upsert` is keyed by chunk and model version, so re-running a job
        replaces vectors rather than accumulating them, and a model upgrade adds
        a row instead of destroying the old one.
        """
        await self._advance_stage(message, IngestionStage.INDEXING)
        if not embedded:
            return
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            repository = ChunkEmbeddingRepository(session, message.workspace_id)
            for chunk_id, vector in embedded:
                await repository.upsert(chunk_id, vector)
        logger.info(
            "indexed embeddings",
            extra={
                "job_id": str(message.job_id),
                "chunks": len(embedded),
                "model": self._embeddings.model,
                "model_version": self._embeddings.model_version,
            },
        )

    async def _stage_chunk(
        self,
        message: JobMessage,
        content: _LoadedContent,
        parsed: ParsedDocument,
        languages: Mapping[int, str],
    ) -> None:
        """Chunk parsed pages and persist only provenance-validated chunks."""
        await self._advance_stage(message, IngestionStage.CHUNKING)
        page_inputs = [
            PageInput(
                page_number=page.page_number,
                text=page.text,
                # From the normalization stage, so every chunk carries the
                # language its page was detected as. Without this the column is
                # silently NULL and citation and verification lose a provenance
                # field they are required to have.
                language=languages.get(page.page_number),
                ocr_engine=page.ocr_engine,
                ocr_confidence=page.ocr_confidence,
            )
            for page in parsed.pages
        ]
        drafts = chunk_pages(
            page_inputs,
            max_chars=self._chunk_max_chars,
            overlap=self._chunk_overlap_chars,
        )
        texts_by_page = {page.page_number: page.text for page in page_inputs}
        try:
            for draft in drafts:
                validate_chunk_provenance(draft, texts_by_page[draft.page_number])
        except ProvenanceError as error:
            # A provenance failure is a chunker bug, not bad input; never
            # persist anything from this run.
            raise PermanentIngestionError(f"chunk provenance invalid: {error}") from error

        # Prompt-injection scan: treat chunk text as untrusted data and detect
        # instruction-like passages *before* anything is persisted, so poisoned
        # content never reaches the chunks table (and thus never retrieval or
        # generation). A quarantine verdict aborts the stage via the shared
        # quarantine path, leaving no chunk rows behind.
        flagged_report: DocumentSafetyReport | None = None
        if self._scan_injection:
            report = self._injection_scanner.scan_chunks(
                [(index, draft.content) for index, draft in enumerate(drafts)]
            )
            if report.is_quarantined:
                self._log_injection(message, content, report)
                raise QuarantinedError(report.reason)
            if report.trace.flagged_count:
                flagged_report = report
                logger.warning(
                    "document has flagged-but-allowed chunks",
                    extra={
                        "job_id": str(message.job_id),
                        "safety": report.trace.as_metadata(),
                    },
                )

        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            if flagged_report is not None:
                await AuditLogRepository(session).record(
                    action="document.prompt_injection_flagged",
                    resource_type="document",
                    resource_id=content.document_id,
                    workspace_id=message.workspace_id,
                    detail={
                        "decision": flagged_report.decision.value,
                        "safety": flagged_report.trace.as_metadata(),
                    },
                )
            await session.execute(
                delete(Chunk).where(Chunk.document_version_id == content.version_id)
            )
            for index, draft in enumerate(drafts):
                session.add(
                    Chunk(
                        workspace_id=message.workspace_id,
                        document_version_id=content.version_id,
                        chunk_index=index,
                        content=draft.content,
                        content_hash=draft.content_hash,
                        token_count=draft.token_count,
                        page_number=draft.page_number,
                        section=draft.section,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                        language=draft.language,
                        ocr_engine=draft.ocr_engine,
                        ocr_confidence=draft.ocr_confidence,
                    )
                )
        logger.info(
            "chunked document",
            extra={"job_id": str(message.job_id), "chunks": len(drafts)},
        )

    async def _finish(self, message: JobMessage) -> None:
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            # Document before job, as everywhere that writes both rows.
            job, document = await self._lock_job_and_document(session, message.job_id)
            if job is None:
                # Terminal handler: there is no row left to mark, and raising
                # here would escape `process` (this runs in its `else` branch).
                logger.info(
                    "job row vanished before completion could be recorded",
                    extra={"job_id": str(message.job_id)},
                )
                return
            job.status = IngestionStatus.SUCCEEDED
            job.stage = IngestionStage.READY
            job.finished_at = datetime.now(UTC)
            if document is not None:
                document.status = DocumentStatus.READY
            await AuditLogRepository(session).record(
                action="document.ready",
                resource_type="document",
                resource_id=job.document_id,
                workspace_id=message.workspace_id,
            )
        logger.info("ingestion succeeded", extra={"job_id": str(message.job_id)})

    async def _quarantine(self, message: JobMessage, reason: str) -> None:
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            job, document = await self._lock_job_and_document(session, message.job_id)
            if job is None:
                logger.info(
                    "job row vanished before quarantine could be recorded",
                    extra={"job_id": str(message.job_id)},
                )
                return
            job.status = IngestionStatus.FAILED
            job.error = f"quarantined: {reason}"
            job.finished_at = datetime.now(UTC)
            if document is not None:
                document.status = DocumentStatus.QUARANTINED
            await AuditLogRepository(session).record(
                action="document.quarantined",
                resource_type="document",
                resource_id=job.document_id,
                workspace_id=message.workspace_id,
                detail={"reason": reason},
            )
        logger.warning(
            "document quarantined",
            extra={"job_id": str(message.job_id), "reason": reason},
        )

    def _log_injection(
        self,
        message: JobMessage,
        content: _LoadedContent,
        report: DocumentSafetyReport,
    ) -> None:
        """Emit a privacy-safe security event for a prompt-injection quarantine.

        Carries only counts, categories, and the aggregate score — never the
        matched chunk text — so operators can alert without the event leaking
        untrusted document content.
        """
        log_security_event(
            "prompt_injection_quarantine",
            job_id=str(message.job_id),
            workspace_id=str(message.workspace_id),
            document_id=str(content.document_id),
            **report.trace.as_metadata(),
        )

    async def _fail(self, message: JobMessage, error: str, *, retry: bool) -> None:
        async with session_scope(self._factory) as session:
            await bind_workspace(session, message.workspace_id)
            job, document = await self._lock_job_and_document(session, message.job_id)
            if job is None:
                # The document was deleted under this job. Asserting here would
                # raise from inside an exception handler and escape
                # `run_forever`, stopping the worker over one deleted document.
                logger.info(
                    "job row vanished before failure could be recorded",
                    extra={"job_id": str(message.job_id)},
                )
                return
            job.error = error
            will_retry = retry and job.attempts < self._max_attempts
            if will_retry:
                job.status = IngestionStatus.QUEUED
            else:
                job.status = IngestionStatus.FAILED
                # A deterministic failure is recorded as such so the retry
                # endpoint can refuse it: the same bytes would fail identically.
                job.permanent_failure = not retry
                job.finished_at = datetime.now(UTC)
                if document is not None:
                    document.status = DocumentStatus.FAILED
                await AuditLogRepository(session).record(
                    action="document.ingestion_failed",
                    resource_type="document",
                    resource_id=job.document_id,
                    workspace_id=message.workspace_id,
                    detail={"error": error},
                )
        if will_retry:
            await self._queue.enqueue(message)
            logger.warning(
                "ingestion attempt failed; requeued",
                extra={"job_id": str(message.job_id), "error": error},
            )
        else:
            await self._queue.dead_letter(message)
            logger.error(
                "ingestion failed terminally",
                extra={"job_id": str(message.job_id), "error": error},
            )

    async def requeue_stale(self) -> int:
        """Re-enqueue crashed (stale RUNNING) and orphaned (stale QUEUED) jobs.

        Duplicate messages are harmless because claiming is a compare-and-set.
        """
        cutoff = datetime.now(UTC) - self._stale_after
        async with session_scope(self._factory) as session:
            stale_running = (
                await session.scalars(
                    select(IngestionJob).where(
                        IngestionJob.status == IngestionStatus.RUNNING,
                        IngestionJob.started_at < cutoff,
                    )
                )
            ).all()
            stale_queued = (
                await session.scalars(
                    select(IngestionJob).where(
                        IngestionJob.status == IngestionStatus.QUEUED,
                        IngestionJob.updated_at < cutoff,
                    )
                )
            ).all()
            messages = []
            for job in stale_running:
                job.status = IngestionStatus.QUEUED
                messages.append(JobMessage(job_id=job.id, workspace_id=job.workspace_id))
            for job in stale_queued:
                job.updated_at = datetime.now(UTC)
                messages.append(JobMessage(job_id=job.id, workspace_id=job.workspace_id))
        for queue_message in messages:
            await self._queue.enqueue(queue_message)
            logger.warning(
                "stale job requeued",
                extra={"job_id": str(queue_message.job_id)},
            )
        return len(messages)

    async def purge_deleted_content(self) -> int:
        """Finish the storage half of any permanent deletions awaiting a purge.

        Permanent deletion commits its row removal with a durable purge record
        and performs no storage call itself, so something has to complete it;
        the worker is that something. Failures leave the record pending, so the
        next idle pass tries again.
        """
        return await run_pending_purges(session_factory=self._factory, storage=self._storage)

    async def run_forever(self, *, idle_timeout_seconds: float = 5.0) -> None:
        """Consume jobs until cancelled; recover stale jobs and purge when idle."""
        while True:
            worked = await self.process_next(idle_timeout_seconds)
            if not worked:
                await self.requeue_stale()
                await self.purge_deleted_content()


def _main() -> None:
    from app.config import get_settings
    from app.db.session import get_session_factory
    from app.ingestion.queue import RedisJobQueue
    from app.ingestion.scanner import SignatureScanner
    from app.parsing.ocr import build_ocr_engine
    from app.storage.s3 import S3ObjectStorage

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    worker = IngestionWorker(
        session_factory=get_session_factory(),
        storage=S3ObjectStorage(settings),
        queue=RedisJobQueue(
            settings.redis_url,
            queue_key=settings.ingestion_queue_key,
            dead_letter_key=settings.ingestion_dead_letter_key,
        ),
        scanner=SignatureScanner(),
        ocr_engine=build_ocr_engine(settings.ocr_engine, settings.ocr_languages),
        injection_scanner=InjectionScanner(
            InjectionDetector(
                policy=InjectionPolicyConfig(
                    flag_score=settings.injection_flag_score,
                    quarantine_score=settings.injection_quarantine_score,
                    quarantine_on_high_severity=(settings.injection_quarantine_on_high_severity),
                )
            )
        ),
        # Same construction retrieval queries with, so a document is indexed
        # under exactly the model and version a search will look for.
        embedding_service=EmbeddingService(build_embedding_provider(settings)),
        scan_injection=settings.injection_scan_enabled,
        store_page_images=settings.ingestion_store_page_images,
        chunk_max_chars=settings.chunk_max_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        max_attempts=settings.ingestion_max_attempts,
        stale_after_seconds=settings.ingestion_stale_after_seconds,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    _main()
