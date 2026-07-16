"""Repositories: the only sanctioned data-access path; scoped ones enforce tenancy."""

from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.base import Repository, WorkspaceScopedRepository
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.identity import (
    MembershipRepository,
    UserRepository,
    WorkspaceRepository,
)

__all__ = [
    "AuditLogRepository",
    "DocumentRepository",
    "MembershipRepository",
    "Repository",
    "UserRepository",
    "WorkspaceRepository",
    "WorkspaceScopedRepository",
]
