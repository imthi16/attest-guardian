# Evaluation tests

The evaluation framework lives where it can import the pipeline it scores:

- **Data** — `evaluation/datasets/` (versioned, digest-verified), with the floors in
  `evaluation/thresholds.json` and the committed baseline in `evaluation/reports/baseline.json`.
- **Code** — `apps/api/app/evaluation/` (metrics, dataset loader, harness, report generator).
- **Suites** — `apps/api/tests/evaluation/`, so they run under the existing `pytest` gate.

Run it with `make evaluate`. See [`docs/EVALUATION.md`](../../docs/EVALUATION.md) for the baseline,
what each metric means, and the known limitations.
