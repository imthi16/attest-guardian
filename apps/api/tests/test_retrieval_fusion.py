"""Reciprocal Rank Fusion: ranking, ties, config, and edge cases."""

import uuid

import pytest
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.types import ScoredCandidate


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _candidate(n: int, rank: int, score: float = 0.0) -> ScoredCandidate:
    return ScoredCandidate(chunk_id=_id(n), rank=rank, score=score)


def test_empty_lists_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion({"lexical": [], "dense": []}) == []


def test_single_list_preserves_order() -> None:
    fused = reciprocal_rank_fusion(
        {"lexical": [_candidate(1, 1), _candidate(2, 2), _candidate(3, 3)]}
    )
    assert [item.chunk_id for item in fused] == [_id(1), _id(2), _id(3)]


def test_item_in_both_lists_outranks_item_in_one() -> None:
    # Chunk 1 is rank 2 in both lists; chunk 2 is rank 1 in only one list.
    fused = reciprocal_rank_fusion(
        {
            "lexical": [_candidate(2, 1), _candidate(1, 2)],
            "dense": [_candidate(3, 1), _candidate(1, 2)],
        },
        k=60,
    )
    # 1: 1/62 + 1/62 = 0.03226; 2: 1/61 = 0.01639; 3: 1/61 = 0.01639
    assert fused[0].chunk_id == _id(1)
    assert fused[0].ranks == {"lexical": 2, "dense": 2}


def test_scores_follow_the_rrf_formula() -> None:
    fused = reciprocal_rank_fusion({"lexical": [_candidate(1, 1)]}, k=60)
    assert fused[0].score == pytest.approx(1.0 / 61.0)


def test_ties_break_deterministically_by_chunk_id() -> None:
    # Both at rank 1 in their own single list => equal scores; id order decides.
    fused = reciprocal_rank_fusion({"lexical": [_candidate(5, 1)], "dense": [_candidate(2, 1)]})
    assert [item.chunk_id for item in fused] == [_id(2), _id(5)]


def test_limit_truncates_after_ranking() -> None:
    fused = reciprocal_rank_fusion(
        {"lexical": [_candidate(1, 1), _candidate(2, 2), _candidate(3, 3)]},
        limit=2,
    )
    assert len(fused) == 2
    assert [item.chunk_id for item in fused] == [_id(1), _id(2)]


def test_larger_k_flattens_rank_advantage() -> None:
    small_k = reciprocal_rank_fusion({"lexical": [_candidate(1, 1), _candidate(2, 10)]}, k=1)
    large_k = reciprocal_rank_fusion({"lexical": [_candidate(1, 1), _candidate(2, 10)]}, k=1000)
    small_gap = small_k[0].score - small_k[1].score
    large_gap = large_k[0].score - large_k[1].score
    assert small_gap > large_gap


def test_nonpositive_k_is_rejected() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        reciprocal_rank_fusion({"lexical": [_candidate(1, 1)]}, k=0)
