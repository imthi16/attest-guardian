"""Cross-cutting evaluation: one metric set over the versioned datasets.

Distinct from the per-feature `test_*_eval.py` suites, which each score one
component against its own fixtures. These run the whole pipeline over one shared
corpus and assert the floors declared in `evaluation/thresholds.json`, so a
change that improves retrieval while breaking citations shows up as a single
verdict rather than as two unrelated results.

Offline and deterministic: no database, no network, no paid service, and no
tenant document.
"""
