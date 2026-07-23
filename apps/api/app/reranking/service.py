"""The rerank service: score, normalize, threshold, and reorder candidates.

The service is deliberately thin and provider-agnostic. It calls a `Reranker`,
min-max normalizes the raw scores into [0, 1] so a threshold is meaningful
across models, drops candidates below the threshold, and returns items ordered
by normalized score (ties broken by chunk id for determinism).

Failure is safe by construction: if the reranker raises, the service returns
the original candidate order untouched (with a marker in telemetry) rather than
dropping evidence, because losing authorized evidence is worse than skipping a
reordering. Telemetry records counts, latency, and the model, never passage
text or the query.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.reranking.provider import LocalLexicalReranker
from app.reranking.types import (
    RankedItem,
    Reranker,
    RerankError,
    RerankItem,
    RerankResult,
    RerankScore,
)

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger("app.reranking")


def build_reranker(settings: Settings | None = None) -> Reranker:
    """Construct the configured reranker behind the `Reranker` interface.

    Only the local provider ships in the MVP; a hosted cross-encoder would be
    resolved here by `settings.reranker_provider` without changing callers.
    """
    return LocalLexicalReranker()


@dataclass
class RerankMetrics:
    """Non-sensitive performance and outcome counters for one rerank call."""

    considered: int = 0
    returned: int = 0
    dropped_below_threshold: int = 0
    duration_ms: float = 0.0
    failed: bool = False

    def as_metadata(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "returned": self.returned,
            "dropped_below_threshold": self.dropped_below_threshold,
            "duration_ms": round(self.duration_ms, 3),
            "failed": self.failed,
        }


@dataclass
class RerankOutcome:
    """The reranked result plus the metrics gathered producing it."""

    result: RerankResult
    metrics: RerankMetrics = field(default_factory=RerankMetrics)


class RerankService:
    """Scores, normalizes, thresholds, and reorders candidate passages."""

    def __init__(
        self,
        reranker: Reranker | None = None,
        *,
        threshold: float = 0.0,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            msg = "threshold must be within [0, 1]"
            raise ValueError(msg)
        self._reranker = reranker or LocalLexicalReranker()
        self._threshold = threshold

    @property
    def model(self) -> str:
        return self._reranker.model

    @property
    def model_version(self) -> str:
        return self._reranker.model_version

    def rerank(self, query: str, items: Sequence[RerankItem]) -> RerankOutcome:
        metrics = RerankMetrics(considered=len(items))
        if not items:
            return RerankOutcome(result=self._empty(), metrics=metrics)

        start = time.perf_counter()
        try:
            scores = self._reranker.score(query, items)
        except RerankError:
            metrics.duration_ms = (time.perf_counter() - start) * 1000
            metrics.failed = True
            metrics.returned = len(items)
            logger.warning(
                "reranker failed; preserving retrieval order",
                extra={"model": self.model, "considered": len(items)},
            )
            return RerankOutcome(result=self._passthrough(items), metrics=metrics)
        metrics.duration_ms = (time.perf_counter() - start) * 1000

        if len(scores) != len(items):
            # A contract violation is a bug, not bad input: fail loudly rather
            # than silently misalign scores with chunks.
            msg = "reranker returned the wrong number of scores"
            raise RerankError(msg)

        ranked, dropped = self._normalize_and_threshold(scores)
        metrics.returned = len(ranked)
        metrics.dropped_below_threshold = dropped
        logger.info(
            "rerank complete",
            extra={"model": self.model, **metrics.as_metadata()},
        )
        return RerankOutcome(
            result=RerankResult(
                items=ranked,
                model=self.model,
                model_version=self.model_version,
                considered=len(items),
                dropped_below_threshold=dropped,
            ),
            metrics=metrics,
        )

    def _normalize_and_threshold(
        self,
        scores: Sequence[RerankScore],
    ) -> tuple[list[RankedItem], int]:
        raw_values = [score.score for score in scores]
        lowest = min(raw_values)
        highest = max(raw_values)
        span = highest - lowest

        normalized: list[tuple[RerankScore, float]] = []
        for score in scores:
            # Min-max into [0, 1]. When every score is equal there is no signal
            # to separate them, so they all normalize to 1.0 and pass any
            # threshold <= 1 together, preserving the incoming order.
            value = 1.0 if span == 0.0 else (score.score - lowest) / span
            normalized.append((score, value))

        kept = [pair for pair in normalized if pair[1] >= self._threshold]
        dropped = len(normalized) - len(kept)
        kept.sort(key=lambda pair: (-pair[1], pair[0].chunk_id.bytes))
        ranked = [
            RankedItem(
                chunk_id=score.chunk_id,
                raw_score=score.score,
                normalized_score=value,
                rank=index + 1,
            )
            for index, (score, value) in enumerate(kept)
        ]
        return ranked, dropped

    def _passthrough(self, items: Sequence[RerankItem]) -> RerankResult:
        """Preserve the incoming order when the reranker is unavailable."""
        ranked = [
            RankedItem(chunk_id=item.chunk_id, raw_score=0.0, normalized_score=0.0, rank=index + 1)
            for index, item in enumerate(items)
        ]
        return RerankResult(
            items=ranked,
            model=self.model,
            model_version=self.model_version,
            considered=len(items),
            dropped_below_threshold=0,
        )

    def _empty(self) -> RerankResult:
        return RerankResult(
            items=[],
            model=self.model,
            model_version=self.model_version,
            considered=0,
            dropped_below_threshold=0,
        )
