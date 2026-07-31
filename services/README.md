# Services

Domain service boundaries. Each treats document-derived content as untrusted, accepts typed
contracts, preserves provenance, and has no tenant-bypass path.

**The code is not here.** Every boundary below is implemented as a package inside `apps/api/app/`,
where it runs in the API and worker processes. These directories hold each boundary's own
documentation and mark the seams along which a package would be extracted if it ever needed to
scale, deploy, or fail independently. Splitting them before that need is real would buy a network
hop and lose a transaction.

| Boundary | Implemented in |
| --- | --- |
| [`ingestion/`](./ingestion/README.md) | `apps/api/app/ingestion/`, `parsing/`, `chunking/`, `documents/` |
| [`retrieval/`](./retrieval/README.md) | `apps/api/app/retrieval/`, `embeddings/`, `reranking/`, `language/` |
| [`verification/`](./verification/README.md) | `apps/api/app/verification/`, `decision/`, `citations/` |
| [`safety/`](./safety/README.md) | `apps/api/app/safety/` |
