"""Workspace and membership endpoints under `/api/v1/workspaces`.

Authorization layering: the workspace context proves membership (non-members
get the same 404 as a missing workspace), `RequireAction` applies the role
matrix, and per-member mutations additionally check `can_manage_role` for
both the member being touched and the role being granted. Every mutation
appends an audit event in the same transaction.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.auth import errors
from app.auth.dependencies import CurrentUserDep, SessionDep
from app.auth.permissions import WorkspaceAction, can_manage_role
from app.auth.workspace import RequireAction, WorkspaceContext
from app.db.models.enums import MembershipRole
from app.db.models.identity import Membership, Workspace
from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.identity import (
    MembershipRepository,
    UserRepository,
    WorkspaceRepository,
)
from app.schemas.workspaces import (
    AddMemberRequest,
    MemberResponse,
    UpdateMemberRoleRequest,
    WorkspaceCreateRequest,
    WorkspaceWithRoleResponse,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

ViewerContext = Annotated[WorkspaceContext, Depends(RequireAction(WorkspaceAction.VIEW))]
ManagerContext = Annotated[
    WorkspaceContext,
    Depends(RequireAction(WorkspaceAction.MANAGE_MEMBERS)),
]


def _derive_slug(name: str) -> str:
    stem = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")[:80]
    stem = stem or "workspace"
    return f"{stem}-{uuid.uuid4().hex[:6]}"


def _member_response(membership: Membership) -> MemberResponse:
    return MemberResponse(
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.post("", response_model=WorkspaceWithRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreateRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> WorkspaceWithRoleResponse:
    workspaces = WorkspaceRepository(session)
    slug = body.slug or _derive_slug(body.name)
    if await workspaces.get_by_slug(slug) is not None:
        raise errors.slug_already_exists()
    workspace = await workspaces.add(
        Workspace(name=body.name, slug=slug, created_by=current_user.id)
    )
    await MembershipRepository(session).add(
        Membership(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=MembershipRole.OWNER,
        )
    )
    await AuditLogRepository(session).record(
        action="workspace.created",
        resource_type="workspace",
        resource_id=workspace.id,
        workspace_id=workspace.id,
        actor_user_id=current_user.id,
        detail={"name": workspace.name, "slug": workspace.slug},
    )
    return WorkspaceWithRoleResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        created_at=workspace.created_at,
        role=MembershipRole.OWNER,
    )


@router.get("", response_model=list[WorkspaceWithRoleResponse])
async def list_my_workspaces(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[WorkspaceWithRoleResponse]:
    memberships = await MembershipRepository(session).list_for_user(current_user.id)
    return [
        WorkspaceWithRoleResponse(
            id=membership.workspace.id,
            name=membership.workspace.name,
            slug=membership.workspace.slug,
            created_at=membership.workspace.created_at,
            role=membership.role,
        )
        for membership in memberships
    ]


@router.get("/{workspace_id}", response_model=WorkspaceWithRoleResponse)
async def get_workspace(context: ViewerContext) -> WorkspaceWithRoleResponse:
    return WorkspaceWithRoleResponse(
        id=context.workspace.id,
        name=context.workspace.name,
        slug=context.workspace.slug,
        created_at=context.workspace.created_at,
        role=context.membership.role,
    )


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def list_members(context: ViewerContext, session: SessionDep) -> list[MemberResponse]:
    memberships = await MembershipRepository(session).list_with_users(context.workspace.id)
    return [_member_response(membership) for membership in memberships]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    body: AddMemberRequest,
    context: ManagerContext,
    session: SessionDep,
) -> MemberResponse:
    if not can_manage_role(context.membership.role, body.role):
        raise errors.cannot_manage_role()
    user = await UserRepository(session).get_by_email(body.email.strip().lower())
    if user is None or not user.is_active:
        raise errors.user_not_found()
    memberships = MembershipRepository(session)
    if await memberships.get_membership(context.workspace.id, user.id) is not None:
        raise errors.member_already_exists()
    membership = await memberships.add(
        Membership(workspace_id=context.workspace.id, user_id=user.id, role=body.role)
    )
    await AuditLogRepository(session).record(
        action="member.added",
        resource_type="membership",
        resource_id=membership.id,
        workspace_id=context.workspace.id,
        actor_user_id=context.user.id,
        detail={"member_user_id": str(user.id), "role": body.role.value},
    )
    membership.user = user
    return _member_response(membership)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def change_member_role(
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    context: ManagerContext,
    session: SessionDep,
) -> MemberResponse:
    memberships = MembershipRepository(session)
    membership = await memberships.get_membership(context.workspace.id, user_id)
    if membership is None:
        raise errors.member_not_found()
    if not (
        can_manage_role(context.membership.role, membership.role)
        and can_manage_role(context.membership.role, body.role)
    ):
        raise errors.cannot_manage_role()
    if (
        membership.role is MembershipRole.OWNER
        and body.role is not MembershipRole.OWNER
        and await memberships.count_owners(context.workspace.id) == 1
    ):
        raise errors.last_owner()
    previous_role = membership.role
    membership.role = body.role
    await session.flush()
    await AuditLogRepository(session).record(
        action="member.role_changed",
        resource_type="membership",
        resource_id=membership.id,
        workspace_id=context.workspace.id,
        actor_user_id=context.user.id,
        detail={
            "member_user_id": str(user_id),
            "from_role": previous_role.value,
            "to_role": body.role.value,
        },
    )
    user = await UserRepository(session).get(user_id)
    assert user is not None  # noqa: S101 - FK guarantees the member's account exists
    membership.user = user
    return _member_response(membership)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: uuid.UUID,
    context: ManagerContext,
    session: SessionDep,
) -> Response:
    memberships = MembershipRepository(session)
    membership = await memberships.get_membership(context.workspace.id, user_id)
    if membership is None:
        raise errors.member_not_found()
    if not can_manage_role(context.membership.role, membership.role):
        raise errors.cannot_manage_role()
    if (
        membership.role is MembershipRole.OWNER
        and await memberships.count_owners(context.workspace.id) == 1
    ):
        raise errors.last_owner()
    await memberships.delete(membership)
    await AuditLogRepository(session).record(
        action="member.removed",
        resource_type="membership",
        workspace_id=context.workspace.id,
        actor_user_id=context.user.id,
        detail={"member_user_id": str(user_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
