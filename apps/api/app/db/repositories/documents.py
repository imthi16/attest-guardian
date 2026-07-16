"""Workspace-scoped repository for documents."""

from collections.abc import Sequence

from sqlalchemy import select

from app.db.models.documents import Document
from app.db.models.enums import DocumentStatus
from app.db.repositories.base import WorkspaceScopedRepository


class DocumentRepository(WorkspaceScopedRepository[Document]):
    model = Document

    async def list_by_status(self, status: DocumentStatus) -> Sequence[Document]:
        statement = select(Document).where(
            Document.workspace_id == self.workspace_id,
            Document.status == status,
        )
        result = await self._session.scalars(statement)
        return result.all()
