"""The scoring functions themselves, against hand-computed values.

A quality gate is only as trustworthy as its arithmetic: a metric that is
quietly wrong either hides a regression or blocks a good change, and neither
failure announces itself. So the expected numbers here are written out by hand
rather than derived from the implementation.

The recurring theme is the undefined case. Precision over nothing, recall over
nothing, and a mean of nothing are not zero and not one — they are absent, and a
metric that returned a number there would let an empty evaluation clear a
threshold.
"""

from __future__ import annotations

import math

import pytest
from app.evaluation.metrics import (
    ClassificationCounts,
    CostAccount,
    classify,
    dcg,
    mean,
    mean_reciprocal_rank,
    ndcg_at_k,
    percentile,
    rate,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_counts_only_the_top_k() -> None:
    ranked = ["a", "b", "c", "d"]
    assert recall_at_k(ranked, {"a", "d"}, 2) == 0.5
    assert recall_at_k(ranked, {"a", "d"}, 4) == 1.0
    assert recall_at_k(ranked, {"z"}, 4) == 0.0


def test_recall_is_undefined_when_nothing_is_relevant() -> None:
    """Scoring "found all zero of them" as perfect would flatter every ranking.

    An unanswerable query has no relevant document by construction, and it is
    exactly the kind of case a corpus has many of, so a `1.0` here would lift the
    mean by however many such queries were added.
    """
    assert recall_at_k(["a"], [], 3) is None


def test_recall_rejects_a_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        recall_at_k(["a"], ["a"], 0)


def test_reciprocal_rank_is_one_based() -> None:
    # First position is 1/1, not 1/0 and not 1/2.
    assert reciprocal_rank(["a", "b"], {"a"}) == 1.0
    assert reciprocal_rank(["a", "b"], {"b"}) == 0.5
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)


def test_reciprocal_rank_of_a_miss_is_zero() -> None:
    """A ranking that never surfaces a relevant item has failed, not abstained."""
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_mean_reciprocal_rank_skips_queries_with_no_right_answer() -> None:
    # Second pair has nothing relevant, so the mean is over the first and third
    # alone: (1.0 + 0.5) / 2, not (1.0 + 0.0 + 0.5) / 3.
    assert mean_reciprocal_rank(
        [
            (["a", "b"], {"a"}),
            (["a", "b"], set()),
            (["a", "b"], {"b"}),
        ]
    ) == pytest.approx(0.75)


def test_mean_reciprocal_rank_of_nothing_is_undefined() -> None:
    assert mean_reciprocal_rank([]) is None
    assert mean_reciprocal_rank([(["a"], set())]) is None


def test_dcg_applies_the_log2_rank_plus_one_discount() -> None:
    # Rank 1 is undiscounted (log2(2) == 1), rank 2 is divided by log2(3).
    assert dcg([3.0, 2.0]) == pytest.approx(3.0 + 2.0 / math.log2(3))


def test_ndcg_is_one_for_the_ideal_ordering() -> None:
    gains = {"a": 3.0, "b": 2.0, "c": 1.0}
    assert ndcg_at_k(["a", "b", "c"], gains, 3) == pytest.approx(1.0)


def test_ndcg_penalizes_a_reversed_ordering() -> None:
    gains = {"a": 3.0, "b": 2.0, "c": 1.0}
    ideal = 3.0 + 2.0 / math.log2(3) + 1.0 / 2.0
    reversed_dcg = 1.0 + 2.0 / math.log2(3) + 3.0 / 2.0
    assert ndcg_at_k(["c", "b", "a"], gains, 3) == pytest.approx(reversed_dcg / ideal)


def test_ndcg_scores_unlisted_items_as_zero_gain() -> None:
    gains = {"a": 1.0}
    # Only the second slot is relevant, so the score is the rank-2 discount.
    assert ndcg_at_k(["z", "a"], gains, 2) == pytest.approx(1 / math.log2(3))


def test_ndcg_is_undefined_when_no_item_has_any_gain() -> None:
    """The ideal ranking scores zero too, so the ratio is 0/0 rather than 0."""
    assert ndcg_at_k(["a"], {}, 3) is None
    assert ndcg_at_k(["a"], {"a": 0.0}, 3) is None


def test_ndcg_rejects_a_non_positive_k() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        ndcg_at_k(["a"], {"a": 1.0}, 0)


def test_ndcg_rejects_a_negative_gain() -> None:
    # Clamping would silently report a metric over data nobody labelled.
    with pytest.raises(ValueError, match="must not be negative"):
        ndcg_at_k(["a"], {"a": -1.0}, 3)


def test_classify_tallies_every_quadrant() -> None:
    counts = classify(
        [
            (True, True),
            (True, False),
            (False, True),
            (False, False),
            (True, True),
        ]
    )

    assert counts == ClassificationCounts(
        true_positives=2,
        false_positives=1,
        false_negatives=1,
        true_negatives=1,
    )
    assert counts.precision == pytest.approx(2 / 3)
    assert counts.recall == pytest.approx(2 / 3)
    assert counts.f1 == pytest.approx(2 / 3)
    assert counts.accuracy == pytest.approx(3 / 5)


def test_precision_is_undefined_when_nothing_was_flagged() -> None:
    """A detector that flags nothing has no precision — it is not perfectly precise."""
    counts = classify([(False, True), (False, False)])

    assert counts.precision is None
    assert counts.recall == 0.0
    assert counts.f1 is None


def test_recall_is_undefined_when_there_was_nothing_to_find() -> None:
    counts = classify([(True, False), (False, False)])

    assert counts.recall is None
    assert counts.precision == 0.0
    assert counts.f1 is None


def test_f1_is_undefined_when_both_sides_are_zero() -> None:
    counts = classify([(True, False), (False, True)])

    assert counts.precision == 0.0
    assert counts.recall == 0.0
    assert counts.f1 is None


def test_empty_classification_reports_nothing_rather_than_perfection() -> None:
    counts = classify([])

    assert counts.precision is None
    assert counts.recall is None
    assert counts.accuracy is None
    assert counts.total == 0


def test_rate_and_mean_are_undefined_over_nothing() -> None:
    assert rate(0, 0) is None
    assert rate(1, 4) == 0.25
    assert mean([]) is None
    assert mean([1.0, 2.0]) == 1.5


def test_percentile_reports_an_observed_value() -> None:
    """Nearest-rank, so a reported p95 is a duration something actually took."""
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 0.5) == 20.0
    assert percentile(values, 0.95) == 40.0
    assert percentile(values, 1.0) == 40.0
    # Interpolation would have produced 38.5 here, which no sample recorded.
    assert percentile(values, 0.95) in values


def test_percentile_of_nothing_is_undefined() -> None:
    assert percentile([], 0.5) is None


def test_percentile_rejects_a_fraction_outside_the_unit_range() -> None:
    for fraction in (0.0, 1.5, -0.1):
        with pytest.raises(ValueError, match="fraction must be"):
            percentile([1.0], fraction)


def test_cost_accounts_add_and_default_to_free() -> None:
    """The extractive local pipeline spends nothing, and says so rather than guessing."""
    empty = CostAccount()
    assert empty.total_tokens == 0
    assert empty.usd == 0.0

    combined = CostAccount(prompt_tokens=10, completion_tokens=5, usd=0.02) + CostAccount(
        prompt_tokens=1, completion_tokens=2, usd=0.01
    )
    assert combined.total_tokens == 18
    assert combined.usd == pytest.approx(0.03)


def test_mean_reciprocal_rank_accepts_one_shot_iterators() -> None:
    """The `relevant` side is materialized once, not consumed twice.

    Checking emptiness and then scoring would exhaust a generator, and every
    query would record `0.0` — a catastrophic MRR produced by the measurement
    rather than by the ranking, which is the worst kind of wrong number.
    """
    rankings = [(["a", "b"], (item for item in ["b"]))]

    assert mean_reciprocal_rank(rankings) == 0.5


def test_ndcg_pays_a_repeated_item_only_once() -> None:
    """Otherwise returning the same chunk twice scores better than returning two.

    The ideal ranking holds each item once, so collecting its gain again on a
    second appearance can push the ratio above 1.0 — a metric that rewards a
    retriever for duplicating its best result.
    """
    gains = {"a": 2.0}

    repeated = ndcg_at_k(["a", "a"], gains, 2)
    once = ndcg_at_k(["a"], gains, 2)

    assert repeated == once == 1.0
    assert repeated is not None
    assert repeated <= 1.0
