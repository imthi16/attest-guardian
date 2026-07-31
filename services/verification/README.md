# Verification boundary

Atomic claim extraction, evidence matching, contradiction checks, calibrated confidence, and
abstention.

**Implemented in `apps/api/app/`** — `verification/` (claim entailment and the confidence signals),
`decision/` (the calibrated policy and abstention reasons), and `citations/` (resolution against
stored content).

The rule that shapes this boundary: a model's self-reported confidence is never a confidence score.
Confidence blends retrieval, rerank, OCR, and query-overlap signals — and OCR text with *no*
recorded confidence scores as unknown, not as perfect, which was a real defect the evaluation
found.

See [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md#grounded-answer-pipeline) and
[`docs/EVALUATION.md`](../../docs/EVALUATION.md).
