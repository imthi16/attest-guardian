"""Conversations, messages, citations, and claim verification results.

Citations reference chunks with `ondelete=RESTRICT`: cited evidence may not be
deleted while an answer depends on it. Deleting a cited document therefore
requires explicitly resolving its citations first.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceOwnedModel
from app.db.models.enums import (
    AnswerDecision,
    AnswerStatus,
    ClaimVerdict,
    FeedbackRating,
    MessageRole,
    pg_enum,
)

if TYPE_CHECKING:
    from app.db.models.documents import Chunk


class Conversation(WorkspaceOwnedModel):
    """A query thread scoped to one workspace."""

    __tablename__ = "conversations"

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    title: Mapped[str | None] = mapped_column(String(500))

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        # Ordered by the explicit turn sequence, not by timestamp: a question and
        # its answer are written close together and `now()` is transaction-start
        # time in PostgreSQL, so timestamps can tie and SQL would then be free to
        # return the answer before the question that produced it.
        order_by="Message.sequence",
    )


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn in a conversation, keeping all query representations.

    An assistant turn stores the whole grounding verdict, not just its status:
    the decision, the human-readable reason behind it, the calibrated
    confidence, and the abstention code. Without those, reloading a thread
    degrades what the answer said — three different decisions all read as
    `abstained`, and a withheld answer becomes indistinguishable from an absent
    one. All four are null on a user turn, which has no verdict of its own.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        UniqueConstraint("conversation_id", "sequence"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    # Position within the thread. Explicit because `created_at` cannot order
    # turns written in one transaction: PostgreSQL's `now()` is transaction-start
    # time, so a question and its answer tie on it.
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    transliterated_content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))
    answer_status: Mapped[AnswerStatus | None] = mapped_column(
        pg_enum(AnswerStatus, "answer_status"),
    )
    decision: Mapped[AnswerDecision | None] = mapped_column(
        pg_enum(AnswerDecision, "answer_decision"),
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    # A stable machine code (`insufficient_evidence`, `unauthorized`, or the
    # decision that withheld the answer) rather than an enum: it draws from two
    # vocabularies, so constraining it to one would reject valid values.
    abstention_reason: Mapped[str | None] = mapped_column(String(100))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list["Citation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )
    verification_results: Mapped[list["VerificationResult"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class Citation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Links one claim span in an answer to one supporting evidence span."""

    __tablename__ = "citations"
    __table_args__ = (
        CheckConstraint("claim_end > claim_start", name="claim_span_positive"),
        CheckConstraint("quote_end > quote_start", name="quote_span_positive"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="RESTRICT"),
        index=True,
    )
    claim_text: Mapped[str] = mapped_column(Text)
    claim_start: Mapped[int] = mapped_column(Integer)
    claim_end: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text)
    quote_start: Mapped[int] = mapped_column(Integer)
    quote_end: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)

    message: Mapped[Message] = relationship(back_populates="citations")
    chunk: Mapped["Chunk"] = relationship()


class VerificationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The verdict for one atomic claim extracted from an assistant message."""

    __tablename__ = "verification_results"
    __table_args__ = (
        UniqueConstraint("message_id", "claim_index"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"),
    )
    claim_index: Mapped[int] = mapped_column(Integer)
    claim_text: Mapped[str] = mapped_column(Text)
    verdict: Mapped[ClaimVerdict] = mapped_column(pg_enum(ClaimVerdict, "claim_verdict"))
    confidence: Mapped[float] = mapped_column(Float)
    verifier: Mapped[str] = mapped_column(String(100))

    message: Mapped[Message] = relationship(back_populates="verification_results")


class MessageFeedback(WorkspaceOwnedModel):
    """One reviewer's verdict on one assistant message.

    Unique per message and reviewer, so submitting again revises that person's
    verdict instead of stacking duplicates — the row is the reviewer's current
    opinion, not an append-only log of clicks.

    `note` is reviewer-authored free text. It is tenant content like any other:
    stored verbatim, never interpolated into a prompt, and rendered as text.
    """

    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "reviewer_id"),)

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    rating: Mapped[FeedbackRating] = mapped_column(pg_enum(FeedbackRating, "feedback_rating"))
    note: Mapped[str | None] = mapped_column(Text)

    message: Mapped[Message] = relationship()
