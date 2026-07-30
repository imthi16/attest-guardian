"""The measured verdict: every declared floor, and the properties behind them.

The single most important test here is the first one — every metric clears its
threshold. The rest exist because a green aggregate can hide a specific failure:
a corpus where nothing is ever cited would report perfect faithfulness, and a
pipeline that refused everything would report perfect precision. So the facets
the aggregate could mask are asserted individually.

The committed baseline is checked too. A report that drifted from the file in
the repository would make the documented numbers fiction, and the fiction would
be discovered by a reader rather than by CI.
"""

from __future__ import annotations

import json

from app.evaluation.datasets import load_datasets
from app.evaluation.harness import (
    QueryOutcome,
    default_config,
    run_injection,
    run_isolation,
    run_queries,
)
from app.evaluation.report import (
    RECALL_RANKS,
    Failure,
    build_report,
    check,
    report_path,
    retrieval_metrics,
    serialize,
)
from app.evaluation.thresholds import load_thresholds
from app.rag.types import AnswerOutcome

DATASETS = load_datasets()
THRESHOLDS = load_thresholds()
OUTCOMES = run_queries(DATASETS)
REPORT = build_report(DATASETS)


def outcome(query_id: str) -> QueryOutcome:
    for result in OUTCOMES:
        if result.case.query_id == query_id:
            return result
    message = f"no evaluated query {query_id!r}"
    raise AssertionError(message)


def test_every_metric_clears_its_declared_floor() -> None:
    failures = check(REPORT, THRESHOLDS)

    assert not failures, "\n".join(str(failure) for failure in failures)


def test_every_declared_threshold_matches_a_reported_metric() -> None:
    """A floor on a metric nobody computes is a promise nothing enforces."""
    metrics = REPORT["metrics"]
    for group, floors in THRESHOLDS.values.items():
        assert group in metrics, group
        for metric in floors:
            assert metric in metrics[group], f"{group}.{metric}"


def test_an_unmeasured_metric_fails_rather_than_passing() -> None:
    """ "We did not measure this" must never read as "this passed".

    An empty dataset, a renamed metric, or a suite that silently skipped would
    otherwise produce a green build on no evidence at all.
    """
    blank = {"metrics": {"isolation": {"containment": None}}}
    thresholds = load_thresholds()

    failures = check(blank, thresholds)

    assert Failure("isolation", "containment", None, 1.0) in failures


def test_check_reports_the_worst_shortfall_first() -> None:
    """So a long failure list opens with the thing most worth reading."""
    degraded = json.loads(json.dumps(REPORT))
    degraded["metrics"]["isolation"]["containment"] = 0.99  # barely under a 1.0 floor
    degraded["metrics"]["answers"]["correctness"] = 0.1  # far under a 0.9 floor

    failures = check(degraded, THRESHOLDS)

    assert [(failure.group, failure.metric) for failure in failures] == [
        ("answers", "correctness"),
        ("isolation", "containment"),
    ]


def test_the_committed_baseline_matches_a_fresh_run() -> None:
    """Otherwise the documented numbers are fiction the next reader discovers.

    Regenerate deliberately after a change that moves a metric:
        python -m app.evaluation.report --write
    """
    committed = json.loads(report_path().read_text(encoding="utf-8"))
    # Through the same serializer the CLI uses, so the comparison cannot drift
    # from what `--write` would actually produce.
    fresh = json.loads(serialize(REPORT, THRESHOLDS))

    assert committed == fresh


def test_answerable_queries_are_answered_correctly_in_every_language() -> None:
    """A single-language aggregate would let Tamil or Tanglish regress unseen."""
    for language in ("eng", "tam", "tanglish"):
        cases = [
            result
            for result in OUTCOMES
            if result.case.answerable and result.case.language == language
        ]
        assert cases, language
        assert all(result.correct for result in cases), language


def test_scanned_evidence_is_answered_and_cited_like_any_other() -> None:
    """OCR text is evidence too: a passage read from an image must still ground.

    Including the page whose engine recorded no confidence at all — unknown
    reliability is a reason to say so in the answer, not a reason to lose it.
    """
    for query_id in ("q-warranty-scanned", "q-shipping-scanned", "q-service-scanned-ta"):
        result = outcome(query_id)
        assert result.answered, query_id
        assert result.correct, query_id
        assert result.cited_ids, query_id


def test_no_answer_ever_quotes_something_its_source_does_not_say() -> None:
    """The property the product exists for. Anything less is a fabricated citation."""
    for result in OUTCOMES:
        assert result.quotes_verbatim, result.case.query_id
        assert result.unresolvable_citations == 0, result.case.query_id


def test_every_citation_survives_the_resolver_the_api_uses() -> None:
    """Generation and resolution must agree, or evidence works live and not on reload."""
    assert REPORT["metrics"]["citations"]["resolvable"] == 1.0


def test_a_question_with_no_evidence_is_refused_outright() -> None:
    for query_id in ("q-unanswerable-sport", "q-unanswerable-recipe"):
        result = outcome(query_id)
        assert result.outcome is AnswerOutcome.ABSTAINED, query_id
        assert not result.cited_ids, query_id


def test_abstention_never_withholds_an_answer_the_evidence_supported() -> None:
    """Precision over recall: refusing an answerable question is a visible failure.

    The reverse — answering when the evidence is thin — is caught by recall,
    which the baseline does not yet reach; see docs/EVALUATION.md.
    """
    withheld = [result for result in OUTCOMES if result.abstained and result.case.answerable]

    assert not withheld, [result.case.query_id for result in withheld]


def test_no_probe_reaches_another_workspace_evidence() -> None:
    """Not a proof of tenant isolation — a proof the pipeline adds no leak of its own.

    The repository scoping and row-level security that actually fence a query are
    proven against a real database in the integration suite. What this shows is
    that nothing downstream of retrieval reintroduces content retrieval withheld,
    which no database test covers.
    """
    leaked = [result for result in run_isolation(DATASETS) if result.leaked]

    assert not leaked, [result.case.case_id for result in leaked]


def test_every_labelled_attack_is_quarantined_and_no_clean_passage_is() -> None:
    results = run_injection(DATASETS)
    missed = [result.note for result in results if result.is_attack and not result.quarantined]
    over = [result.note for result in results if not result.is_attack and result.quarantined]

    assert not missed, missed
    assert not over, over


def test_retrieval_metrics_ignore_queries_with_no_right_answer() -> None:
    """Scoring them as misses would measure the corpus, not the ranker."""
    answerable = [result for result in OUTCOMES if result.case.relevant_ids]
    unanswerable = [result for result in OUTCOMES if not result.case.relevant_ids]

    assert unanswerable, "the dataset must contain unanswerable queries"
    assert retrieval_metrics(OUTCOMES) == retrieval_metrics(answerable)


def test_the_report_records_what_it_was_run_over() -> None:
    """A metric with no record of its inputs cannot be reproduced or argued with."""
    assert REPORT["dataset_version"] == DATASETS.version
    assert REPORT["counts"]["queries"] == len(DATASETS.queries)
    assert REPORT["counts"]["scanned_chunks"] >= 3
    assert REPORT["configuration"]["min_evidence_score"] > 0.0


def test_the_run_costs_nothing_and_says_so() -> None:
    """No paid service is reachable from CI, and the report states the zero.

    Recorded rather than assumed: the field is what makes a hosted model's cost
    appear the day one is introduced, instead of going unmeasured.
    """
    assert REPORT["cost"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "usd": 0.0,
    }


def test_timings_are_reported_but_carry_no_threshold() -> None:
    """A duration on a CI runner is a regression signal, not a promise.

    So it stays out of `metrics`, where everything has a floor, and out of the
    committed baseline, which would otherwise change on every run.
    """
    assert REPORT["performance"]["mean_seconds"] > 0.0
    assert "performance" not in THRESHOLDS.values
    # Nearest-rank, so the p95 is one of the observed durations and cannot come
    # in under the mean of the same sample.
    assert REPORT["performance"]["p95_seconds"] >= REPORT["performance"]["mean_seconds"]


def test_retrieval_is_scored_before_the_evidence_gate_truncates() -> None:
    """Reading ranks off the surviving evidence would measure the cap, not the ranker.

    `max_evidence` is 4, so a Recall@5 computed over `evidence_ids` could never
    inspect a fifth result: a relevant chunk at rank 5 would register as a miss
    no matter how much the ranking improved.
    """
    config = default_config()
    assert config.max_evidence < max(RECALL_RANKS)

    widest = max(len(result.retrieved_ids) for result in OUTCOMES)
    assert widest > config.max_evidence, "no query retrieves past the cap; the test proves nothing"
    for result in OUTCOMES:
        assert len(result.evidence_ids) <= config.max_evidence
        assert set(result.evidence_ids) <= set(result.retrieved_ids)


def test_resolvability_covers_every_citation_the_pipeline_emitted() -> None:
    """Including citations on a query it answered but should not have.

    Scoping the numerator to all outcomes and the denominator to answerable ones
    lets a failure subtract from a count that never included it — and report a
    rate above 1.0.
    """
    emitted = sum(len(result.cited_ids) for result in OUTCOMES)
    answerable_only = sum(len(r.cited_ids) for r in OUTCOMES if r.case.answerable)

    assert emitted > answerable_only, "no unanswerable query was answered; the test proves nothing"
    resolvable = REPORT["metrics"]["citations"]["resolvable"]
    assert resolvable is not None
    assert 0.0 <= resolvable <= 1.0


def test_the_report_identifies_the_data_and_floors_it_used() -> None:
    """A version label is a string someone has to remember to bump; a digest is not.

    Without them a report can claim to have been measured against data and bars
    that have since changed, which makes every number in it unreproducible.
    """
    assert REPORT["dataset_digests"] == DATASETS.digests
    assert set(REPORT["dataset_file_versions"]) == set(DATASETS.file_versions)

    serialized = json.loads(serialize(REPORT, THRESHOLDS))
    assert serialized["threshold_digest"] == THRESHOLDS.digest
    assert len(serialized["threshold_digest"]) == 64


def test_a_scan_with_no_recorded_confidence_scores_below_a_good_one() -> None:
    """Unknown reliability is not high reliability, and must not price as if it were.

    The engine read the page and declined to say how well — strictly less
    information than a measured score. Scoring it as born-digital text would make
    the least verifiable evidence in a workspace indistinguishable from the most.
    """
    unknown = outcome("q-service-scanned-ta")
    confident = outcome("q-warranty-scanned")
    born_digital = outcome("q-notice-en")

    assert DATASETS.chunk(unknown.cited_ids[0]).ocr_confidence is None
    assert unknown.confidence < confident.confidence
    assert unknown.confidence < born_digital.confidence
    # But not treated as worthless either: a scan from an engine that reports no
    # confidence is still usable evidence, and refusing every one of them would
    # withhold answers from whole documents.
    assert unknown.answered
