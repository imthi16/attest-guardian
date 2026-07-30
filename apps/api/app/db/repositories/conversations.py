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

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.conversations import (
    Citation,
    Conversation,
    Message,
    MessageFeedback,
    VerificationResult,
)
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

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
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
