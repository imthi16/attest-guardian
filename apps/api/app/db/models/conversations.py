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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceOwnedModel
from app.db.models.enums import AnswerStatus, ClaimVerdict, MessageRole, pg_enum

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
        order_by="Message.created_at",
    )


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn in a conversation, keeping all query representations."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    transliterated_content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))
    answer_status: Mapped[AnswerStatus | None] = mapped_column(
        pg_enum(AnswerStatus, "answer_status"),
    )

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
