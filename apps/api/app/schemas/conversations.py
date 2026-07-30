"""Request and response bodies for the conversation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models.conversations import Conversation, Message, MessageFeedback


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, conversation: Conversation) -> ConversationResponse:
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class CitationRecordResponse(BaseModel):
    """One persisted evidence span behind a claim in an answer."""

    chunk_id: uuid.UUID
    claim_text: str
    quote_text: str
    quote_start: int
    quote_end: int
    page_number: int | None


class ClaimRecordResponse(BaseModel):
    """One persisted claim verdict, so a stored answer stays auditable."""

    claim_index: int
    claim_text: str
    verdict: str
    confidence: float
    verifier: str


class MessageResponse(BaseModel):
    """One turn. Query representations are exposed for user turns only.

    `content` is tenant text — a question someone typed or an answer composed
    from their documents. Clients must render it as text, never as markup.
    """

    id: uuid.UUID
    role: str
    content: str
    language: str | None
    normalized_content: str | None
    transliterated_content: str | None
    answer_status: str | None
    created_at: datetime
    citations: list[CitationRecordResponse]
    claims: list[ClaimRecordResponse]

    @classmethod
    def of(cls, message: Message) -> MessageResponse:
        return cls(
            id=message.id,
            role=message.role.value,
            content=message.content,
            language=message.language,
            normalized_content=message.normalized_content,
            transliterated_content=message.transliterated_content,
            answer_status=message.answer_status.value if message.answer_status else None,
            created_at=message.created_at,
            citations=[
                CitationRecordResponse(
                    chunk_id=citation.chunk_id,
                    claim_text=citation.claim_text,
                    quote_text=citation.quote_text,
                    quote_start=citation.quote_start,
                    quote_end=citation.quote_end,
                    page_number=citation.page_number,
                )
                for citation in message.citations
            ],
            claims=[
                ClaimRecordResponse(
                    claim_index=claim.claim_index,
                    claim_text=claim.claim_text,
                    verdict=claim.verdict.value,
                    confidence=claim.confidence,
                    verifier=claim.verifier,
                )
                for claim in sorted(
                    message.verification_results,
                    key=lambda result: result.claim_index,
                )
            ],
        )


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]


class AskRequest(BaseModel):
    """A question against a workspace's evidence, optionally scoped."""

    question: str = Field(min_length=1, max_length=2000)
    document_id: uuid.UUID | None = None
    top_k: int | None = Field(default=None, ge=1)


class FeedbackRequest(BaseModel):
    """A reviewer's verdict on one answer, with optional free-text detail."""

    rating: str = Field(pattern="^(helpful|unhelpful|incorrect)$")
    note: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: str
    note: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, feedback: MessageFeedback) -> FeedbackResponse:
        return cls(
            id=feedback.id,
            message_id=feedback.message_id,
            rating=feedback.rating.value,
            note=feedback.note,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
        )
