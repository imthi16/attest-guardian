"""Reciprocal Rank Fusion: combine multiple ranked lists into one.

RRF scores each item by summing ``1 / (k + rank)`` across the lists it
appears in, where `rank` is 1-based. It needs only ranks, not comparable
scores, which is exactly right for fusing lexical relevance (`ts_rank_cd`)
with dense cosine similarity. Larger `k` flattens the contribution of top
ranks; the field's common default is 60.

The function is pure and deterministic: ties break by chunk id so results are
stable across runs and reproducible in tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.retrieval.types import ScoredCandidate

DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class FusedCandidate:
    """A chunk's fused score and its 1-based rank in each source list."""

    chunk_id: uuid.UUID
    score: float
    ranks: dict[str, int]


def reciprocal_rank_fusion(
    ranked_lists: Mapping[str, Sequence[ScoredCandidate]],
    *,
    k: int = DEFAULT_RRF_K,
    limit: int | None = None,
) -> list[FusedCandidate]:
    """Fuse named ranked lists into one descending-score ranking.

    `ranked_lists` maps a source name (e.g. "lexical", "dense") to that
    source's candidates. Each candidate's own `rank` is used, so callers may
    pass pre-truncated lists. Output is sorted by fused score descending, then
    by chunk id for a deterministic tie-break, and truncated to `limit`.
    """
    if k <= 0:
        msg = "rrf k must be positive"
        raise ValueError(msg)

    scores: dict[uuid.UUID, float] = {}
    ranks: dict[uuid.UUID, dict[str, int]] = {}
    for source, candidates in ranked_lists.items():
        for candidate in candidates:
            contribution = 1.0 / (k + candidate.rank)
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + contribution
            ranks.setdefault(candidate.chunk_id, {})[source] = candidate.rank

    fused = [
        FusedCandidate(chunk_id=chunk_id, score=scores[chunk_id], ranks=ranks[chunk_id])
        for chunk_id in scores
    ]
    fused.sort(key=lambda item: (-item.score, item.chunk_id.bytes))
    if limit is not None:
        fused = fused[:limit]
    return fused
