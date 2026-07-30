"""Scoring functions for the evaluation harness.

Every number the platform reports about its own quality is computed here, so a
metric means the same thing in a test, in a report, and in a threshold. The
functions are pure: they take labelled results and return floats, with no
knowledge of where the results came from.

Two conventions run through the module, both chosen so a metric can never
flatter the system:

* **An undefined metric is `None`, never `0.0` and never `1.0`.** Precision over
  zero predictions, recall over zero relevant items, and a mean over an empty
  set are all undefined. Returning a number would let an empty evaluation report
  a perfect (or catastrophic) score, and a threshold would then pass on evidence
  that does not exist. Callers must decide what an absent metric means.
* **Ranks are 1-based in the output, 0-based in the input.** A ranked list is a
  sequence; reciprocal rank is `1/position`. Mixing the two silently halves MRR,
  so the boundary is stated rather than assumed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


def recall_at_k(ranked: Sequence[object], relevant: Iterable[object], k: int) -> float | None:
    """Fraction of the relevant items that appear in the top ``k``.

    ``None`` when nothing is relevant: a query with no correct answer cannot
    have its recall measured, and scoring it as `1.0` ("found all zero of them")
    would raise the mean for every query the system knows nothing about.
    """
    if k <= 0:
        message = "k must be positive"
        raise ValueError(message)
    wanted = set(relevant)
    if not wanted:
        return None
    found = wanted.intersection(ranked[:k])
    return len(found) / len(wanted)


def reciprocal_rank(ranked: Sequence[object], relevant: Iterable[object]) -> float:
    """``1 / position`` of the first relevant item, or ``0.0`` if absent.

    Zero is a real score here rather than an undefined one: a ranking that never
    surfaces a relevant item has genuinely failed, which is different from a
    query that had nothing to surface. Callers filter those out first.
    """
    wanted = set(relevant)
    for index, item in enumerate(ranked):
        if item in wanted:
            return 1.0 / (index + 1)
    return 0.0


def mean_reciprocal_rank(
    rankings: Iterable[tuple[Sequence[object], Iterable[object]]],
) -> float | None:
    """MRR over ``(ranked, relevant)`` pairs, ignoring pairs with no relevant item."""
    scores = [
        reciprocal_rank(ranked, relevant)
        for ranked, relevant in rankings
        if set(relevant)  # a query with no right answer cannot be scored
    ]
    return sum(scores) / len(scores) if scores else None


def dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain with the standard ``log2(rank + 1)`` discount."""
    return sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))


def ndcg_at_k[T](
    ranked: Sequence[T],
    gains: Mapping[T, float],
    k: int,
) -> float | None:
    """nDCG@k against the best ordering the graded gains allow.

    ``gains`` maps an item to its relevance grade; anything absent scores zero.
    ``None`` when every gain is zero or negative — the ideal ranking would score
    zero too, and the ratio would be `0/0`. Negative grades are rejected rather
    than clamped: they make the "ideal" ordering ambiguous, and silently
    dropping them would report a metric nobody asked for.
    """
    if k <= 0:
        message = "k must be positive"
        raise ValueError(message)
    if any(gain < 0 for gain in gains.values()):
        message = "relevance gains must not be negative"
        raise ValueError(message)
    ideal = sorted(gains.values(), reverse=True)[:k]
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0.0:
        return None
    actual = [gains.get(item, 0.0) for item in ranked[:k]]
    return dcg(actual) / ideal_dcg


@dataclass(frozen=True)
class ClassificationCounts:
    """Confusion-matrix counts for one binary decision."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def predicted_positive(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def actual_positive(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def total(self) -> int:
        return self.predicted_positive + self.false_negatives + self.true_negatives

    @property
    def precision(self) -> float | None:
        """Of what was flagged, how much should have been. ``None`` if nothing was."""
        if self.predicted_positive == 0:
            return None
        return self.true_positives / self.predicted_positive

    @property
    def recall(self) -> float | None:
        """Of what should have been flagged, how much was. ``None`` if nothing should."""
        if self.actual_positive == 0:
            return None
        return self.true_positives / self.actual_positive

    @property
    def f1(self) -> float | None:
        """Harmonic mean of precision and recall; ``None`` if either is undefined."""
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0.0:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def accuracy(self) -> float | None:
        if self.total == 0:
            return None
        return (self.true_positives + self.true_negatives) / self.total


def classify(predictions: Iterable[tuple[bool, bool]]) -> ClassificationCounts:
    """Tally ``(predicted, actual)`` pairs into a confusion matrix."""
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for predicted, actual in predictions:
        if predicted and actual:
            counts["tp"] += 1
        elif predicted and not actual:
            counts["fp"] += 1
        elif actual:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
    return ClassificationCounts(
        true_positives=counts["tp"],
        false_positives=counts["fp"],
        false_negatives=counts["fn"],
        true_negatives=counts["tn"],
    )


def rate(numerator: int, denominator: int) -> float | None:
    """A proportion, or ``None`` when there was nothing to take a proportion of."""
    return numerator / denominator if denominator else None


def mean(values: Iterable[float]) -> float | None:
    """Arithmetic mean, or ``None`` over an empty sequence."""
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def percentile(values: Iterable[float], fraction: float) -> float | None:
    """Nearest-rank percentile — the smallest observed value at or above ``fraction``.

    Nearest-rank rather than interpolated, because a latency budget is met by a
    measurement that actually happened. An interpolated p95 can report a duration
    that no request took, which is not a fact about the system.
    """
    if not 0.0 < fraction <= 1.0:
        message = "fraction must be in (0, 1]"
        raise ValueError(message)
    ordered = sorted(values)
    if not ordered:
        return None
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[index]


@dataclass(frozen=True)
class CostAccount:
    """Token and money cost of one evaluation run.

    Kept explicit and defaulted to zero because the MVP pipeline is extractive
    and local: no tokens are sent to a paid service, so the honest recorded cost
    is zero rather than an estimate. The field exists so that swapping in a
    hosted model makes the cost appear in the report instead of being invisible.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: CostAccount) -> CostAccount:
        return CostAccount(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            usd=self.usd + other.usd,
        )


__all__ = [
    "ClassificationCounts",
    "CostAccount",
    "classify",
    "dcg",
    "mean",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "percentile",
    "rate",
    "recall_at_k",
    "reciprocal_rank",
]
