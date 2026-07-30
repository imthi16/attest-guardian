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


class AnswerDecision(enum.Enum):
    """The operational decision the policy reached for one answered query.

    Persisted alongside `AnswerStatus` because the two answer different
    questions and neither implies the other. Status says whether an answer was
    produced; this says what the platform decided to *do* about it. Three
    distinct decisions all surface as `ABSTAINED` — no usable evidence, a
    question that needs narrowing, and evidence that contradicts itself — and a
    stored thread that kept only the status could not tell a reader which of
    those happened, or that a human was asked to look.

    Mirrors the value set of `app.decision.types.DecisionOutcome`, which is kept
    separate so the decision policy never imports the ORM.
    """

    ANSWER = "answer"
    ANSWER_WITH_WARNING = "answer_with_warning"
    ASK_FOR_CLARIFICATION = "ask_for_clarification"
    ABSTAIN = "abstain"
    ESCALATE_FOR_REVIEW = "escalate_for_review"


class FeedbackRating(enum.Enum):
    """A reviewer's verdict on one assistant answer.

    Deliberately coarse. `INCORRECT` is kept separate from `UNHELPFUL` because
    the two mean different things for evaluation: an unhelpful answer may be
    correctly abstaining, while an incorrect one is a grounding failure worth
    investigating.
    """

    HELPFUL = "helpful"
    UNHELPFUL = "unhelpful"
    INCORRECT = "incorrect"


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


class IngestionStage(enum.Enum):
    """The furthest pipeline stage an ingestion job has reached.

    Every stage now does real work, and the worker advances through them in
    declaration order, so the progression is both observable and meaningful:
    a job reporting `EMBEDDING` really is being embedded.
    """

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    SCANNING = "scanning"
    PARSING = "parsing"
    OCR = "ocr"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
