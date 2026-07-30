"""Measurement of the platform's own answer quality.

The package holds three things: the scoring functions (:mod:`metrics`), the
versioned labelled data they are computed over (:mod:`datasets`), and the
versioned floors those numbers must clear (:mod:`thresholds`). Keeping them
together is the point — a metric, the data behind it, and the bar it has to
clear are one contract, and a number is meaningless without all three.

Nothing here reaches a network or a database. The datasets are synthetic and
public, so an evaluation is reproducible on any checkout and CI can fail on a
regression without access to a tenant's documents or a paid model.
"""

from app.evaluation.datasets import (
    DatasetError,
    EvaluationDatasets,
    load_datasets,
)
from app.evaluation.metrics import (
    ClassificationCounts,
    CostAccount,
    classify,
    mean,
    mean_reciprocal_rank,
    ndcg_at_k,
    percentile,
    rate,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.thresholds import Thresholds, load_thresholds

__all__ = [
    "ClassificationCounts",
    "CostAccount",
    "DatasetError",
    "EvaluationDatasets",
    "Thresholds",
    "classify",
    "load_datasets",
    "load_thresholds",
    "mean",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "percentile",
    "rate",
    "recall_at_k",
    "reciprocal_rank",
]
