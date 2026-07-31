# Retrieval boundary

Permission-filtered lexical and dense retrieval, reciprocal-rank fusion, metadata filters, and
multilingual reranking.

**Implemented in `apps/api/app/`** — `retrieval/` (lexical, dense, fusion, hydration),
`embeddings/` (provider interface and pgvector persistence), `reranking/`, and `language/`
(detection, normalization, transliteration, and the mark-aware tokenizer).

The rule that shapes this boundary: the workspace filter is applied *before* any candidate is
scored, so there is no code path that ranks a chunk another tenant owns. Eligibility for evidence
is a single predicate — `evidence_eligible()` — used by lexical retrieval, dense retrieval,
hydration, and citation resolution alike.

See [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md#permission-filtered-hybrid-retrieval).
