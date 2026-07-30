"""Running the real pipeline over the labelled datasets.

The harness is deliberately thin: it wires the *production* retriever protocol,
graph, generator, verifier, decision policy, and citation resolver to synthetic
evidence and records what they did. Nothing is reimplemented here, because a
harness that scored a copy of the pipeline would measure the copy.

What it substitutes is the data layer, and only the data layer. A
:class:`CorpusRetriever` reads passages from the fixed corpus instead of
PostgreSQL, which is what makes the evaluation deterministic, offline, and free
of tenant documents. That substitution has a consequence worth stating plainly:
the isolation numbers here measure whether the *pipeline* ever emits content
outside what retrieval authorized — not whether the repository layer and
row-level security scope a query correctly. Those are proven against a real
database in the integration suite, and neither check substitutes for the other.

Timing is measured with a monotonic clock around each run. It reflects this
machine and this fake retriever, so it is a regression signal — a change that
doubles the pipeline's own work shows up — and not a production latency figure.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.citations.resolver import CitationResolver
from app.citations.types import ChunkProvenance, CitationError, CitationReference
from app.evaluation.datasets import CorpusChunk, EvaluationDatasets, IsolationCase, QueryCase
from app.evaluation.metrics import CostAccount
from app.language import match_tokens, normalize_for_match
from app.rag.config import RagConfig
from app.rag.graph import RagGraph
from app.rag.state import RagState
from app.rag.types import AnswerOutcome, EvidencePassage, RagTrace
from app.safety import assess_text

# Stable synthetic identifiers. A chunk id is derived from its dataset key so a
# failure names the passage a reader can look up, rather than a random UUID.
_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def chunk_uuid(chunk_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, chunk_id)


def workspace_uuid(workspace: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"workspace:{workspace}")


def tokens(text: str) -> set[str]:
    """Distinct match tokens, with combining marks kept on their base letter.

    Uses the shared tokenizer rather than a local regex, because the obvious
    ``[^\\W_]+`` shatters every Tamil word into bare consonants and would make
    two unrelated Tamil passages look half-identical — a measurement artefact
    that would show up as excellent Tamil retrieval.
    """
    return match_tokens(text)


def overlap(query: str, text: str) -> float:
    """Share of the query's tokens the passage contains.

    A stand-in for the hybrid retriever, not a model of it. It exists so the
    ranking is deterministic and reproducible on any checkout; the absolute
    retrieval numbers are therefore a floor for the real system rather than a
    prediction of it.
    """
    query_tokens = tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & tokens(text)) / len(query_tokens)


class CorpusRetriever:
    """Serves the fixed corpus for exactly one workspace.

    The workspace filter is applied here because there is no database to apply
    it. It stands in for the repository scoping, so what the pipeline downstream
    can be held to is that it never emits anything this method did not return.
    """

    def __init__(self, datasets: EvaluationDatasets, workspace: str) -> None:
        self._chunks = datasets.workspace_corpus(workspace)
        self._workspace = workspace

    async def retrieve(
        self,
        *,
        workspace_id: uuid.UUID,
        query: str,
        top_k: int,
        document_id: uuid.UUID | None,
        language: str | None,
    ) -> tuple[Sequence[EvidencePassage], dict[str, object]]:
        del workspace_id, document_id, language  # scoping is the constructor's job here
        scored = [
            (score, chunk) for chunk in self._chunks if (score := overlap(query, chunk.text)) > 0.0
        ]
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        passages = [
            _passage(chunk, score=score, order=order)
            for order, (score, chunk) in enumerate(scored[:top_k])
        ]
        return passages, {"returned_count": len(passages)}


def _passage(chunk: CorpusChunk, *, score: float, order: int) -> EvidencePassage:
    return EvidencePassage(
        chunk_id=chunk_uuid(chunk.chunk_id),
        document_id=chunk_uuid(chunk.document),
        document_version_id=chunk_uuid(f"{chunk.document}:v1"),
        content=chunk.text,
        page_number=chunk.page_number,
        section=chunk.section,
        char_start=0,
        char_end=len(chunk.text),
        language=chunk.language,
        ocr_engine=chunk.ocr_engine,
        ocr_confidence=chunk.ocr_confidence,
        fused_score=min(1.0, score),
        rerank_score=min(1.0, score),
        order=order,
        rerank_raw_score=min(1.0, score),
    )


class CorpusProvenanceReader:
    """Reads provenance for the citation resolver, scoped to one workspace.

    Returning ``None`` for another workspace's chunk is what the real reader
    does, and it is what lets a resolved citation prove that the answer's
    evidence was authorized rather than merely plausible.
    """

    def __init__(self, datasets: EvaluationDatasets, workspace: str) -> None:
        self._by_uuid = {
            chunk_uuid(chunk.chunk_id): chunk for chunk in datasets.workspace_corpus(workspace)
        }

    async def get_provenance(self, chunk_id: uuid.UUID) -> ChunkProvenance | None:
        chunk = self._by_uuid.get(chunk_id)
        if chunk is None:
            return None
        return ChunkProvenance(
            chunk_id=chunk_uuid(chunk.chunk_id),
            document_id=chunk_uuid(chunk.document),
            document_title=chunk.document,
            document_version_id=chunk_uuid(f"{chunk.document}:v1"),
            version_number=1,
            chunk_index=0,
            content=chunk.text,
            page_number=chunk.page_number,
            section=chunk.section,
            language=chunk.language,
            char_start=0,
            char_end=len(chunk.text),
            ocr_engine=chunk.ocr_engine,
            ocr_confidence=chunk.ocr_confidence,
        )


@dataclass(frozen=True)
class QueryOutcome:
    """Everything one query produced, in dataset terms rather than UUIDs."""

    case: QueryCase
    outcome: AnswerOutcome
    decision: str
    confidence: float
    answer_text: str
    # What the retriever ranked, before the graph's sufficiency gate and its
    # `max_evidence` truncation. Scoring Recall@5 against the evidence the graph
    # kept would measure the *cap*, not the ranking: with `max_evidence=4` the
    # fifth result can never be inspected, so a relevant chunk at rank 5 would
    # register as a miss no matter how the ranker improved.
    retrieved_ids: tuple[str, ...]
    # What survived into generation. Reported separately because the gap between
    # the two is itself informative — it is how much the gate threw away.
    evidence_ids: tuple[str, ...]
    cited_ids: tuple[str, ...]
    supported_claims: int
    dropped_claims: int
    unresolvable_citations: int
    quotes_verbatim: bool
    seconds: float
    cost: CostAccount = field(default_factory=CostAccount)

    @property
    def answered(self) -> bool:
        return self.outcome in {AnswerOutcome.ANSWERED, AnswerOutcome.PARTIAL}

    @property
    def abstained(self) -> bool:
        return self.outcome is AnswerOutcome.ABSTAINED

    @property
    def correct(self) -> bool:
        """Answered, and the answer states the fact the dataset expects.

        Deliberately checked against the *answer text* rather than the span the
        generator chose to quote: which words it quotes is an implementation
        detail, whereas whether the reader is told the right thing is not.
        """
        if not self.answered or self.case.expected_quote is None:
            return False
        return normalize_for_match(self.case.expected_quote) in normalize_for_match(
            self.answer_text
        )

    @property
    def faithful(self) -> bool:
        """Every quote appears verbatim in the passage it cites, and each cites real evidence.

        This is the property that separates a grounded answer from a plausible
        one, so an answer citing nothing at all is not faithful by default —
        an abstention simply is not an answer and is excluded by the caller.
        """
        return self.quotes_verbatim and self.unresolvable_citations == 0 and bool(self.cited_ids)


def build_graph(datasets: EvaluationDatasets, workspace: str, config: RagConfig) -> RagGraph:
    return RagGraph(CorpusRetriever(datasets, workspace), config=config)


def default_config() -> RagConfig:
    """The evaluation's pipeline settings, stated once so every suite shares them.

    ``min_evidence_score`` gates out retrievals that share only a stray token
    with the query; without it a lexical stand-in retriever returns something for
    almost any string and the abstention numbers would measure the retriever's
    laxness rather than the pipeline's judgement.
    """
    return RagConfig(top_k=8, max_evidence=4, min_evidence=1, min_evidence_score=0.35)


async def _resolve_all(
    resolver: CitationResolver,
    references: Sequence[CitationReference],
) -> int:
    """How many citations failed to resolve against authorized provenance."""
    failures = 0
    for reference in references:
        try:
            await resolver.resolve(reference)
        except CitationError:
            failures += 1
    return failures


async def run_query(
    datasets: EvaluationDatasets,
    case: QueryCase,
    *,
    workspace: str = "alpha",
    config: RagConfig | None = None,
) -> QueryOutcome:
    """Run one labelled query end to end and record what happened."""
    settings = config or default_config()
    retriever = CorpusRetriever(datasets, workspace)
    graph = RagGraph(retriever, config=settings)
    resolver = CitationResolver(CorpusProvenanceReader(datasets, workspace))
    by_uuid = {chunk_uuid(chunk.chunk_id): chunk for chunk in datasets.corpus}

    # The retriever's own ranking, asked for separately and at the same `top_k`
    # the graph will use. Ranking quality is a property of the retriever, and
    # reading it off the graph's surviving evidence would silently score the
    # sufficiency gate and `max_evidence` instead. The retriever is
    # deterministic, so this is the same ranking the graph then receives.
    ranked, _ = await retriever.retrieve(
        workspace_id=workspace_uuid(workspace),
        query=case.text,
        top_k=settings.top_k,
        document_id=None,
        language=None,
    )

    state = RagState(
        workspace_id=workspace_uuid(workspace),
        query=case.text,
        top_k=settings.top_k,
        trace=RagTrace(
            workspace_id=workspace_uuid(workspace),
            detected_language=case.language,
            top_k=settings.top_k,
        ),
    )

    started = time.perf_counter()
    terminal = await graph.run(state)
    seconds = time.perf_counter() - started

    references = [
        CitationReference(
            chunk_id=claim.citation.chunk_id,
            document_version_id=claim.citation.document_version_id,
            quote=claim.citation.quote,
            quote_char_start=claim.citation.quote_char_start,
            quote_char_end=claim.citation.quote_char_end,
        )
        for claim in terminal.claims
    ]
    verbatim = all(
        normalize_for_match(claim.citation.quote)
        in normalize_for_match(by_uuid[claim.citation.chunk_id].text)
        for claim in terminal.claims
        if claim.citation.chunk_id in by_uuid
    )

    return QueryOutcome(
        case=case,
        outcome=terminal.outcome,
        decision=terminal.decision,
        confidence=terminal.trace.confidence or 0.0,
        answer_text=terminal.answer_text,
        retrieved_ids=tuple(
            by_uuid[passage.chunk_id].chunk_id for passage in ranked if passage.chunk_id in by_uuid
        ),
        evidence_ids=tuple(
            by_uuid[passage.chunk_id].chunk_id
            for passage in terminal.evidence
            if passage.chunk_id in by_uuid
        ),
        cited_ids=tuple(
            by_uuid[claim.citation.chunk_id].chunk_id
            for claim in terminal.claims
            if claim.citation.chunk_id in by_uuid
        ),
        supported_claims=len(terminal.claims),
        dropped_claims=terminal.trace.dropped_claim_count,
        unresolvable_citations=await _resolve_all(resolver, references),
        quotes_verbatim=verbatim,
        seconds=seconds,
    )


def run_queries(
    datasets: EvaluationDatasets,
    *,
    workspace: str = "alpha",
    config: RagConfig | None = None,
) -> tuple[QueryOutcome, ...]:
    async def _all() -> tuple[QueryOutcome, ...]:
        return tuple(
            [
                await run_query(datasets, case, workspace=workspace, config=config)
                for case in datasets.queries
            ]
        )

    return asyncio.run(_all())


@dataclass(frozen=True)
class IsolationOutcome:
    """One cross-tenant probe: what the reader's own pipeline returned."""

    case: IsolationCase
    answered: bool
    cited_ids: tuple[str, ...]
    answer_text: str
    target_text: str

    @property
    def leaked(self) -> bool:
        """True if the other workspace's passage reached the reader.

        Checked two ways because either alone can miss: the citation may name the
        foreign chunk, or the answer text may carry its wording without citing it
        at all. The corpus is written so the two tenants' clauses contradict each
        other, which is what makes the second check possible.
        """
        if self.case.target_chunk_id in self.cited_ids:
            return True
        return normalize_for_match(self.target_text) in normalize_for_match(self.answer_text)


def run_isolation(datasets: EvaluationDatasets) -> tuple[IsolationOutcome, ...]:
    """Ask each probe as the reader it belongs to, never as the owner."""

    async def _all() -> tuple[IsolationOutcome, ...]:
        results: list[IsolationOutcome] = []
        for case in datasets.isolation:
            probe = QueryCase(
                query_id=case.case_id,
                text=case.query,
                language="eng",
                answerable=False,
                relevance={},
                expected_quote=None,
                note=case.note,
            )
            outcome = await run_query(datasets, probe, workspace=case.reader_workspace)
            results.append(
                IsolationOutcome(
                    case=case,
                    answered=outcome.answered,
                    cited_ids=outcome.cited_ids,
                    answer_text=outcome.answer_text,
                    target_text=datasets.chunk(case.target_chunk_id).text,
                )
            )
        return tuple(results)

    return asyncio.run(_all())


@dataclass(frozen=True)
class InjectionOutcome:
    """One labelled injection sample and what the detector did with it.

    ``quarantined`` rather than "flagged" because quarantine is the decision that
    actually keeps content out of retrieval and generation. Flagging a benign
    passage for review costs a reviewer a glance; quarantining one silently
    removes a tenant's document from every answer, so only the blocking decision
    is scored.
    """

    is_attack: bool
    quarantined: bool
    language: str
    note: str


def run_injection(datasets: EvaluationDatasets) -> tuple[InjectionOutcome, ...]:
    return tuple(
        InjectionOutcome(
            is_attack=sample.is_attack,
            quarantined=assess_text(sample.text).is_quarantined,
            language=sample.language,
            note=sample.note,
        )
        for sample in datasets.injection
    )


__all__ = [
    "CorpusProvenanceReader",
    "CorpusRetriever",
    "InjectionOutcome",
    "IsolationOutcome",
    "QueryOutcome",
    "build_graph",
    "chunk_uuid",
    "default_config",
    "overlap",
    "run_injection",
    "run_isolation",
    "run_queries",
    "run_query",
    "tokens",
    "workspace_uuid",
]
