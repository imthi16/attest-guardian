"""Measurable rerank-quality evaluation for the local reranker.

This is a deterministic, offline evaluation (not a plumbing test): it scores
the local reranker on a small labelled multilingual fixture and asserts a
minimum top-1 accuracy and mean reciprocal rank. It guards against regressions
in the ranking heuristic. Numbers are modest because the MVP reranker is
lexical, not a semantic cross-encoder; the thresholds exist to catch a drop,
not to certify production quality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.reranking.service import RerankService
from app.reranking.types import RerankItem


@dataclass(frozen=True)
class Case:
    query: str
    passages: tuple[str, ...]
    relevant_index: int  # index of the single most relevant passage


# Labelled fixtures across English, Tamil, and Tanglish. The relevant passage
# is the one a human would cite for the query.
CASES: tuple[Case, ...] = (
    Case(
        query="invoice payment due date",
        passages=(
            "The invoice payment is due within thirty days of receipt.",
            "Our office will be closed for the public holiday.",
            "Employees may claim travel reimbursement quarterly.",
        ),
        relevant_index=0,
    ),
    Case(
        query="annual leave policy",
        passages=(
            "Fire drills are conducted twice a year.",
            "Annual leave accrues monthly and carries over once.",
            "The cafeteria menu changes every week.",
        ),
        relevant_index=1,
    ),
    Case(
        query="ஒப்பந்த முடிவு தேதி",
        passages=(
            "கடலோர பகுதிகளில் வானிலை மாறுபாடு உள்ளது.",
            "ஊழியர் விடுப்பு ஒவ்வொரு மாதமும் சேர்க்கப்படும்.",
            "இந்த ஒப்பந்தம் மார்ச் மாதம் முடிவடைகிறது.",
        ),
        relevant_index=2,
    ),
    Case(
        query="oppantham mudivu",
        passages=(
            "climate change affects coastal regions",
            "இந்த ஒப்பந்தம் மார்ச் மாதம் ம= oppantham march",
            "the annual staff picnic was postponed",
        ),
        relevant_index=1,
    ),
    Case(
        query="refund processing time",
        passages=(
            "Refunds are processed within five business days.",
            "New employees complete orientation in week one.",
            "The parking lot will be repaved next month.",
        ),
        relevant_index=0,
    ),
)


def _rank_of_relevant(case: Case) -> int:
    service = RerankService()  # local reranker, threshold 0
    items = [
        RerankItem(chunk_id=uuid.UUID(int=index), text=text)
        for index, text in enumerate(case.passages)
    ]
    outcome = service.rerank(case.query, items)
    relevant_id = uuid.UUID(int=case.relevant_index)
    for ranked in outcome.result.items:
        if ranked.chunk_id == relevant_id:
            return ranked.rank
    msg = "relevant passage was dropped"
    raise AssertionError(msg)


def test_reranker_top1_accuracy_meets_threshold() -> None:
    hits = sum(1 for case in CASES if _rank_of_relevant(case) == 1)
    accuracy = hits / len(CASES)
    assert accuracy >= 0.8, f"top-1 accuracy regressed to {accuracy:.2f}"


def test_reranker_mean_reciprocal_rank_meets_threshold() -> None:
    mrr = sum(1.0 / _rank_of_relevant(case) for case in CASES) / len(CASES)
    assert mrr >= 0.85, f"MRR regressed to {mrr:.3f}"
