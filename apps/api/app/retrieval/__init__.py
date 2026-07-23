"""Permission-filtered hybrid retrieval: lexical + dense search fused by RRF."""

from app.retrieval.fusion import DEFAULT_RRF_K, FusedCandidate, reciprocal_rank_fusion
from app.retrieval.service import HybridRetrievalService, RetrievalConfig
from app.retrieval.types import (
    RetrievalFilters,
    RetrievalResult,
    RetrievalSource,
    RetrievalTrace,
    RetrievedChunk,
    ScoredCandidate,
)

__all__ = [
    "DEFAULT_RRF_K",
    "FusedCandidate",
    "HybridRetrievalService",
    "RetrievalConfig",
    "RetrievalFilters",
    "RetrievalResult",
    "RetrievalSource",
    "RetrievalTrace",
    "RetrievedChunk",
    "ScoredCandidate",
    "reciprocal_rank_fusion",
]
