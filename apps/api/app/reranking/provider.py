"""A local, deterministic multilingual reranker.

The production system will load a cross-encoder (`BAAI/bge-reranker-v2-m3`)
behind this same `Reranker` interface. Shipping model weights in the MVP is
neither desirable (size, licensing, offline CI) nor necessary to exercise the
normalization, thresholding, ordering, and telemetry that this feature adds.

`LocalLexicalReranker` therefore scores query/passage relevance with a
deterministic token-overlap measure over `app.language`-normalized text:
weighted Jaccard over unigrams plus character trigrams, the same feature basis
the local embedder uses, so Tamil, English, and Tanglish are all handled with
no language-specific tables. It is a lexical stand-in, not a semantic
cross-encoder: use it for wiring and tests, not to measure real rerank
quality.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.language import normalize_for_match
from app.reranking.types import RerankItem, RerankScore

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class LocalLexicalReranker:
    """Deterministic multilingual reranker with no external dependencies."""

    def __init__(
        self,
        *,
        model: str = "bge-reranker-v2-m3-local",
        model_version: str = "lexical-v1",
    ) -> None:
        self.model = model
        self.model_version = model_version

    def score(self, query: str, items: Sequence[RerankItem]) -> Sequence[RerankScore]:
        query_features = self._features(query)
        return [
            RerankScore(
                chunk_id=item.chunk_id,
                score=self._relevance(query_features, self._features(item.text)),
            )
            for item in items
        ]

    def _relevance(self, query_features: set[str], passage_features: set[str]) -> float:
        """Weighted Jaccard similarity in [0, 1]; 0 when either side is empty.

        Dividing the shared features by the query's feature count rewards
        passages that cover the query, while the union term damps very long
        passages that would otherwise match by sheer size.
        """
        if not query_features or not passage_features:
            return 0.0
        shared = query_features & passage_features
        if not shared:
            return 0.0
        coverage = len(shared) / len(query_features)
        jaccard = len(shared) / len(query_features | passage_features)
        # Blend coverage (recall of query terms) with Jaccard (precision), so a
        # passage must both contain the query terms and not be mostly noise.
        return 0.5 * coverage + 0.5 * jaccard

    def _features(self, text: str) -> set[str]:
        """Unigrams plus character trigrams over normalized text."""
        normalized = normalize_for_match(text)
        tokens = _TOKEN.findall(normalized)
        features: set[str] = set(tokens)
        for token in tokens:
            padded = f"#{token}#"
            features.update(padded[i : i + 3] for i in range(len(padded) - 2))
        return features
