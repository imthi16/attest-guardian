"""Reranker provider and service: ordering, normalization, thresholds, failure."""

import uuid

import pytest
from app.reranking.provider import LocalLexicalReranker
from app.reranking.service import RerankService
from app.reranking.types import RerankError, RerankItem, RerankScore


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _items(*texts: str) -> list[RerankItem]:
    return [RerankItem(chunk_id=_id(i + 1), text=text) for i, text in enumerate(texts)]


class StubReranker:
    """Returns preset scores keyed by chunk id, in input order."""

    model = "stub-reranker"
    model_version = "v1"

    def __init__(self, scores: dict[uuid.UUID, float]) -> None:
        self._scores = scores

    def score(self, query: str, items):  # type: ignore[no-untyped-def]
        return [
            RerankScore(chunk_id=item.chunk_id, score=self._scores[item.chunk_id]) for item in items
        ]


class FailingReranker:
    model = "failing-reranker"
    model_version = "v1"

    def score(self, query: str, items):  # type: ignore[no-untyped-def]
        raise RerankError("boom")


class MiscountingReranker:
    model = "miscounting"
    model_version = "v1"

    def score(self, query: str, items):  # type: ignore[no-untyped-def]
        return []  # wrong number of scores


# --- Local provider --------------------------------------------------------


def test_local_reranker_scores_overlap_higher() -> None:
    reranker = LocalLexicalReranker()
    items = _items("the annual invoice total", "unrelated weather report")
    scores = reranker.score("invoice total", items)
    by_id = {score.chunk_id: score.score for score in scores}
    assert by_id[_id(1)] > by_id[_id(2)]


def test_local_reranker_is_deterministic() -> None:
    reranker = LocalLexicalReranker()
    items = _items("contract renewal terms")
    first = reranker.score("renewal", items)
    second = reranker.score("renewal", items)
    assert first[0].score == second[0].score


def test_local_reranker_handles_tamil() -> None:
    reranker = LocalLexicalReranker()
    items = _items("இந்த ஒப்பந்தம் மார்ச் மாதம்", "கடலோர வானிலை")
    scores = reranker.score("ஒப்பந்தம் மார்ச்", items)
    by_id = {score.chunk_id: score.score for score in scores}
    assert by_id[_id(1)] > by_id[_id(2)]


def test_local_reranker_empty_query_scores_zero() -> None:
    reranker = LocalLexicalReranker()
    scores = reranker.score("", _items("anything at all"))
    assert scores[0].score == 0.0


# --- Service ---------------------------------------------------------------


def test_service_reorders_by_score_descending() -> None:
    stub = StubReranker({_id(1): 0.2, _id(2): 0.9, _id(3): 0.5})
    outcome = RerankService(stub).rerank("q", _items("a", "b", "c"))
    order = [item.chunk_id for item in outcome.result.items]
    assert order == [_id(2), _id(3), _id(1)]
    assert [item.rank for item in outcome.result.items] == [1, 2, 3]


def test_service_normalizes_scores_into_unit_interval() -> None:
    stub = StubReranker({_id(1): 1.0, _id(2): 3.0, _id(3): 5.0})
    outcome = RerankService(stub).rerank("q", _items("a", "b", "c"))
    normalized = {item.chunk_id: item.normalized_score for item in outcome.result.items}
    assert normalized[_id(3)] == pytest.approx(1.0)
    assert normalized[_id(1)] == pytest.approx(0.0)
    assert normalized[_id(2)] == pytest.approx(0.5)


def test_service_equal_scores_normalize_to_one_and_keep_order() -> None:
    stub = StubReranker({_id(1): 2.0, _id(2): 2.0})
    outcome = RerankService(stub, threshold=1.0).rerank("q", _items("a", "b"))
    assert len(outcome.result.items) == 2
    assert all(item.normalized_score == 1.0 for item in outcome.result.items)


def test_service_threshold_drops_low_scores() -> None:
    stub = StubReranker({_id(1): 0.0, _id(2): 5.0, _id(3): 10.0})
    outcome = RerankService(stub, threshold=0.5).rerank("q", _items("a", "b", "c"))
    kept = {item.chunk_id for item in outcome.result.items}
    assert kept == {_id(2), _id(3)}  # normalized 0.0 dropped
    assert outcome.result.dropped_below_threshold == 1
    assert outcome.metrics.dropped_below_threshold == 1


def test_service_empty_input_returns_empty() -> None:
    outcome = RerankService(StubReranker({})).rerank("q", [])
    assert outcome.result.items == []
    assert outcome.metrics.considered == 0


def test_service_failure_preserves_order_and_flags_metric() -> None:
    items = _items("a", "b", "c")
    outcome = RerankService(FailingReranker()).rerank("q", items)
    assert outcome.metrics.failed is True
    assert [item.chunk_id for item in outcome.result.items] == [_id(1), _id(2), _id(3)]


def test_service_records_latency() -> None:
    outcome = RerankService(StubReranker({_id(1): 1.0})).rerank("q", _items("a"))
    assert outcome.metrics.duration_ms >= 0.0
    assert outcome.metrics.returned == 1


def test_service_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError, match="threshold must be within"):
        RerankService(StubReranker({}), threshold=1.5)


def test_service_miscount_is_a_hard_error() -> None:
    with pytest.raises(RerankError, match="wrong number of scores"):
        RerankService(MiscountingReranker()).rerank("q", _items("a", "b"))


def test_service_exposes_model_provenance() -> None:
    service = RerankService(StubReranker({}))
    assert service.model == "stub-reranker"
    assert service.model_version == "v1"


def test_provider_replacement_changes_ordering() -> None:
    # Two different rerankers over the same items must be able to disagree.
    forward = StubReranker({_id(1): 0.9, _id(2): 0.1})
    reverse = StubReranker({_id(1): 0.1, _id(2): 0.9})
    a = RerankService(forward).rerank("q", _items("a", "b"))
    b = RerankService(reverse).rerank("q", _items("a", "b"))
    assert a.result.items[0].chunk_id == _id(1)
    assert b.result.items[0].chunk_id == _id(2)
