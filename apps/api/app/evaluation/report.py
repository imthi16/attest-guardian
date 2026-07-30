"""Turning one harness run into the report and the pass/fail verdict.

Every metric the platform claims about itself is computed here, in one place, so
a test and a published report can never disagree about what a number means. The
report is JSON and deterministic apart from timings, which makes it diffable
between runs and reviewable in a pull request.

Run it directly to regenerate the committed baseline:

    python -m app.evaluation.report --write

A metric that could not be computed is reported as ``null`` and, if it has a
threshold, fails. That is deliberate: "we did not measure this" must never read
as "this passed". The alternative — treating an absent metric as satisfied —
turns an empty dataset into a green build.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.datasets import EvaluationDatasets, evaluation_root, load_datasets
from app.evaluation.harness import (
    InjectionOutcome,
    IsolationOutcome,
    QueryOutcome,
    default_config,
    run_injection,
    run_isolation,
    run_queries,
)
from app.evaluation.metrics import (
    CostAccount,
    classify,
    mean,
    mean_reciprocal_rank,
    ndcg_at_k,
    percentile,
    rate,
    recall_at_k,
)
from app.evaluation.thresholds import Thresholds, load_thresholds

REPORT_NAME = "baseline.json"

# Ranks at which retrieval is scored. `1` is what a reader actually sees first;
# `5` is roughly what fits in a generation window here.
RECALL_RANKS = (1, 3, 5)
NDCG_RANK = 5


@dataclass(frozen=True)
class Failure:
    """One metric that came in under its declared floor, or was not measured."""

    group: str
    metric: str
    observed: float | None
    floor: float

    def __str__(self) -> str:
        seen = "not measured" if self.observed is None else f"{self.observed:.3f}"
        return f"{self.group}.{self.metric}: {seen} < required {self.floor:.3f}"


def retrieval_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """Ranking quality over the queries that have a right answer.

    Unanswerable queries are excluded rather than scored as misses: they have no
    relevant chunk by construction, so including them would drive every ranking
    metric down by however many of them the dataset happens to contain, which
    says nothing about the ranker.
    """
    scored = [outcome for outcome in outcomes if outcome.case.relevant_ids]
    metrics: dict[str, float | None] = {}
    for rank in RECALL_RANKS:
        values = [
            value
            for outcome in scored
            if (value := recall_at_k(outcome.retrieved_ids, outcome.case.relevant_ids, rank))
            is not None
        ]
        metrics[f"recall_at_{rank}"] = mean(values)
    metrics["mrr"] = mean_reciprocal_rank(
        [(outcome.retrieved_ids, outcome.case.relevant_ids) for outcome in scored]
    )
    metrics[f"ndcg_at_{NDCG_RANK}"] = mean(
        [
            value
            for outcome in scored
            if (value := ndcg_at_k(outcome.retrieved_ids, dict(outcome.case.relevance), NDCG_RANK))
            is not None
        ]
    )
    return metrics


def answer_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """Correctness over answerable queries; faithfulness over the answers given.

    The two denominators differ on purpose. Correctness asks "of the questions we
    could answer, how many did we answer right" — a refusal counts against it.
    Faithfulness asks "of the answers we gave, how many are actually grounded" —
    a refusal is not an answer and cannot be unfaithful, so including refusals
    would let a system that refuses everything score perfectly.
    """
    answerable = [outcome for outcome in outcomes if outcome.case.answerable]
    answered = [outcome for outcome in outcomes if outcome.answered]
    return {
        "correctness": rate(sum(1 for o in answerable if o.correct), len(answerable)),
        "faithfulness": rate(sum(1 for o in answered if o.faithful), len(answered)),
        "answer_rate": rate(len(answered), len(outcomes)),
    }


def citation_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """How much of what was cited belongs, and how much of what belongs was cited.

    Precision counts a cited chunk as correct when the dataset grades it relevant
    at all, including grade 1: a passage on the right topic is a defensible thing
    to cite. Recall is measured against grade 2 alone, because the question is
    whether the passage that actually answers the query was surfaced.
    """
    answerable = [outcome for outcome in outcomes if outcome.case.answerable]
    cited_total = sum(len(outcome.cited_ids) for outcome in answerable)
    cited_relevant = sum(
        1
        for outcome in answerable
        for chunk_id in outcome.cited_ids
        if outcome.case.relevance.get(chunk_id, 0.0) >= 1.0
    )
    wanted_total = sum(len(outcome.case.relevant_ids) for outcome in answerable)
    wanted_cited = sum(
        len(outcome.case.relevant_ids.intersection(outcome.cited_ids)) for outcome in answerable
    )
    # Resolvability spans *every* citation the pipeline emitted, including those
    # on a query labelled unanswerable that it answered anyway. Precision and
    # recall are questions about answerable queries; "does this citation resolve"
    # is a question about the citation, and scoping the two denominators
    # differently would let a failure on an unlabelled answer subtract from a
    # count that never included it — and report resolvability above 1.0.
    emitted = sum(len(outcome.cited_ids) for outcome in outcomes)
    unresolvable = sum(outcome.unresolvable_citations for outcome in outcomes)
    return {
        "precision": rate(cited_relevant, cited_total),
        "recall": rate(wanted_cited, wanted_total),
        # Every citation the pipeline emits must survive the same resolver the
        # public API uses, so this is a rate that has to be 1.0, not a target.
        "resolvable": rate(emitted - unresolvable, emitted),
    }


def claim_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """The share of proposed claims that survived verification with evidence."""
    supported = sum(outcome.supported_claims for outcome in outcomes)
    dropped = sum(outcome.dropped_claims for outcome in outcomes)
    return {"support_rate": rate(supported, supported + dropped)}


def abstention_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """Withholding scored as a binary classifier: predicted abstain vs should abstain.

    Precision is the property that matters most to a reader — an abstention that
    should have been an answer is a question the platform refused for no reason.
    Recall is the property that matters most to trust: answering something the
    evidence does not support is the failure the whole product exists to avoid.
    """
    counts = classify([(outcome.abstained, not outcome.case.answerable) for outcome in outcomes])
    return {
        "precision": counts.precision,
        "recall": counts.recall,
        "accuracy": counts.accuracy,
    }


def injection_metrics(outcomes: Sequence[InjectionOutcome]) -> dict[str, float | None]:
    """Detection scored on the quarantine decision, the one that blocks content."""
    counts = classify([(outcome.quarantined, outcome.is_attack) for outcome in outcomes])
    return {"recall": counts.recall, "precision": counts.precision}


def isolation_metrics(outcomes: Sequence[IsolationOutcome]) -> dict[str, float | None]:
    """Leakage, expressed as the share of probes that stayed contained.

    Stated as containment rather than as a leak count so it reads like every
    other metric — higher is better, and its floor is 1.0. There is no
    acceptable non-zero leak rate, so the threshold is not a target to approach.
    """
    contained = sum(1 for outcome in outcomes if not outcome.leaked)
    return {"containment": rate(contained, len(outcomes))}


def performance_metrics(outcomes: Sequence[QueryOutcome]) -> dict[str, float | None]:
    """Wall-clock cost of the pipeline's own work on this machine.

    Not a production latency figure: the retriever is a stand-in and there is no
    network or database in the loop. It is a regression signal — a change that
    makes the pipeline do materially more work per query shows up here.
    """
    durations = [outcome.seconds for outcome in outcomes]
    return {
        "mean_seconds": mean(durations),
        "p95_seconds": percentile(durations, 0.95),
    }


def cost_summary(outcomes: Sequence[QueryOutcome]) -> dict[str, float | int]:
    """Tokens and money spent. Zero, and recorded rather than assumed.

    The MVP generator is extractive and every model here is local, so nothing is
    sent to a paid service. Reporting the zero keeps the field in the report, so
    the day a hosted model is introduced its cost appears instead of being
    invisible.
    """
    total = CostAccount()
    for outcome in outcomes:
        total = total + outcome.cost
    return {
        "prompt_tokens": total.prompt_tokens,
        "completion_tokens": total.completion_tokens,
        "total_tokens": total.total_tokens,
        "usd": round(total.usd, 6),
    }


def build_report(datasets: EvaluationDatasets) -> dict[str, Any]:
    """Run every suite and assemble the full metric set."""
    queries = run_queries(datasets)
    injection = run_injection(datasets)
    isolation = run_isolation(datasets)
    config = default_config()

    return {
        "dataset_version": datasets.version,
        # The identity of what was actually scored. Version labels are strings
        # someone has to remember to bump, and nothing enforces it — so a report
        # carrying only labels can describe data that has since changed. The
        # digests cannot be forgotten, and the threshold digest covers the floors
        # for the same reason.
        "dataset_digests": dict(datasets.digests),
        "dataset_file_versions": dict(datasets.file_versions),
        "configuration": {
            "top_k": config.top_k,
            "max_evidence": config.max_evidence,
            "min_evidence": config.min_evidence,
            "min_evidence_score": config.min_evidence_score,
        },
        "counts": {
            "corpus_chunks": len(datasets.corpus),
            "scanned_chunks": sum(1 for chunk in datasets.corpus if chunk.scanned),
            "queries": len(datasets.queries),
            "answerable_queries": sum(1 for case in datasets.queries if case.answerable),
            "injection_samples": len(datasets.injection),
            "isolation_probes": len(datasets.isolation),
        },
        "metrics": {
            "retrieval": retrieval_metrics(queries),
            "answers": answer_metrics(queries),
            "citations": citation_metrics(queries),
            "claims": claim_metrics(queries),
            "abstention": abstention_metrics(queries),
            "injection": injection_metrics(injection),
            "isolation": isolation_metrics(isolation),
        },
        # Kept out of `metrics` because nothing here has a floor: a latency on a
        # CI runner is not a promise, and a zero cost is a fact rather than a bar.
        "performance": performance_metrics(queries),
        "cost": cost_summary(queries),
    }


def check(report: dict[str, Any], thresholds: Thresholds) -> list[Failure]:
    """Every declared floor the report does not clear, worst first."""
    failures: list[Failure] = []
    metrics: dict[str, dict[str, float | None]] = report["metrics"]
    for group, floors in thresholds.values.items():
        observed_group = metrics.get(group, {})
        for metric, floor in floors.items():
            observed = observed_group.get(metric)
            if observed is None or observed < floor:
                failures.append(Failure(group, metric, observed, floor))
    failures.sort(key=lambda failure: (failure.observed or -1.0) - failure.floor)
    return failures


def report_path(root: Path | None = None) -> Path:
    return (root or evaluation_root()) / "reports" / REPORT_NAME


def serialize(report: dict[str, Any], thresholds: Thresholds) -> str:
    payload = {
        **report,
        "threshold_version": thresholds.version,
        "threshold_digest": thresholds.digest,
    }
    # Timings differ between machines, so they are dropped from the committed
    # baseline: a report that changed on every run would be reviewed by nobody.
    payload.pop("performance", None)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _main(argv: list[str]) -> int:
    datasets = load_datasets()
    thresholds = load_thresholds()
    report = build_report(datasets)
    failures = check(report, thresholds)

    if "--write" in argv:
        path = report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize(report, thresholds), encoding="utf-8")
        sys.stdout.write(f"wrote {path}\n")
    else:
        sys.stdout.write(serialize(report, thresholds))

    for failure in failures:
        sys.stderr.write(f"FAIL {failure}\n")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main(sys.argv[1:]))


__all__ = [
    "Failure",
    "abstention_metrics",
    "answer_metrics",
    "build_report",
    "check",
    "citation_metrics",
    "claim_metrics",
    "cost_summary",
    "injection_metrics",
    "isolation_metrics",
    "performance_metrics",
    "report_path",
    "serialize",
    "retrieval_metrics",
]
