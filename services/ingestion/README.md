# Ingestion boundary

Validated upload processing, malware-scan gates, parsing, OCR, normalization, and
provenance-preserving chunking.

**Implemented in `apps/api/app/`** — `documents/` (validation, storage, lifecycle, purge),
`ingestion/` (queue, worker, stage machine), `parsing/` (PDF/DOCX/text extraction and OCR), and
`chunking/` (spans with validated provenance). It runs in the worker process (`make dev-worker`),
not in the API.

The cardinal rule of this boundary: a chunk's content must equal `page_text[char_start:char_end]`
exactly. The chunker computes boundaries and never rewrites text, because citation resolution
proves a quote by re-reading that span. Normalization happens at read time instead.

See [`docs/DEVELOPMENT.md`](../../docs/DEVELOPMENT.md#ingestion-pipeline) and
[`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).
