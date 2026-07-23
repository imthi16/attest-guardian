"""Reranker interface and shared types.

Rerankers are kept behind the `Reranker` protocol so the local MVP reranker
can be replaced by a hosted cross-encoder (the planned `bge-reranker-v2-m3`)
without touching the retrieval pipeline. A reranker scores how well a passage
answers a query; the service normalizes those raw scores, applies a threshold,
and reorders candidates. Passage text is untrusted data, never an instruction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class RerankError(Exception):
    """A reranker failed to score a query/passage batch."""


@dataclass(frozen=True)
class RerankItem:
    """One passage to score against the query, keyed by its chunk id."""

    chunk_id: uuid.UUID
    text: str


@dataclass(frozen=True)
class RerankScore:
    """A reranker's raw relevance score for one passage.

    `score` is the reranker's own scale (cross-encoders emit unbounded
    logits); the service normalizes it. Higher always means more relevant.
    """

    chunk_id: uuid.UUID
    score: float


@dataclass(frozen=True)
class RankedItem:
    """A passage after reranking: raw score, normalized score, and new rank."""

    chunk_id: uuid.UUID
    raw_score: float
    normalized_score: float
    rank: int


@dataclass(frozen=True)
class RerankResult:
    """The reordered, threshold-filtered items plus reranker provenance."""

    items: list[RankedItem]
    model: str
    model_version: str
    considered: int
    dropped_below_threshold: int


@runtime_checkable
class Reranker(Protocol):
    """Scores passages by relevance to a query.

    Implementations must be deterministic for a given (query, passages, model
    version) so scores are reproducible and telemetry is meaningful. Order of
    returned scores matches the order of the input items.
    """

    model: str
    model_version: str

    def score(self, query: str, items: Sequence[RerankItem]) -> Sequence[RerankScore]: ...
