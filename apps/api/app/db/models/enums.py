"""Enumerated value sets stored as native PostgreSQL enum types."""

import enum

import sqlalchemy as sa


def pg_enum(enum_cls: type[enum.Enum], name: str) -> sa.Enum:
    """Build a named native enum column type that stores member values."""
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
    )


class MembershipRole(enum.Enum):
    """Workspace-scoped authorization role."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class DocumentStatus(enum.Enum):
    """Ingestion lifecycle state of a document."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class MessageRole(enum.Enum):
    """Author role of a conversation message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AnswerStatus(enum.Enum):
    """Grounding outcome of an assistant message."""

    ANSWERED = "answered"
    PARTIAL = "partial"
    ABSTAINED = "abstained"


class ClaimVerdict(enum.Enum):
    """Verification outcome for one atomic claim."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    AMBIGUOUS = "ambiguous"


class IngestionStatus(enum.Enum):
    """Lifecycle state of an asynchronous ingestion job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
