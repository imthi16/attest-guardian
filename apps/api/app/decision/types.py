"""Types for the confidence-and-abstention decision policy.

The policy turns the *aggregated* signals of one answered query into a single
operational decision. It never uses a model's self-reported confidence; every
input is an objective signal produced upstream:

* ``verifier_confidence`` — the mean calibrated confidence of the supported
  claims, which itself blends lexical, dense (vector), reranker, OCR, and
  normalization signals in the verifier;
* the per-verdict claim counts — how many claims were supported, partially
  supported, contradicted, or unsupported;
* ``evidence_count`` / ``retrieved_count`` — evidence coverage;
* ``min_ocr_confidence`` — the least reliable OCR source among cited evidence.

Keeping the signals in one dataclass makes the decision reproducible and easy to
log without exposing document text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionOutcome(StrEnum):
    """The operational decision for one answered query."""

    ANSWER = "answer"
    ANSWER_WITH_WARNING = "answer_with_warning"
    ASK_FOR_CLARIFICATION = "ask_for_clarification"
    ABSTAIN = "abstain"
    ESCALATE_FOR_REVIEW = "escalate_for_review"

    @property
    def is_answering(self) -> bool:
        """Whether this outcome surfaces an answer (vs. withholding one)."""
        return self in (DecisionOutcome.ANSWER, DecisionOutcome.ANSWER_WITH_WARNING)


@dataclass(frozen=True)
class DecisionSignals:
    """The objective signals a decision is calibrated from.

    ``verifier_confidence`` and ``min_ocr_confidence`` are ``None`` when the
    signal is genuinely absent (no supported claim; no OCR-derived evidence),
    which the policy treats deterministically rather than as a zero.
    """

    supported_claims: int
    partial_claims: int
    contradicted_claims: int
    unsupported_claims: int
    evidence_count: int
    retrieved_count: int
    verifier_confidence: float | None = None
    min_ocr_confidence: float | None = None


@dataclass(frozen=True)
class DecisionResult:
    """The chosen outcome, its confidence, and a non-sensitive explanation."""

    outcome: DecisionOutcome
    confidence: float
    reason: str
