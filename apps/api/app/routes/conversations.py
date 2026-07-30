"""Conversation endpoints under `/api/v1/workspaces/{workspace_id}/conversations`.

Asking a question requires `QUERY`, the same capability the one-shot answer
endpoint demands; the thread only adds persistence. Every route runs inside the
workspace context, so membership is proven and row-level security is bound
before any tenant row moves, and a conversation belonging to another tenant
answers 404 rather than 403.

Two ways to ask the same question:

* `POST /{id}/messages` returns the finished answer as JSON.
* `POST /{id}/messages/stream` returns Server-Sent Events, emitting each
  pipeline stage as it completes and the answer once. Both run the identical
  pipeline through the identical gates — only the reporting differs, so a client
  can never obtain a less-checked answer by choosing the streaming route.

Stage events carry a node name and nothing else. The answer arrives in one
`answer` event at the end: generation is extractive, so there is no partial text
that is safe to display, and a half-composed answer could show a claim whose
citation had not been verified.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.auth import errors
from app.auth.dependencies import SessionDep, get_app_settings
from app.auth.permissions import WorkspaceAction
from app.auth.workspace import RequireAction, WorkspaceContext
from app.config import Settings
from app.conversations.service import (
    ConversationNotFoundError,
    create_conversation,
    load_conversation,
    record_answer,
    record_question,
)
from app.db.models.conversations import MessageFeedback
from app.db.models.enums import FeedbackRating
from app.db.repositories.conversations import (
    ConversationRepository,
    MessageFeedbackRepository,
    MessageRepository,
)
from app.rag.config import RagConfig
from app.rag.retriever import HybridEvidenceRetriever
from app.rag.service import RagService
from app.reranking.service import RerankService, build_reranker
from app.retrieval.service import HybridRetrievalService, RetrievalConfig
from app.schemas.answer import AnswerResponse
from app.schemas.conversations import (
    AskRequest,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageResponse,
)

logger = logging.getLogger("app.conversations")

router = APIRouter(prefix="/workspaces/{workspace_id}/conversations", tags=["conversations"])

QuerierContext = Annotated[WorkspaceContext, Depends(RequireAction(WorkspaceAction.QUERY))]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def _build_service(session: SessionDep, settings: Settings) -> RagService:
    """Assemble the same pipeline the one-shot answer endpoint runs."""
    retrieval_service = HybridRetrievalService(
        session,
        rerank_service=RerankService(build_reranker(settings), threshold=settings.rerank_threshold)
        if settings.rerank_enabled
        else None,
        config=RetrievalConfig(
            rrf_k=settings.retrieval_rrf_k,
            candidate_limit=settings.retrieval_candidate_limit,
            top_k=settings.retrieval_top_k,
            rerank_enabled=settings.rerank_enabled,
            rerank_candidate_limit=settings.rerank_candidate_limit,
        ),
    )
    return RagService(
        session,
        retriever=HybridEvidenceRetriever(retrieval_service),
        config=RagConfig(
            top_k=settings.rag_top_k,
            max_evidence=settings.rag_max_evidence,
            min_evidence=settings.rag_min_evidence,
            min_evidence_score=settings.rag_min_evidence_score,
        ),
    )


def _clamped_top_k(requested: int | None, settings: Settings) -> int | None:
    """Never trust a caller's `top_k`; clamp it to the configured maximum."""
    return None if requested is None else min(requested, settings.rag_max_top_k)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: ConversationCreateRequest,
    context: QuerierContext,
    session: SessionDep,
) -> ConversationResponse:
    conversation = await create_conversation(
        session=session,
        workspace_id=context.workspace.id,
        actor_id=context.user.id,
        title=payload.title,
    )
    return ConversationResponse.of(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    context: QuerierContext,
    session: SessionDep,
) -> list[ConversationResponse]:
    conversations = await ConversationRepository(session, context.workspace.id).list_ordered()
    return [ConversationResponse.of(conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    context: QuerierContext,
    session: SessionDep,
) -> ConversationDetailResponse:
    try:
        conversation = await load_conversation(
            session=session,
            workspace_id=context.workspace.id,
            conversation_id=conversation_id,
        )
    except ConversationNotFoundError:
        raise errors.conversation_not_found() from None
    return ConversationDetailResponse(
        conversation=ConversationResponse.of(conversation),
        messages=[MessageResponse.of(message) for message in conversation.messages],
    )


@router.post("/{conversation_id}/messages", response_model=AnswerResponse)
async def ask(
    conversation_id: uuid.UUID,
    payload: AskRequest,
    context: QuerierContext,
    session: SessionDep,
    settings: SettingsDep,
) -> AnswerResponse:
    """Ask a question and persist both turns, returning the finished answer."""
    try:
        await record_question(
            session=session,
            workspace_id=context.workspace.id,
            conversation_id=conversation_id,
            question=payload.question,
        )
    except ConversationNotFoundError:
        raise errors.conversation_not_found() from None

    result = await _build_service(session, settings).answer(
        workspace_id=context.workspace.id,
        query=payload.question,
        actor_user_id=context.user.id,
        document_id=payload.document_id,
        top_k=_clamped_top_k(payload.top_k, settings),
    )
    await record_answer(
        session=session,
        workspace_id=context.workspace.id,
        conversation_id=conversation_id,
        result=result,
    )
    return AnswerResponse.from_result(result)


def _sse(event: str, data: dict[str, object]) -> str:
    """One Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.post("/{conversation_id}/messages/stream")
async def ask_streaming(
    conversation_id: uuid.UUID,
    payload: AskRequest,
    context: QuerierContext,
    session: SessionDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Ask a question, reporting each pipeline stage as it completes.

    The question is persisted before streaming begins, so a client that
    disconnects mid-run still leaves a record of what was asked; the answer is
    persisted only once the pipeline reaches a terminal result, so an abandoned
    run never stores an assistant turn implying an answer existed.

    A pipeline failure is reported as an `error` event rather than a broken
    connection: the response status is already `200` by the time streaming
    starts, so an exception would otherwise reach the client as a truncated
    stream it could not distinguish from a network drop.
    """
    try:
        await record_question(
            session=session,
            workspace_id=context.workspace.id,
            conversation_id=conversation_id,
            question=payload.question,
        )
    except ConversationNotFoundError:
        raise errors.conversation_not_found() from None

    service = _build_service(session, settings)
    top_k = _clamped_top_k(payload.top_k, settings)

    async def frames() -> AsyncIterator[str]:
        try:
            async for stage, result in service.answer_streaming(
                workspace_id=context.workspace.id,
                query=payload.question,
                actor_user_id=context.user.id,
                document_id=payload.document_id,
                top_k=top_k,
            ):
                if result is None:
                    yield _sse("stage", {"stage": stage})
                    continue
                message = await record_answer(
                    session=session,
                    workspace_id=context.workspace.id,
                    conversation_id=conversation_id,
                    result=result,
                )
                answer = AnswerResponse.from_result(result)
                yield _sse(
                    "answer",
                    {"message_id": str(message.id), **answer.model_dump(mode="json")},
                )
        except Exception:
            # The trace is safe to log; the client gets a stable code and no
            # internal detail, matching the error envelope elsewhere.
            logger.exception(
                "streamed answer failed",
                extra={"workspace_id": str(context.workspace.id)},
            )
            yield _sse(
                "error",
                {
                    "code": "answer_failed",
                    "message": "The answer could not be completed. Please try again.",
                },
            )

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            # Answers are tenant content: never cached, and never buffered by an
            # intermediary that would defeat the point of streaming.
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.put(
    "/{conversation_id}/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
)
async def submit_feedback(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    context: QuerierContext,
    session: SessionDep,
) -> FeedbackResponse:
    """Record or revise this reviewer's verdict on one answer.

    Idempotent per reviewer: submitting again updates their row rather than
    stacking duplicates, so the table holds current opinions and not a log of
    clicks. `PUT` rather than `POST` for the same reason.
    """
    conversation = await ConversationRepository(session, context.workspace.id).get(conversation_id)
    if conversation is None:
        raise errors.conversation_not_found()
    message = await MessageRepository(session).get_in_workspace(message_id, context.workspace.id)
    if message is None or message.conversation_id != conversation.id:
        raise errors.message_not_found()

    repository = MessageFeedbackRepository(session, context.workspace.id)
    existing = await repository.get_for_reviewer(message_id, context.user.id)
    rating = FeedbackRating(payload.rating)
    if existing is not None:
        existing.rating = rating
        existing.note = payload.note
        await session.flush()
        return FeedbackResponse.of(existing)

    created = await repository.add(
        MessageFeedback(
            workspace_id=context.workspace.id,
            message_id=message_id,
            reviewer_id=context.user.id,
            rating=rating,
            note=payload.note,
        )
    )
    return FeedbackResponse.of(created)


@router.get(
    "/{conversation_id}/messages/{message_id}/feedback",
    response_model=list[FeedbackResponse],
)
async def list_feedback(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    context: QuerierContext,
    session: SessionDep,
) -> list[FeedbackResponse]:
    conversation = await ConversationRepository(session, context.workspace.id).get(conversation_id)
    if conversation is None:
        raise errors.conversation_not_found()
    message = await MessageRepository(session).get_in_workspace(message_id, context.workspace.id)
    if message is None or message.conversation_id != conversation.id:
        raise errors.message_not_found()
    entries = await MessageFeedbackRepository(session, context.workspace.id).list_for_message(
        message_id
    )
    return [FeedbackResponse.of(entry) for entry in entries]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    context: QuerierContext,
    session: SessionDep,
) -> Response:
    """Delete a thread and its turns.

    Citations reference chunks with `ondelete=RESTRICT`, which protects cited
    *evidence* from disappearing under an answer — it does not prevent deleting
    the answer itself, and the cascade removes this conversation's citations
    with it. The evidence and its documents are untouched.
    """
    repository = ConversationRepository(session, context.workspace.id)
    conversation = await repository.get(conversation_id)
    if conversation is None:
        raise errors.conversation_not_found()
    await repository.delete(conversation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
