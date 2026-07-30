"""Workspace-scoped repository for documents."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.db.models.documents import Document, DocumentVersion, Page
from app.db.models.enums import DocumentStatus
from app.db.repositories.base import Repository, WorkspaceScopedRepository


class DocumentRepository(WorkspaceScopedRepository[Document]):
    model = Document

    async def count(self) -> int:
        """Number of documents in this workspace (for upload quota checks)."""
        statement = (
            select(func.count())
            .select_from(Document)
            .where(Document.workspace_id == self.workspace_id)
        )
        return await self._session.scalar(statement) or 0

    async def total_size_bytes(self) -> int:
        """Sum of stored document sizes in this workspace, in bytes."""
        statement = select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.workspace_id == self.workspace_id
        )
        return await self._session.scalar(statement) or 0

    async def list_by_status(self, status: DocumentStatus) -> Sequence[Document]:
        statement = select(Document).where(
            Document.workspace_id == self.workspace_id,
            Document.status == status,
        )
        result = await self._session.scalars(statement)
        return result.all()

    async def get_for_update(self, entity_id: uuid.UUID) -> Document | None:
        """Read a document holding a row lock until the transaction ends.

        Lifecycle transitions that branch on `status` or `archived_at` must use
        this rather than `get`: two concurrent requests reading the same row
        would otherwise both see the pre-transition value and both act on it —
        two retries of one failed document, for instance, would each enqueue a
        job and two workers would then race over the same pages and chunks.
        """
        statement = (
            select(Document)
            .where(
                Document.id == entity_id,
                Document.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def get_by_sha256(self, sha256: str) -> Document | None:
        statement = select(Document).where(
            Document.workspace_id == self.workspace_id,
            Document.sha256 == sha256,
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def list_ordered(self, *, include_archived: bool = False) -> Sequence[Document]:
        """Newest first. Archived documents are excluded unless asked for.

        Quota counting deliberately still includes archived documents: their
        bytes remain stored until the document is deleted permanently, so
        letting archival free quota would let a workspace store more than it
        is allowed.
        """
        statement = select(Document).where(Document.workspace_id == self.workspace_id)
        if not include_archived:
            statement = statement.where(Document.archived_at.is_(None))
        result = await self._session.scalars(statement.order_by(Document.created_at.desc()))
        return result.all()


class DocumentVersionRepository(Repository[DocumentVersion]):
    """Versions are reached through their (workspace-checked) document."""

    model = DocumentVersion

    async def list_for_document(self, document_id: uuid.UUID) -> Sequence[DocumentVersion]:
        """Every stored version, oldest first (used when purging content)."""
        statement = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
        )
        result = await self._session.scalars(statement)
        return result.all()

    async def list_page_image_keys(self, document_id: uuid.UUID) -> Sequence[str]:
        """Stored page-image keys for every version of a document.

        Rendered page images are document content: they are pictures of the
        uploaded pages, kept for the citation viewer when
        `ingestion_store_page_images` is on. Deleting the rows cascades the only
        record of these keys away, so a purge has to collect them first or the
        images outlive the "permanent" deletion in object storage.
        """
        statement = (
            select(Page.image_storage_key)
            .join(DocumentVersion, Page.document_version_id == DocumentVersion.id)
            .where(
                DocumentVersion.document_id == document_id,
                Page.image_storage_key.is_not(None),
            )
        )
        result = await self._session.scalars(statement)
        return [key for key in result.all() if key is not None]

    async def get_latest_for_document(self, document_id: uuid.UUID) -> DocumentVersion | None:
        statement = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.first()
