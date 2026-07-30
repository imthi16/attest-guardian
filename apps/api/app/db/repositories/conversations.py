"""Workspace-scoped repositories for conversations, messages, and feedback.

Conversations and feedback are tenant-owned and go through
`WorkspaceScopedRepository`, so every query carries the workspace filter and
row-level security fences them again. Messages, citations, and verification
results are reached *through* their conversation rather than being scoped
directly: they carry no `workspace_id` of their own, so the only safe way to
load one is to prove the owning conversation belongs to this workspace first.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.db.models.conversations import (
    Citation,
    Conversation,
    Message,
    MessageFeedback,
    VerificationResult,
)
from app.db.models.enums import FeedbackRating
from app.db.repositories.base import Repository, WorkspaceScopedRepository


class ConversationRepository(WorkspaceScopedRepository[Conversation]):
    model = Conversation

    async def list_ordered(self) -> Sequence[Conversation]:
        """Most recently updated first: the thread a caller wants is the last one."""
        statement = (
            select(Conversation)
            .where(Conversation.workspace_id == self.workspace_id)
            .order_by(Conversation.updated_at.desc())
        )
        result = await self._session.scalars(statement)
        return result.all()

    async def get_for_update(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Load a conversation holding its row lock for the rest of the transaction.

        Adding a turn takes this lock: it serializes assignment of the next
        `sequence` (two concurrent turns would otherwise compute the same number
        and collide on the unique constraint) and it is the row whose
        `updated_at` has to move so the thread list reflects recent activity.
        """
        statement = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == self.workspace_id,
            )
            .with_for_update()
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def next_sequence(self, conversation_id: uuid.UUID) -> int:
        """The next turn position. Call while holding the conversation's lock."""
        statement = select(func.coalesce(func.max(Message.sequence), -1) + 1).where(
            Message.conversation_id == conversation_id
        )
        return await self._session.scalar(statement) or 0

    async def count_messages(self, conversation_id: uuid.UUID) -> int:
        """How many turns a thread holds, for the deletion audit detail."""
        statement = (
            select(func.count())
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.workspace_id == self.workspace_id,
            )
        )
        return await self._session.scalar(statement) or 0

    async def get_with_messages(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Load a conversation and its turns, with citations and claims attached.

        Eager-loads the whole thread so rendering it is one round trip rather
        than one per message. The workspace filter is applied to the
        conversation, which is what makes the nested rows safe to read.

        Each citation's chunk comes with it, because a citation stores only a
        `chunk_id` while resolving one needs the version that chunk belongs to.
        Loading it here rather than on access keeps that a single query and means
        serializing a thread cannot fail on a lazy load outside the session.
        """
        statement = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == self.workspace_id,
            )
            .options(
                selectinload(Conversation.messages)
                .selectinload(Message.citations)
                .selectinload(Citation.chunk),
                selectinload(Conversation.messages).selectinload(Message.verification_results),
            )
        )
        result = await self._session.scalars(statement)
        return result.first()


class MessageRepository(Repository[Message]):
    """Messages are reached through a workspace-checked conversation."""

    model = Message

    async def get_in_workspace(
        self,
        message_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Message | None:
        """Load a message only if its conversation belongs to this workspace.

        A message id from another tenant resolves to `None` and is therefore
        indistinguishable from one that does not exist.
        """
        statement = (
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.id == message_id,
                Conversation.workspace_id == workspace_id,
            )
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def list_for_conversation(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Sequence[Message]:
        """Turns of one conversation, oldest first, fenced by workspace.

        The workspace is a required argument and enforced in the query: this
        repository is the tenant boundary, so accepting a bare conversation id
        would hand another tenant's questions, answers, and citations to any
        caller that guessed one.
        """
        statement = (
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
            .order_by(Message.sequence, Message.created_at)
            .options(
                selectinload(Message.citations).selectinload(Citation.chunk),
                selectinload(Message.verification_results),
            )
        )
        result = await self._session.scalars(statement)
        return result.all()


class CitationRepository(Repository[Citation]):
    model = Citation


class VerificationResultRepository(Repository[VerificationResult]):
    model = VerificationResult


class MessageFeedbackRepository(WorkspaceScopedRepository[MessageFeedback]):
    model = MessageFeedback

    async def upsert(
        self,
        *,
        message_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        rating: FeedbackRating,
        note: str | None,
    ) -> MessageFeedback:
        """Record or revise this reviewer's verdict in one statement.

        `ON CONFLICT DO UPDATE` rather than read-then-write: two concurrent
        first-time submissions would both see no existing row and both insert,
        and the unique `(message_id, reviewer_id)` constraint would turn one of
        them into a 500 on an endpoint that promises idempotent revision.

        `updated_at` is set explicitly because `onupdate` only fires on an ORM
        flush, not on a conflict resolved inside the database.
        """
        now = datetime.now(UTC)
        statement = (
            pg_insert(MessageFeedback)
            .values(
                workspace_id=self.workspace_id,
                message_id=message_id,
                reviewer_id=reviewer_id,
                rating=rating,
                note=note,
            )
            .on_conflict_do_update(
                index_elements=[MessageFeedback.message_id, MessageFeedback.reviewer_id],
                set_={"rating": rating, "note": note, "updated_at": now},
            )
            .returning(MessageFeedback)
        )
        result = await self._session.scalars(statement)
        feedback = result.one()
        # The row was written by a statement rather than through the identity
        # map, so refresh before anything reads server-generated columns.
        await self._session.refresh(feedback)
        return feedback

    async def get_for_reviewer(
        self,
        message_id: uuid.UUID,
        reviewer_id: uuid.UUID,
    ) -> MessageFeedback | None:
        statement = select(MessageFeedback).where(
            MessageFeedback.workspace_id == self.workspace_id,
            MessageFeedback.message_id == message_id,
            MessageFeedback.reviewer_id == reviewer_id,
        )
        result = await self._session.scalars(statement)
        return result.first()

    async def list_for_message(self, message_id: uuid.UUID) -> Sequence[MessageFeedback]:
        statement = (
            select(MessageFeedback)
            .where(
                MessageFeedback.workspace_id == self.workspace_id,
                MessageFeedback.message_id == message_id,
            )
            .order_by(MessageFeedback.created_at)
        )
        result = await self._session.scalars(statement)
        return result.all()


__all__ = [
    "CitationRepository",
    "ConversationRepository",
    "MessageFeedbackRepository",
    "MessageRepository",
    "VerificationResultRepository",
]
