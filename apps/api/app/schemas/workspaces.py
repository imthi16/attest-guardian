"""Request and response bodies for workspace and membership endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models.enums import MembershipRole

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$"


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN, max_length=100)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class WorkspaceWithRoleResponse(WorkspaceResponse):
    """A workspace as seen by one member, including their own role."""

    role: MembershipRole


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: MembershipRole
    joined_at: datetime


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.MEMBER


class UpdateMemberRoleRequest(BaseModel):
    role: MembershipRole
