"""The labelled data itself: it loads, it is what the manifest says, and it covers.

Two kinds of check live here. The first is integrity — a dataset that can be
edited without anyone noticing is not a versioned contract, so the digest check
is tested rather than trusted. The second is coverage: thresholds computed over
a corpus with no Tamil, no scanned page, or no second workspace would be green
and meaningless, so the facets the product claims to handle are asserted to be
present in the data before any metric is computed over it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from app.evaluation.datasets import (
    DATASET_FILES,
    DatasetError,
    evaluation_root,
    load_datasets,
    refresh_manifest,
)
from app.evaluation.thresholds import load_thresholds

DATASETS = load_datasets()


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A writable copy of the evaluation tree, so tampering tests touch no source."""
    destination = tmp_path / "evaluation"
    shutil.copytree(evaluation_root(), destination)
    return destination


def test_every_dataset_loads_and_declares_a_version() -> None:
    assert DATASETS.version
    assert set(DATASETS.file_versions) == set(DATASET_FILES)
    assert all(version for version in DATASETS.file_versions.values())


def test_an_edited_dataset_fails_until_the_manifest_is_refreshed(sandbox: Path) -> None:
    """Otherwise "tune the data until the threshold passes" leaves no trace.

    The digest is what makes editing a corpus a visible act: the suite fails
    until someone refreshes the manifest, which puts the change in the diff.
    """
    corpus = sandbox / "datasets" / "corpus.json"
    payload = json.loads(corpus.read_text(encoding="utf-8"))
    payload["chunks"][0]["text"] = "An answer inserted to make a metric pass."
    corpus.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="does not match manifest.json"):
        load_datasets(sandbox)

    refresh_manifest(sandbox)
    assert load_datasets(sandbox).chunk("alpha-invoice-terms").text.startswith("An answer inserted")


def test_a_dataset_missing_from_the_manifest_is_refused(sandbox: Path) -> None:
    manifest = sandbox / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    del payload["datasets"]["queries.json"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="not listed"):
        load_datasets(sandbox)


def test_a_missing_dataset_file_names_itself(sandbox: Path) -> None:
    (sandbox / "datasets" / "queries.json").unlink()

    with pytest.raises(DatasetError, match="queries.json"):
        load_datasets(sandbox)


def test_malformed_json_is_reported_rather_than_crashing(sandbox: Path) -> None:
    # Refreshed first, so the digest check passes and the parse is what fails —
    # otherwise this would only re-test the tamper detection above.
    (sandbox / "datasets" / "queries.json").write_text("{not json", encoding="utf-8")
    refresh_manifest(sandbox)

    with pytest.raises(DatasetError, match="not valid JSON"):
        load_datasets(sandbox)


def test_unreachable_repository_root_is_an_explicit_error(tmp_path: Path) -> None:
    # No AGENTS.md above tmp_path, so the walk finds no repository.
    with pytest.raises(DatasetError, match="repository root not found"):
        evaluation_root(tmp_path / "nowhere")


def test_chunk_ids_are_unique() -> None:
    ids = [chunk.chunk_id for chunk in DATASETS.corpus]
    assert len(ids) == len(set(ids))


def test_query_ids_are_unique() -> None:
    ids = [case.query_id for case in DATASETS.queries]
    assert len(ids) == len(set(ids))


def test_every_graded_chunk_exists() -> None:
    """A relevance grade pointing at nothing would silently deflate recall."""
    known = {chunk.chunk_id for chunk in DATASETS.corpus}
    for case in DATASETS.queries:
        assert set(case.relevance) <= known, case.query_id


def test_the_corpus_covers_all_three_languages() -> None:
    assert {"eng", "tam", "tanglish"} <= {chunk.language for chunk in DATASETS.corpus}


def test_queries_cover_all_three_languages() -> None:
    answerable = [case for case in DATASETS.queries if case.answerable]
    assert {"eng", "tam", "tanglish"} <= {case.language for case in answerable}


def test_scanned_pages_are_represented_including_an_unknown_confidence() -> None:
    """OCR reliability has three states, and the least safe one must be in the data.

    A scanned page whose engine recorded *no* confidence is of unknown quality,
    which is distinct from a low score and must never be treated as a good
    reading. If the corpus held only confident scans, nothing would exercise it.
    """
    scanned = [chunk for chunk in DATASETS.corpus if chunk.scanned]

    assert len(scanned) >= 3
    assert any(
        chunk.ocr_confidence is not None and chunk.ocr_confidence >= 0.9 for chunk in scanned
    )
    assert any(chunk.ocr_confidence is not None and chunk.ocr_confidence < 0.5 for chunk in scanned)
    assert any(chunk.ocr_confidence is None for chunk in scanned)


def test_unanswerable_queries_include_one_with_related_evidence() -> None:
    """The hard abstention case: retrieval succeeds and the answer must still be withheld.

    Without it, "abstains on unanswerable questions" would only ever mean
    "abstains when it found nothing", which is the easy half of the problem.
    """
    unanswerable = [case for case in DATASETS.queries if not case.answerable]

    assert len(unanswerable) >= 3
    assert any(case.relevance for case in unanswerable)
    assert any(not case.relevance for case in unanswerable)


def test_every_answerable_query_states_the_fact_it_expects() -> None:
    for case in DATASETS.queries:
        if case.answerable:
            assert case.expected_quote, case.query_id
            assert case.relevant_ids, case.query_id


def test_two_workspaces_hold_contradicting_passages() -> None:
    """Leakage has to be detectable in the answer text, not only in an id.

    If both tenants' clauses said the same thing, an answer built from the wrong
    workspace would read identically to a correct one and the containment metric
    would only catch the citations.
    """
    alpha = {chunk.text for chunk in DATASETS.workspace_corpus("alpha")}
    beta = {chunk.text for chunk in DATASETS.workspace_corpus("beta")}

    assert alpha and beta
    assert not alpha & beta


def test_every_isolation_probe_targets_another_workspace() -> None:
    """A probe against one's own workspace would pass by doing nothing."""
    for case in DATASETS.isolation:
        target = DATASETS.chunk(case.target_chunk_id)
        assert target.workspace != case.reader_workspace, case.case_id


def test_isolation_is_probed_in_both_directions() -> None:
    assert len({case.reader_workspace for case in DATASETS.isolation}) >= 2


def test_the_injection_corpus_covers_families_and_languages() -> None:
    attacks = [case for case in DATASETS.injection if case.is_attack]

    assert len({case.category for case in attacks if case.category}) >= 6
    assert {"en", "ta", "tanglish"} <= {case.language for case in attacks}
    assert any(not case.is_attack for case in DATASETS.injection)


def test_asking_for_an_unknown_chunk_names_it() -> None:
    with pytest.raises(DatasetError, match="no corpus chunk"):
        DATASETS.chunk("does-not-exist")


def test_thresholds_load_and_reject_an_undeclared_metric() -> None:
    thresholds = load_thresholds()

    assert thresholds.version
    assert thresholds.floor("isolation", "containment") == 1.0
    with pytest.raises(DatasetError, match="no threshold for"):
        thresholds.floor("isolation", "invented")
    with pytest.raises(DatasetError, match="no threshold group"):
        thresholds.group("invented")


def test_missing_thresholds_file_is_reported(sandbox: Path) -> None:
    (sandbox / "thresholds.json").unlink()

    with pytest.raises(DatasetError, match="thresholds.json is missing"):
        load_thresholds(sandbox)


def test_malformed_thresholds_file_is_reported(sandbox: Path) -> None:
    (sandbox / "thresholds.json").write_text("{", encoding="utf-8")

    with pytest.raises(DatasetError, match="not valid JSON"):
        load_thresholds(sandbox)


def test_a_threshold_that_cannot_fail_is_refused(sandbox: Path) -> None:
    """`NaN` is the dangerous value: every comparison against it is false.

    JSON carries it as the string "NaN", `float()` accepts it, and `observed <
    NaN` then never fires — so the metric passes forever however far it
    regresses, while the report still displays a bar. A threshold that cannot
    fail is worse than no threshold at all.
    """
    thresholds = sandbox / "thresholds.json"
    payload = json.loads(thresholds.read_text(encoding="utf-8"))
    payload["thresholds"]["isolation"]["containment"] = "NaN"
    thresholds.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="not finite"):
        load_thresholds(sandbox)


def test_a_threshold_outside_the_unit_range_is_refused(sandbox: Path) -> None:
    """Every metric here is a rate, so a floor of 12 is a typo, not a strict bar."""
    thresholds = sandbox / "thresholds.json"
    payload = json.loads(thresholds.read_text(encoding="utf-8"))
    payload["thresholds"]["isolation"]["containment"] = 12
    thresholds.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match=r"rate in \[0, 1\]"):
        load_thresholds(sandbox)


def test_a_non_numeric_threshold_is_refused(sandbox: Path) -> None:
    thresholds = sandbox / "thresholds.json"
    payload = json.loads(thresholds.read_text(encoding="utf-8"))
    payload["thresholds"]["isolation"]["containment"] = "high"
    thresholds.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError, match="not a number"):
        load_thresholds(sandbox)


def test_a_string_where_a_boolean_belongs_is_refused(sandbox: Path) -> None:
    """`"answerable": "false"` is valid JSON, truthy in Python, and a silent lie.

    A lenient loader would move the query into the answerable set, and the
    abstention numbers would then describe a dataset nobody wrote.
    """
    queries = sandbox / "datasets" / "queries.json"
    payload = json.loads(queries.read_text(encoding="utf-8"))
    payload["queries"][-1]["answerable"] = "false"
    queries.write_text(json.dumps(payload), encoding="utf-8")
    refresh_manifest(sandbox)

    with pytest.raises(DatasetError, match="invalid"):
        load_datasets(sandbox)


def test_an_unknown_field_is_refused_rather_than_ignored(sandbox: Path) -> None:
    """A misspelled key that silently does nothing is a label nobody applied."""
    queries = sandbox / "datasets" / "queries.json"
    payload = json.loads(queries.read_text(encoding="utf-8"))
    payload["queries"][-1]["answerble"] = True
    queries.write_text(json.dumps(payload), encoding="utf-8")
    refresh_manifest(sandbox)

    with pytest.raises(DatasetError, match="invalid"):
        load_datasets(sandbox)


def test_unanswerable_queries_cover_all_three_languages() -> None:
    """Abstention measured only in English stays green while Tamil regresses.

    And each language needs the hard case too — a question whose topic is
    covered but whose answer is not — because "found nothing, so refused" is the
    easy half of abstention in any script.
    """
    unanswerable = [case for case in DATASETS.queries if not case.answerable]
    languages = {case.language for case in unanswerable}

    assert {"eng", "tam", "tanglish"} <= languages
    for language in ("eng", "tam", "tanglish"):
        related = [case for case in unanswerable if case.language == language and case.relevance]
        assert related, f"no related-but-insufficient case in {language}"
