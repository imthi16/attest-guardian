# Evaluation

Attest Guardian answers only from evidence and abstains when the evidence is insufficient. Those
are measurable claims, so they are measured: one metric set, over one versioned corpus, against
declared floors, on every CI run.

```bash
make evaluate           # score the pipeline and print the report
make evaluate-write     # regenerate the committed baseline after an intended change
make evaluate-refresh   # re-record dataset digests after deliberately editing a dataset
```

`make check` runs it too, and the suites under `apps/api/tests/evaluation/` run inside `pytest`,
so a regression fails a build rather than waiting to be noticed.

## What it runs on

Nothing here needs a database, a network, a GPU, or a paid model. The corpus is synthetic prose
written for this repository — no tenant document, no personal data, no real credential; the
"secrets" quoted inside the injection samples are obvious fakes. That is a requirement rather than
a convenience: an evaluation corpus is read by CI, printed into reports, and cloned by anyone with
the repository.

| File | Holds |
| --- | --- |
| `evaluation/datasets/corpus.json` | Evidence passages in English, Tamil, and Tanglish, across two workspaces, including three scanned (OCR-derived) pages |
| `evaluation/datasets/queries.json` | Labelled questions with graded relevance, answerable and unanswerable |
| `evaluation/datasets/injection.json` | Labelled prompt-injection attacks and benign passages across three languages |
| `evaluation/datasets/tenant_isolation.json` | Cross-tenant probes in both directions |
| `evaluation/manifest.json` | Version and a SHA-256 per dataset |
| `evaluation/thresholds.json` | The floor every metric must clear |
| `evaluation/reports/baseline.json` | The committed measured baseline |

The manifest digests are verified on load, so editing a dataset fails the suite until the manifest
is refreshed. The point is that *tuning the data until a threshold passes* is a visible act in a
diff rather than a silent one. The same applies to the baseline: a test asserts the committed
report equals a fresh run, so numbers in this document cannot quietly become fiction.

The scanned pages deliberately cover all three OCR states — a confident reading (0.91), a poor one
(0.42), and one where the engine recorded **no** confidence at all. The last is unknown
reliability, which is not the same as low, and must never be treated as a good reading.

## Baseline

Dataset version `2026-07-v1`, thresholds `2026-07-v1`. 16 chunks, 14 queries (11 answerable),
30 injection samples, 5 isolation probes.

| Group | Metric | Measured | Floor |
| --- | --- | --- | --- |
| retrieval | Recall@1 | 1.00 | 0.90 |
| retrieval | Recall@3 | 1.00 | 1.00 |
| retrieval | Recall@5 | 1.00 | 1.00 |
| retrieval | MRR | 1.00 | 0.90 |
| retrieval | nDCG@5 | 0.91 | 0.85 |
| answers | correctness | 1.00 | 0.90 |
| answers | faithfulness | 1.00 | 1.00 |
| citations | precision | 0.67 | 0.60 |
| citations | recall | 1.00 | 0.90 |
| citations | resolvable | 1.00 | 1.00 |
| claims | support rate | 1.00 | 0.80 |
| abstention | precision | 1.00 | 0.90 |
| abstention | recall | 0.67 | 0.60 |
| injection | recall | 1.00 | 1.00 |
| injection | precision | 1.00 | 1.00 |
| isolation | containment | 1.00 | 1.00 |

Latency and cost are reported but carry no floor. The mean run is ~11 ms per query on a developer
machine, which is a regression signal and not a production latency: the retriever is a stand-in and
there is no database or network in the loop. Cost is **zero tokens and zero dollars**, recorded
rather than assumed — the MVP generator is extractive and every model is local. The field exists so
that the day a hosted model is introduced, its cost appears in the report instead of going
unmeasured.

## What the numbers mean

**Correctness and faithfulness have different denominators, on purpose.** Correctness asks "of the
questions we could answer, how many did we answer right", so a refusal counts against it.
Faithfulness asks "of the answers we gave, how many are actually grounded", so a refusal is
excluded — a system that refused everything would otherwise score a perfect 1.00.

**An unmeasured metric fails.** A metric that could not be computed is reported as `null` and does
not clear its floor. Treating an absent number as satisfied would turn an empty dataset into a
green build, which is the failure mode a quality gate exists to prevent. The same rule runs through
`app/evaluation/metrics.py`: precision over zero predictions and recall over zero relevant items
are `None`, never `1.0`.

**Retrieval metrics skip unanswerable queries.** They have no relevant chunk by construction, so
scoring them as misses would drag every ranking metric down by however many the dataset happens to
contain — a measurement of the corpus rather than of the ranker.

**Citation precision counts grade-1 evidence as correct** (a passage on the right topic is a
defensible thing to cite), while citation recall is measured against grade 2 alone (did the passage
that actually answers the question get surfaced).

**Isolation containment is not a proof of tenant isolation.** The harness substitutes the data
layer, so what it proves is that nothing downstream of retrieval reintroduces content retrieval
withheld — no cache, no cross-run state, no citation resolving outside the authorized set. The
repository scoping and PostgreSQL row-level security that actually fence a query are proven against
a real database in `apps/api/tests/integration/`. Neither check substitutes for the other, and the
probes are written so that a leak would be visible in the answer *text*: the two tenants' clauses
contradict each other (thirty days against sixty, ninety against thirty, monthly against weekly).

## Known limitations

These are recorded rather than tuned away. A dataset written to expose a weakness should not be
adjusted until the weakness stops showing.

- **Abstention recall is 0.67.** Two of the three unanswerable queries are refused. The third —
  "what is the training budget for the marketing team" — retrieves a passage that mentions training
  budgets without answering the question, and the pipeline answers from it. No score threshold
  fixes this; it needs semantic matching rather than lexical overlap. It is the single most
  valuable number in this report to improve.
- **Citation precision is 0.67.** The Tamil queries cite three passages where one would do, because
  the lexical stand-in ranks Tamil chunks together on shared script rather than on meaning.
- **Retrieval scores are near-ceiling and should be read as a floor, not a forecast.** The corpus is
  small and the queries were written against it, so Recall@1 of 1.00 says the ranking has not
  regressed, not that production retrieval is perfect.
- **The retriever is a lexical stand-in**, not BGE-M3 with reciprocal-rank fusion and reranking.
  It exists so the evaluation is deterministic and reproducible on any checkout. Absolute numbers
  will move when the real hybrid retriever is scored; the thresholds are a regression contract for
  the pipeline's own logic.
- **`min_evidence_score` is 0.35 here**, higher than the production default, because a lexical
  overlap score is on a different scale from a fused semantic one. Below roughly a third, the
  overlap is mostly stop-words. The value is a property of the stand-in, not a recommendation.

## Changing a threshold

Lowering a floor is a change to what the product promises. It belongs in its own commit, with the
reason, and never bundled with the change that needed it lowered — that is the whole point of
keeping the floors in one file whose only purpose is to state them. Raising a floor after a genuine
improvement is welcome and should come with a regenerated baseline.

The per-feature suites (`apps/api/tests/test_*_eval.py`) score one component each against their own
fixtures and remain the finer-grained gate; the injection corpus is now shared between both layers
so the two can never disagree about the detector's recall.
