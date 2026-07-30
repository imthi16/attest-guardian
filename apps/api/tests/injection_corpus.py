"""Versioned prompt-injection evaluation corpus.

The corpus is the measurable regression contract for the detector: it pairs
labelled attack and benign samples across languages (English, Tamil, Tanglish)
and attack families, so recall/precision can be asserted and can only improve.
Bumping ``CORPUS_VERSION`` signals an intentional change to the contract.

The samples themselves live in ``evaluation/datasets/injection.json``, alongside
the rest of the evaluation data, so the detector's own suite and the
cross-cutting evaluation report score exactly the same corpus. Two copies of a
labelled set is worse than either copy alone: they drift, and the two suites then
disagree about what the detector's recall actually is. This module is the reading
of that file into the shapes the detector's tests already use.

Samples are synthetic and contain no secrets, PII, or private documents — the
"secrets" referenced in attack strings are obvious fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from app.evaluation.datasets import EvaluationDatasets, load_datasets
from app.safety.types import InjectionCategory

INJECTION_DATASET = "injection.json"


@dataclass(frozen=True)
class CorpusSample:
    """One labelled sample: the text, whether it is an attack, and its family."""

    text: str
    is_attack: bool
    category: InjectionCategory | None
    language: str  # "en" | "ta" | "tanglish"
    note: str


@cache
def _datasets() -> EvaluationDatasets:
    """Load once per session: every call verifies a SHA-256 over the files."""
    return load_datasets()


def corpus_version() -> str:
    """The corpus's own declared version, read rather than restated.

    A constant here would be a second place the version lives, and the one that
    could be right while the data it describes had changed.
    """
    return _datasets().file_versions[INJECTION_DATASET]


def samples() -> tuple[CorpusSample, ...]:
    return tuple(
        CorpusSample(
            text=case.text,
            is_attack=case.is_attack,
            category=InjectionCategory(case.category) if case.category else None,
            language=case.language,
            note=case.note,
        )
        for case in _datasets().injection
    )


def attacks() -> tuple[CorpusSample, ...]:
    return tuple(sample for sample in samples() if sample.is_attack)


def benign() -> tuple[CorpusSample, ...]:
    return tuple(sample for sample in samples() if not sample.is_attack)


__all__ = ["CorpusSample", "attacks", "benign", "corpus_version", "samples"]
