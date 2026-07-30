"""The labelled data every evaluation number is computed over.

The datasets live as JSON under ``evaluation/datasets/`` at the repository root
rather than inline in test modules, for three reasons the acceptance criteria
turn on: a threshold means nothing unless the data behind it is fixed; the same
corpus has to be readable by a test, by the report generator, and by a reviewer;
and data that is versioned separately from code can be extended without touching
the logic that scores it.

**Nothing here is private.** Every passage is synthetic, written for this
repository, and contains no tenant document, no personal data, and no
credential — the "secrets" quoted inside injection samples are obvious fakes.
That is a hard requirement, not a convenience: an evaluation corpus is read by
CI, printed into reports, and cloned by anyone with the repository.

The manifest records a SHA-256 per file and is verified on load. Editing a
dataset therefore fails the suite until the manifest is refreshed, which makes
"I adjusted the data until the threshold passed" a visible act in a diff rather
than a silent one. Refresh deliberately after changing data:

    python -m app.evaluation.datasets --refresh
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

DATASET_FILES = ("corpus.json", "queries.json", "injection.json", "tenant_isolation.json")
MANIFEST_NAME = "manifest.json"


class DatasetError(Exception):
    """A dataset is missing, malformed, or does not match the manifest."""


class _Record(BaseModel):
    """Base for every dataset row: strictly typed and closed to extra keys.

    Strict, because JSON is a weak enough format that a plausible edit changes
    the meaning of a metric without changing its shape. ``"answerable": "false"``
    is a valid JSON string and a *truthy* Python value, so a lenient loader would
    quietly move a query into the answerable set — and the abstention numbers
    would then describe a dataset nobody wrote. Forbidding unknown keys catches
    the other half: a misspelled field silently doing nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def evaluation_root(start: Path | None = None) -> Path:
    """Locate ``evaluation/`` by walking up to the repository marker.

    The same walk `app.config` uses, and for the same reason: the depth of this
    module inside the source tree is not a fact worth hard-coding, and a relative
    path breaks the moment the package moves or is installed.
    """
    for parent in (start or Path(__file__)).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent / "evaluation"
    message = "repository root not found; evaluation datasets are unreachable"
    raise DatasetError(message)


class CorpusChunk(_Record):
    """One passage of synthetic evidence, with the provenance a citation needs.

    ``ocr_engine`` and ``ocr_confidence`` are what make a chunk *scanned*: they
    stand in for a page that was read from an image rather than from text, so the
    harness can measure whether OCR-derived evidence is scored and cited as
    cautiously as the confidence claims it should be.
    """

    chunk_id: str
    workspace: str
    document: str
    text: str
    language: str
    page_number: int | None
    section: str | None
    ocr_engine: str | None
    ocr_confidence: float | None

    @property
    def scanned(self) -> bool:
        return self.ocr_engine is not None


class QueryCase(_Record):
    """One labelled question against the corpus.

    ``relevance`` maps a chunk id to a graded gain (2 = directly answers,
    1 = related), which is what nDCG needs; an unanswerable case simply has an
    empty mapping. ``answerable`` is kept as its own field rather than inferred
    from that emptiness, because the two can disagree deliberately: a query with
    *only* grade-1 evidence is retrievable but not answerable, and that is the
    case abstention exists for.
    """

    query_id: str
    text: str
    language: str
    answerable: bool
    relevance: dict[str, float]
    expected_quote: str | None
    note: str

    @property
    def relevant_ids(self) -> set[str]:
        """Chunks that directly answer the query — grade 2 and above."""
        return {chunk_id for chunk_id, gain in self.relevance.items() if gain >= 2.0}


class InjectionCase(_Record):
    """One labelled prompt-injection sample."""

    text: str
    is_attack: bool
    category: str | None
    language: str
    note: str


class IsolationCase(_Record):
    """One cross-tenant probe: a reader asking for another workspace's evidence.

    ``leaked`` is never a label here — it is the *outcome* the harness measures.
    The case only records who asked and what they asked for, so leakage is
    computed from behaviour rather than asserted from data.
    """

    case_id: str
    reader_workspace: str
    target_chunk_id: str
    query: str
    note: str


class EvaluationDatasets(BaseModel):
    """Every labelled set, plus the versions they were loaded at.

    ``version`` is the manifest's — the version of the collection as a whole.
    ``file_versions`` carries each dataset's own, because they move
    independently: adding injection samples is a change to that contract and to
    nothing else, and forcing one number to cover all four would either
    over-report churn or hide it.

    ``digests`` is the identity a report needs. A version label is a string
    someone remembered to bump; a digest is what the numbers were actually
    computed over, and it cannot be forgotten.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    digests: dict[str, str]
    file_versions: dict[str, str]
    corpus: tuple[CorpusChunk, ...]
    queries: tuple[QueryCase, ...]
    injection: tuple[InjectionCase, ...]
    isolation: tuple[IsolationCase, ...]

    def chunk(self, chunk_id: str) -> CorpusChunk:
        for chunk in self.corpus:
            if chunk.chunk_id == chunk_id:
                return chunk
        message = f"no corpus chunk {chunk_id!r}"
        raise DatasetError(message)

    def workspace_corpus(self, workspace: str) -> tuple[CorpusChunk, ...]:
        return tuple(chunk for chunk in self.corpus if chunk.workspace == workspace)


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as error:
        message = f"evaluation dataset {path.name} is missing"
        raise DatasetError(message) from error


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        message = f"evaluation dataset {path.name} is missing"
        raise DatasetError(message) from error
    except json.JSONDecodeError as error:
        message = f"evaluation dataset {path.name} is not valid JSON: {error}"
        raise DatasetError(message) from error


def _verify(root: Path, manifest: dict[str, Any]) -> None:
    """Fail unless every dataset file hashes to what the manifest recorded."""
    recorded = manifest.get("datasets", {})
    for name in DATASET_FILES:
        path = root / "datasets" / name
        if name not in recorded:
            message = f"{name} is not listed in {MANIFEST_NAME}"
            raise DatasetError(message)
        actual = _digest(path)
        if actual != recorded[name]:
            message = (
                f"{name} does not match {MANIFEST_NAME} "
                f"(recorded {recorded[name][:12]}…, found {actual[:12]}…). "
                "Refresh the manifest deliberately: python -m app.evaluation.datasets --refresh"
            )
            raise DatasetError(message)


def load_datasets(root: Path | None = None) -> EvaluationDatasets:
    """Read, verify, and parse every evaluation dataset.

    A validation failure is re-raised as a :class:`DatasetError` naming the file,
    because a Pydantic traceback tells a reader what type was wrong but not which
    of four datasets it came from.
    """
    base = root or evaluation_root()
    manifest = _read_json(base / MANIFEST_NAME)
    _verify(base, manifest)
    data = {name: _read_json(base / "datasets" / name) for name in DATASET_FILES}

    try:
        return EvaluationDatasets(
            version=str(manifest["version"]),
            digests={name: str(digest) for name, digest in manifest["datasets"].items()},
            file_versions={name: str(payload["version"]) for name, payload in data.items()},
            corpus=tuple(CorpusChunk(**entry) for entry in data["corpus.json"]["chunks"]),
            queries=tuple(QueryCase(**entry) for entry in data["queries.json"]["queries"]),
            injection=tuple(InjectionCase(**entry) for entry in data["injection.json"]["samples"]),
            isolation=tuple(
                IsolationCase(**entry) for entry in data["tenant_isolation.json"]["cases"]
            ),
        )
    except ValidationError as error:
        message = f"an evaluation dataset record is invalid: {error}"
        raise DatasetError(message) from error
    except (KeyError, TypeError) as error:
        message = f"an evaluation dataset is missing a required key: {error}"
        raise DatasetError(message) from error


def refresh_manifest(root: Path | None = None) -> dict[str, str]:
    """Rewrite the recorded digests to match the files on disk.

    Separate from loading and never called by it: recomputing a hash during a
    test run would defeat the check entirely, since any edit would then verify
    against itself.
    """
    base = root or evaluation_root()
    manifest_path = base / MANIFEST_NAME
    manifest = _read_json(manifest_path)
    digests = {name: _digest(base / "datasets" / name) for name in DATASET_FILES}
    manifest["datasets"] = digests
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digests


def _main(argv: list[str]) -> int:
    if "--refresh" not in argv:
        sys.stderr.write("usage: python -m app.evaluation.datasets --refresh\n")
        return 2
    for name, digest in refresh_manifest().items():
        sys.stdout.write(f"{digest}  {name}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main(sys.argv[1:]))


__all__ = [
    "CorpusChunk",
    "DatasetError",
    "EvaluationDatasets",
    "InjectionCase",
    "IsolationCase",
    "QueryCase",
    "evaluation_root",
    "load_datasets",
    "refresh_manifest",
]
