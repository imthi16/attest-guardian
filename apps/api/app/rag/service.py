"""The grounded-answer service: build state, run the graph, persist the trace.

This is the single entry point a route calls. It constructs the workspace-scoped
retriever, runs the typed LangGraph workflow, and records a non-sensitive audit
event describing *how* the answer was reached (counts, outcome, timings) without
persisting the query, evidence, or answer text.

Authorization is enforced upstream by the route dependency and the row-level
security binding, and again in the retrieval data layer; this service never
loosens that boundary.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.audit import AuditLogRepository
from app.observability.metrics import ANSWER_DURATION, ANSWERS, CLAIMS
from app.rag.config import RagConfig
from app.rag.generation import AnswerGenerator
from app.rag.graph import EvidenceRetriever, RagGraph
from app.rag.retriever import HybridEvidenceRetriever
from app.rag.state import RagState
from app.rag.types import RagResult, RagTrace
from app.rag.verification import ClaimVerifier
from app.retrieval.service import HybridRetrievalService

logger = logging.getLogger("app.rag")

AUDIT_ACTION = "rag.answer"
AUDIT_RESOURCE = "conversation"


class RagService:
    """Runs the grounded-answer pipeline for one authorized workspace query."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        retriever: EvidenceRetriever | None = None,
        generator: AnswerGenerator | None = None,
        verifier: ClaimVerifier | None = None,
        config: RagConfig | None = None,
    ) -> None:
        self._session = session
        self._config = config or RagConfig()
        resolved_retriever = retriever or HybridEvidenceRetriever(HybridRetrievalService(session))
        self._graph = RagGraph(
            resolved_retriever,
            generator=generator,
            verifier=verifier,
            config=self._config,
        )

    async def answer(
        self,
        *,
        workspace_id: uuid.UUID,
        query: str,
        actor_user_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
        language: str | None = None,
        top_k: int | None = None,
    ) -> RagResult:
        """Produce a grounded answer or a calibrated abstention."""
        resolved_top_k = top_k or self._config.top_k
        trace = RagTrace(
            workspace_id=workspace_id,
            detected_language="unknown",
            top_k=resolved_top_k,
        )
        state = RagState(
            workspace_id=workspace_id,
            query=query,
            top_k=resolved_top_k,
            document_id=document_id,
            language_filter=language,
            trace=trace,
        )

        start = time.perf_counter()
        terminal = await self._graph.run(state)
        terminal.trace.total_ms = (time.perf_counter() - start) * 1000

        await self._record(workspace_id, actor_user_id, terminal.trace, conversation_id)
        _observe(terminal)
        logger.info(
            "rag answer completed",
            extra={"workspace_id": str(workspace_id), "trace": terminal.trace.as_metadata()},
        )
        return RagResult(answer=terminal.to_answer(), trace=terminal.trace)

    async def answer_streaming(
        self,
        *,
        workspace_id: uuid.UUID,
        query: str,
        actor_user_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
        language: str | None = None,
        top_k: int | None = None,
    ) -> AsyncGenerator[tuple[str, RagResult | None], None]:
        """Yield each completed pipeline stage, then the finished result.

        Same pipeline and same gates as `answer`; only the reporting differs. A
        caller that stops consuming this iterator cancels the run — the audit
        event is written when the pipeline finishes, so an abandoned request
        leaves no record claiming an answer was produced.
        """
        resolved_top_k = top_k or self._config.top_k
        trace = RagTrace(
            workspace_id=workspace_id,
            detected_language="unknown",
            top_k=resolved_top_k,
        )
        state = RagState(
            workspace_id=workspace_id,
            query=query,
            top_k=resolved_top_k,
            document_id=document_id,
            language_filter=language,
            trace=trace,
        )

        start = time.perf_counter()
        async for stage, terminal in self._graph.run_streaming(state):
            if terminal is None:
                yield stage, None
                continue
            terminal.trace.total_ms = (time.perf_counter() - start) * 1000
            await self._record(workspace_id, actor_user_id, terminal.trace, conversation_id)
            logger.info(
                "rag answer completed",
                extra={
                    "workspace_id": str(workspace_id),
                    "streamed": True,
                    "trace": terminal.trace.as_metadata(),
                },
            )
            yield stage, RagResult(answer=terminal.to_answer(), trace=terminal.trace)

    async def _record(
        self,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        trace: RagTrace,
        conversation_id: uuid.UUID | None = None,
    ) -> None:
        """Append an audit event carrying only the non-sensitive trace.

        `resource_id` is the conversation when the answer belongs to a thread.
        The event already claims `resource_type: conversation`, so leaving it null
        made it impossible to tell which thread produced a grounding decision
        once a workspace had more than one.
        """
        await AuditLogRepository(self._session).record(
            action=AUDIT_ACTION,
            resource_type=AUDIT_RESOURCE,
            resource_id=conversation_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            detail=trace.as_metadata(),
        )


def _observe(terminal: RagState) -> None:
    """Record the outcome of one answer.

    The decision is the label rather than the outcome, because three different
    decisions all report `abstained` and an operator needs to tell "no evidence"
    from "the evidence contradicts itself" — the second is a data problem
    somebody has to look at, the first usually is not.

    Claim verdicts are counted here and nowhere else: unsupported and
    contradicted claims are dropped before the answer, so nothing downstream ever
    sees them. A rise in dropped claims is retrieval degrading while the answers
    still look fine.
    """
    trace = terminal.trace
    ANSWERS.increment(decision=terminal.decision, outcome=str(trace.outcome))
    if trace.total_ms is not None:
        ANSWER_DURATION.observe(trace.total_ms / 1000)
    CLAIMS.increment(len(terminal.claims), verdict="supported")
    for verdict, count in (
        ("unsupported", trace.unsupported_claim_count),
        ("contradicted", trace.contradicted_claim_count),
        ("partial", trace.partial_claim_count),
    ):
        if count:
            CLAIMS.increment(count, verdict=verdict)
