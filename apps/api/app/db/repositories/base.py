"""Generic repository primitives.

`WorkspaceScopedRepository` is the authorization boundary required by the
project rules: tenant-owned rows must be read through it so every query
carries the workspace filter, regardless of what routes or services do.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base, WorkspaceOwnedModel


class Repository[ModelT: Base]:
    """Minimal persistence operations for one model."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self._session.get(self.model, entity_id)

    async def add(self, instance: ModelT) -> ModelT:
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self._session.delete(instance)
        await self._session.flush()


class WorkspaceScopedRepository[ScopedModelT: WorkspaceOwnedModel](Repository[ScopedModelT]):
    """Repository whose every query is filtered to one workspace."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        super().__init__(session)
        self.workspace_id = workspace_id

    async def get(self, entity_id: uuid.UUID) -> ScopedModelT | None:
        statement = select(self.model).where(
            self.model.id == entity_id,
            self.model.workspace_id == self.workspace_id,
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def add(self, instance: ScopedModelT) -> ScopedModelT:
        if instance.workspace_id != self.workspace_id:
            msg = "instance belongs to a different workspace"
            raise ValueError(msg)
        return await super().add(instance)

    async def list_all(self) -> Sequence[ScopedModelT]:
        statement = select(self.model).where(self.model.workspace_id == self.workspace_id)
        result = await self._session.scalars(statement)
        return result.all()
