"""Turning a question into a persisted conversation turn.

The RAG pipeline produces an answer; this module is what makes that answer part
of a durable thread. It writes three kinds of row for one question:

* the **user message**, keeping every representation of the query — verbatim
  original, normalized, and Tamil-script transliteration — so a Tanglish
  question can be re-run or re-indexed later without guessing what was meant;
* the **assistant message**, carrying the whole grounding verdict — the
  outcome, the operational decision and its reason, the calibrated confidence,
  and the abstention code — because a thread that kept only the outcome would
  read three different decisions as the same word;
* one **citation** and one **verification result** per claim, so the evidence
  behind an answer survives independently of the response that returned it.

A turn is atomic. The question is written before the pipeline runs and the answer
only from a terminal result, so a completed run stores both and a failed or
abandoned one stores neither — they share the request's transaction. An
abstention is not a failure: it is a real answer about the evidence and is stored
like any other outcome.

Both writes take the conversation's row lock. That serializes assignment of the
next `sequence` against a concurrent turn, and bumps the conversation's own
`updated_at` so the thread list orders by activity rather than creation.

Persisted text is tenant content: it is stored verbatim and never interpolated
into a prompt.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversations import Citation, Conversation, Message, VerificationResult
from app.db.models.enums import AnswerDecision, AnswerStatus, ClaimVerdict, MessageRole
from app.db.repositories.conversations import ConversationRepository
from app.language import detect_language
from app.language.processor import QueryProcessor
from app.rag.types import AtomicClaim, RagResult

# Fallback identity for the stored verdict. The trace names the verifier that
# actually ran, and that is what gets persisted; this is only for a result whose
# trace carries no name, so the column is never silently wrong about which
# verifier produced a verdict.
VERIFIER_NAME = "attest-claim-verifier"


def _persisted_verdict(verdict: object) -> ClaimVerdict:
    """Translate the pipeline's verdict into the persisted enum.

    The RAG layer keeps its own verdict vocabulary so it never imports the ORM,
    and the two value sets are documented as mirrors. This is the one place they
    meet, so it converts *by value* rather than through a hand-written table: a
    lookup table would silently mismap if either side gained a member, while
    this raises `ValueError` on anything unrecognised.
    """
    return ClaimVerdict(str(verdict))


def _persisted_status(outcome: object) -> AnswerStatus:
    """Translate the pipeline's grounding outcome into the persisted enum."""
    return AnswerStatus(str(outcome))


def _persisted_decision(decision: str) -> AnswerDecision:
    """Translate the policy's decision into the persisted enum.

    Converts by value for the same reason as the verdict above: the decision
    policy keeps its own vocabulary so it never imports the ORM, and a
    hand-written table would silently mismap if either side gained a member.
    """
    return AnswerDecision(decision)


def _touch(conversation: Conversation) -> None:
    """Move the thread to the top of the list by bumping its own timestamp.

    Inserting a `Message` does not update the parent row, and `updated_at` only
    changes when the conversation itself is written, so without this the "most
    recently updated first" ordering would really be creation order and a thread
    with a new answer would never move.
    """
    conversation.updated_at = datetime.now(UTC)


class ConversationNotFoundError(Exception):
    """No such conversation in this workspace (or it is another tenant's)."""


async def create_conversation(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    title: str | None,
) -> Conversation:
    """Start a thread. The title is caller-supplied text, stored verbatim."""
    conversation = Conversation(
        workspace_id=workspace_id,
        created_by=actor_id,
        title=title,
    )
    return await ConversationRepository(session, workspace_id).add(conversation)


async def load_conversation(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> Conversation:
    conversation = await ConversationRepository(session, workspace_id).get_with_messages(
        conversation_id
    )
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


async def record_question(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    question: str,
    processor: QueryProcessor | None = None,
) -> Message:
    """Persist the asked question with all of its language representations.

    Written before the pipeline runs, so a run that fails or is abandoned still
    leaves an honest record of what was asked.
    """
    repository = ConversationRepository(session, workspace_id)
    conversation = await repository.get_for_update(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError

    processed = (processor or QueryProcessor()).process(question)
    message = Message(
        conversation_id=conversation.id,
        sequence=await repository.next_sequence(conversation.id),
        role=MessageRole.USER,
        content=processed.original,
        normalized_content=processed.normalized,
        transliterated_content=processed.transliterated,
        language=processed.detection.language.value,
    )
    session.add(message)
    _touch(conversation)
    await session.flush()
    return message


async def record_answer(
    *,
    session: AsyncSession,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    result: RagResult,
) -> Message:
    """Persist the assistant turn with a citation and verdict per claim.

    Only called once the pipeline has produced a terminal result. An abstention
    is recorded like any other outcome — it is a real answer about the state of
    the evidence, and a thread that silently dropped it would misrepresent what
    the system did.
    """
    repository = ConversationRepository(session, workspace_id)
    conversation = await repository.get_for_update(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError

    answer = result.answer
    message = Message(
        conversation_id=conversation.id,
        sequence=await repository.next_sequence(conversation.id),
        role=MessageRole.ASSISTANT,
        content=answer.text,
        # Detected from the answer, not the query. The extractive answer is
        # composed from evidence that may be in a different language than the
        # question, and an abstention is a fixed English refusal — labelling
        # either with the query's language would make the stored provenance
        # describe something other than the content it sits on.
        language=detect_language(answer.text).language.value,
        answer_status=_persisted_status(answer.outcome),
        decision=_persisted_decision(answer.decision),
        decision_reason=answer.decision_reason or None,
        confidence=answer.confidence,
        abstention_reason=answer.abstention_reason,
    )
    session.add(message)
    await session.flush()

    verifier = result.trace.verifier or VERIFIER_NAME
    for claim in answer.claims:
        _add_claim_rows(session, message.id, claim, verifier=verifier)
    await session.flush()
    return message


def _add_claim_rows(
    session: AsyncSession,
    message_id: uuid.UUID,
    claim: AtomicClaim,
    *,
    verifier: str,
) -> None:
    """Write the citation and the verdict for one claim.

    The claim span is recorded against the claim's own text rather than an offset
    into the composed answer: composition may reorder or join claims, and a span
    that pointed into the final prose would silently drift if that changed.
    """
    citation = claim.citation
    session.add(
        Citation(
            message_id=message_id,
            chunk_id=citation.chunk_id,
            claim_text=claim.text,
            claim_start=0,
            claim_end=len(claim.text),
            quote_text=citation.quote,
            quote_start=citation.quote_char_start,
            quote_end=citation.quote_char_end,
            page_number=citation.page_number,
        )
    )
    session.add(
        VerificationResult(
            message_id=message_id,
            chunk_id=citation.chunk_id,
            claim_index=claim.index,
            claim_text=claim.text,
            verdict=_persisted_verdict(claim.verdict),
            confidence=claim.confidence,
            verifier=verifier,
        )
    )


__all__ = [
    "VERIFIER_NAME",
    "ConversationNotFoundError",
    "create_conversation",
    "load_conversation",
    "record_answer",
    "record_question",
]
