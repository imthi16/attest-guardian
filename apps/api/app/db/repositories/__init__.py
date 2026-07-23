"""Repositories: the only sanctioned data-access path; scoped ones enforce tenancy."""

from app.db.repositories.audit import AuditLogRepository
from app.db.repositories.base import Repository, WorkspaceScopedRepository
from app.db.repositories.chunks import ChunkRepository, LexicalMatch
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.embeddings import ChunkEmbeddingRepository, VectorMatch
from app.db.repositories.identity import (
    MembershipRepository,
    RefreshTokenRepository,
    UserRepository,
    WorkspaceRepository,
)

__all__ = [
    "AuditLogRepository",
    "ChunkEmbeddingRepository",
    "ChunkRepository",
    "DocumentRepository",
    "LexicalMatch",
    "MembershipRepository",
    "RefreshTokenRepository",
    "Repository",
    "UserRepository",
    "VectorMatch",
    "WorkspaceRepository",
    "WorkspaceScopedRepository",
]
