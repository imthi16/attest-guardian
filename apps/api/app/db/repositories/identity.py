"""Repositories for users, workspaces, and memberships.

These are intentionally unscoped: they operate on identity data that exists
above the tenant boundary (login, workspace creation, role resolution).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db.models.identity import Membership, User, Workspace
from app.db.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await self._session.scalars(statement)
        return result.first()


class WorkspaceRepository(Repository[Workspace]):
    model = Workspace

    async def get_by_slug(self, slug: str) -> Workspace | None:
        statement = select(Workspace).where(Workspace.slug == slug)
        result = await self._session.scalars(statement)
        return result.first()


class MembershipRepository(Repository[Membership]):
    model = Membership

    async def get_membership(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Membership | None:
        statement = select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id,
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> Sequence[Membership]:
        statement = select(Membership).where(Membership.workspace_id == workspace_id)
        result = await self._session.scalars(statement)
        return result.all()
