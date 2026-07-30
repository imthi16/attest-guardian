"""Serialization of a stored turn, without a database.

The interesting property is the pairing: claims are returned sorted by
`claim_index` while citations come out of an unordered relationship, so a client
must be able to match the two on a recorded association rather than on list
position. These build the ORM objects in memory — nothing here is flushed — so
the mapping is tested at the layer that produces it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models.conversations import Citation, Message, VerificationResult
from app.db.models.documents import Chunk
from app.db.models.enums import AnswerDecision, AnswerStatus, ClaimVerdict, MessageRole
from app.schemas.conversations import MessageResponse

VERSION_ID = uuid.uuid4()


def make_citation(claim_index: int, *, quote: str) -> Citation:
    citation = Citation(
        message_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        claim_index=claim_index,
        claim_text=f"Claim {claim_index}.",
        claim_start=0,
        claim_end=9,
        quote_text=quote,
        quote_start=0,
        quote_end=len(quote),
        page_number=claim_index + 1,
    )
    citation.chunk = Chunk(document_version_id=VERSION_ID)
    return citation


def make_verdict(claim_index: int) -> VerificationResult:
    return VerificationResult(
        message_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        claim_index=claim_index,
        claim_text=f"Claim {claim_index}.",
        verdict=ClaimVerdict.SUPPORTED,
        confidence=0.9,
        verifier="entailment-v1",
    )


def make_answer(
    citations: list[Citation],
    verdicts: list[VerificationResult],
) -> Message:
    message = Message(
        conversation_id=uuid.uuid4(),
        sequence=1,
        role=MessageRole.ASSISTANT,
        content="- Claim 0.\n- Claim 1.",
        language="eng",
        answer_status=AnswerStatus.ANSWERED,
        decision=AnswerDecision.ANSWER,
        decision_reason="well-supported by cited evidence",
        confidence=0.9,
    )
    message.id = uuid.uuid4()
    message.created_at = datetime.now(UTC)
    message.citations = citations
    message.verification_results = verdicts
    return message


def test_a_citation_carries_the_index_of_the_claim_it_supports() -> None:
    """Otherwise a multi-claim answer can file evidence under the wrong claim.

    Both relationships are handed over in reversed order here, standing in for a
    database free to return rows however it likes: the response must still let a
    client put quote 0 under claim 0.
    """
    citations = [make_citation(1, quote="second"), make_citation(0, quote="first")]
    verdicts = [make_verdict(1), make_verdict(0)]

    response = MessageResponse.of(make_answer(citations, verdicts))

    by_claim = {citation.claim_index: citation.quote_text for citation in response.citations}
    assert by_claim == {0: "first", 1: "second"}
    assert [claim.claim_index for claim in response.claims] == [0, 1]
    # Both lists are ordered the same way, so reading them in parallel agrees
    # with matching them on the index.
    assert [citation.claim_index for citation in response.citations] == [0, 1]


def test_a_citation_exposes_its_version_so_it_stays_resolvable() -> None:
    response = MessageResponse.of(make_answer([make_citation(0, quote="first")], [make_verdict(0)]))

    assert response.citations[0].document_version_id == VERSION_ID


def test_one_claim_may_not_collect_two_citations() -> None:
    """The pairing is a database invariant, not only a serialization detail."""
    constraints = {
        constraint.name
        for constraint in Citation.__table__.constraints  # type: ignore[attr-defined]
    }
    assert "uq_citations_message_id_claim_index" in constraints
