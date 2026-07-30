"""Unit tests for RagService: it runs the graph and records a safe audit trace.

A fake audit repository captures what would be persisted so we can assert the
service records the non-sensitive trace (never the query, evidence, or answer
text) and drives the graph to a terminal answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.rag import service as service_module
from app.rag.config import RagConfig
from app.rag.service import RagService
from app.rag.types import AnswerOutcome, EvidencePassage

WORKSPACE = uuid.UUID(int=1)
ACTOR = uuid.UUID(int=2)


def _passage(text: str, order: int) -> EvidencePassage:
    return EvidencePassage(
        chunk_id=uuid.UUID(int=100 + order),
        document_id=uuid.UUID(int=9),
        document_version_id=uuid.UUID(int=8),
        content=text,
        page_number=order + 1,
        section=None,
        char_start=0,
        char_end=len(text),
        language="eng",
        ocr_engine=None,
        ocr_confidence=None,
        fused_score=0.9,
        rerank_score=0.85,
        order=order,
    )


class FakeRetriever:
    def __init__(self, passages: Sequence[EvidencePassage]) -> None:
        self._passages = tuple(passages)

    async def retrieve(self, *, workspace_id, query, top_k, document_id, language):  # type: ignore[no-untyped-def]
        return self._passages, {"returned_count": len(self._passages)}


class FakeAuditRepo:
    def __init__(self, session: object) -> None:
        self.session = session
        self.records: list[dict[str, object]] = []

    async def record(self, **kwargs: object) -> None:
        self.records.append(kwargs)


def _install_audit(monkeypatch) -> list[FakeAuditRepo]:  # type: ignore[no-untyped-def]
    created: list[FakeAuditRepo] = []

    def factory(session: object) -> FakeAuditRepo:
        repo = FakeAuditRepo(session)
        created.append(repo)
        return repo

    monkeypatch.setattr(service_module, "AuditLogRepository", factory)
    return created


async def test_service_answers_and_records_safe_trace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    audits = _install_audit(monkeypatch)
    evidence = [_passage("The invoice payment is due within thirty days of receipt.", 0)]
    service = RagService(
        session=object(),  # type: ignore[arg-type]
        retriever=FakeRetriever(evidence),
        config=RagConfig(),
    )
    result = await service.answer(
        workspace_id=WORKSPACE,
        query="invoice payment due date",
        actor_user_id=ACTOR,
    )

    assert result.answer.outcome is AnswerOutcome.ANSWERED
    assert result.answer.claims
    assert result.trace.total_ms >= 0.0

    assert len(audits) == 1 and len(audits[0].records) == 1
    recorded = audits[0].records[0]
    assert recorded["action"] == service_module.AUDIT_ACTION
    assert recorded["workspace_id"] == WORKSPACE
    assert recorded["actor_user_id"] == ACTOR
    # The persisted detail is the non-sensitive trace, not query/answer text.
    detail = str(recorded["detail"])
    assert "invoice payment due date" not in detail
    assert "thirty days" not in detail


async def test_service_abstains_and_still_records(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    audits = _install_audit(monkeypatch)
    service = RagService(
        session=object(),  # type: ignore[arg-type]
        retriever=FakeRetriever([]),
        config=RagConfig(),
    )
    result = await service.answer(workspace_id=WORKSPACE, query="anything at all")

    assert result.answer.outcome is AnswerOutcome.ABSTAINED
    assert result.answer.claims == ()
    assert audits[0].records[0]["detail"]["abstained"] is True  # type: ignore[index]


async def test_streaming_reports_real_stages_then_one_final_result(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Stage events come from the graph's own transitions, not from the caller.

    The point of streaming these is that a client showing "retrieving" is seeing
    that the retrieve node actually finished, so the names must be the graph's
    node names and the answer must arrive exactly once, at the end.
    """
    audits = _install_audit(monkeypatch)
    evidence = [_passage("The invoice payment is due within thirty days of receipt.", 0)]
    service = RagService(
        session=object(),  # type: ignore[arg-type]
        retriever=FakeRetriever(evidence),
        config=RagConfig(),
    )

    stages: list[str] = []
    finals = []
    async for stage, result in service.answer_streaming(
        workspace_id=WORKSPACE,
        query="invoice payment due date",
        actor_user_id=ACTOR,
    ):
        stages.append(stage)
        if result is not None:
            finals.append(result)

    # Every answering stage the pipeline really runs, in order, then the result.
    assert stages[:6] == ["authorize", "analyze", "retrieve", "generate", "verify", "decide"]
    assert "compose" in stages
    assert stages[-1] == "final"
    # A partial state is never a usable answer, so only the terminal item has one.
    assert len(finals) == 1
    assert finals[0].answer.outcome is AnswerOutcome.ANSWERED
    assert finals[0].answer.claims

    # Streaming must not change what is audited, nor audit twice.
    assert len(audits[0].records) == 1
    assert "invoice payment due date" not in str(audits[0].records[0]["detail"])


async def test_streaming_matches_the_non_streaming_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Same pipeline, same gates: only the reporting differs."""
    _install_audit(monkeypatch)
    evidence = [_passage("Termination requires ninety days written notice.", 0)]

    def build() -> RagService:
        return RagService(
            session=object(),  # type: ignore[arg-type]
            retriever=FakeRetriever(evidence),
            config=RagConfig(),
        )

    direct = await build().answer(workspace_id=WORKSPACE, query="termination notice period")
    streamed = [
        result
        async for _, result in build().answer_streaming(
            workspace_id=WORKSPACE, query="termination notice period"
        )
        if result is not None
    ][0]

    assert streamed.answer.outcome is direct.answer.outcome
    assert streamed.answer.text == direct.answer.text
    assert streamed.answer.decision == direct.answer.decision
    assert [claim.text for claim in streamed.answer.claims] == [
        claim.text for claim in direct.answer.claims
    ]


async def test_streaming_abstention_reaches_the_abstain_node(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An insufficient-evidence run must stream the gate it actually took."""
    audits = _install_audit(monkeypatch)
    service = RagService(
        session=object(),  # type: ignore[arg-type]
        retriever=FakeRetriever([]),
        config=RagConfig(),
    )

    stages = []
    final = None
    async for stage, result in service.answer_streaming(workspace_id=WORKSPACE, query="anything"):
        stages.append(stage)
        if result is not None:
            final = result

    assert "abstain" in stages
    assert "compose" not in stages
    assert final is not None
    assert final.answer.outcome is AnswerOutcome.ABSTAINED
    assert audits[0].records[0]["detail"]["abstained"] is True  # type: ignore[index]


async def test_abandoning_the_stream_records_no_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Cancellation must not leave an audit event claiming an answer happened.

    A client that navigates away stops consuming the iterator partway. The audit
    event is written with the terminal state, so an abandoned run writes nothing.
    """
    audits = _install_audit(monkeypatch)
    evidence = [_passage("The invoice payment is due within thirty days of receipt.", 0)]
    service = RagService(
        session=object(),  # type: ignore[arg-type]
        retriever=FakeRetriever(evidence),
        config=RagConfig(),
    )

    stream = service.answer_streaming(workspace_id=WORKSPACE, query="invoice payment due date")
    first = await anext(stream)
    await stream.aclose()

    assert first == ("authorize", None)
    assert audits == [] or all(not repo.records for repo in audits)
