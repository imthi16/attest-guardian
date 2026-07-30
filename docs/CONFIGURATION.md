# Configuration Reference

Configuration is read from environment variables and, for local development, the root `.env`.
The committed `.env.example` contains non-secret local defaults only.

| Variable | Purpose | Local default |
| --- | --- | --- |
| `APP_ENV` | `development`, `test`, `staging`, or `production` | `development` |
| `APP_VERSION` | API-reported application version | `0.1.0` |
| `API_HOST`, `API_PORT` | API bind address and port | `0.0.0.0`, `8000` |
| `API_DOCS_ENABLED` | Enables OpenAPI, Swagger UI, and ReDoc | `true` |
| `API_INTERNAL_ORIGIN` | FastAPI origin the Next.js server calls; never sent to the browser | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_API_ORIGIN` | Browser-visible API origin added to the web CSP `connect-src`; empty means same-origin | `` |
| `DATABASE_URL` | Async PostgreSQL connection URL | Local PostgreSQL |
| `REDIS_URL` | Queue/cache connection URL | Local Redis |
| `S3_ENDPOINT` | S3-compatible endpoint | Local MinIO |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Object-storage credentials | Local-only values |
| `S3_BUCKET` | Private document bucket | `attest-documents` |
| `JWT_SECRET` | HS256 signing secret for access tokens | Local-only value |
| `ACCESS_TOKEN_TTL_SECONDS` | Access-token lifetime | `900` (15 minutes) |
| `REFRESH_TOKEN_TTL_SECONDS` | Refresh-token lifetime | `1209600` (14 days) |
| `AUTH_RATE_LIMIT_ATTEMPTS` | Allowed requests per auth endpoint per window | `10` |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit window length | `60` |
| `MAX_UPLOAD_BYTES` | Document upload size cap | `26214400` (25 MiB) |
| `DOWNLOAD_URL_TTL_SECONDS` | Presigned download-link lifetime | `300` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origin allowlist; empty = same-origin only | `` |
| `SECURITY_HSTS_ENABLED` | Send `Strict-Transport-Security` (enable behind TLS) | `false` |
| `SECURITY_HSTS_MAX_AGE_SECONDS` | HSTS `max-age` when enabled | `63072000` (2 years) |
| `SECURITY_CSP` | `Content-Security-Policy` sent on every API response | locked-down JSON policy |
| `GLOBAL_RATE_LIMIT_ATTEMPTS` | Requests per client IP per window across all routes | `300` |
| `GLOBAL_RATE_LIMIT_WINDOW_SECONDS` | Global rate-limit window length | `60` |
| `MAX_REQUEST_BODY_BYTES` | Max declared request body; must be ≥ `MAX_UPLOAD_BYTES` | `33554432` (32 MiB) |
| `WORKSPACE_MAX_DOCUMENTS` | Documents a single workspace may hold | `1000` |
| `WORKSPACE_STORAGE_QUOTA_BYTES` | Total stored bytes a single workspace may hold | `5368709120` (5 GiB) |
| `INGESTION_QUEUE_KEY`, `INGESTION_DEAD_LETTER_KEY` | Redis list keys for the job queue | `attest:ingestion:*` |
| `INGESTION_MAX_ATTEMPTS` | Attempts before a job dead-letters | `3` |
| `INGESTION_STALE_AFTER_SECONDS` | Age before running/queued jobs are recovered | `300` |
| `INGESTION_STORE_PAGE_IMAGES` | Store rendered PNGs of OCR'd pages | `true` |
| `OCR_ENGINE` | `none`, `tesseract`, or `paddle` | `none` |
| `OCR_LANGUAGES` | OCR language codes (`tam+eng`); `paddle` uses the first recognised code | `tam+eng` |
| `CHUNK_MAX_CHARS` | Maximum characters per chunk | `1200` |
| `CHUNK_OVERLAP_CHARS` | Context shared between neighboring chunks | `150` |
| `METRICS_ENABLED` | Serve `GET /metrics` (Prometheus). Off by default; the endpoint has no authentication of its own | `false` |
| `EMBEDDING_PROVIDER` | Embedding backend (`local`) | `local` |
| `EMBEDDING_MODEL`, `EMBEDDING_MODEL_VERSION` | Provider provenance stored on every vector, and the scope of every vector search | `bge-m3-local`, `hashing-v2` |
| `EMBEDDING_DIMENSIONS` | Vector width; must match the `chunk_embeddings` column | `1024` |
| `EMBEDDING_BATCH_SIZE` | Inputs per provider call | `32` |
| `EMBEDDING_MAX_ATTEMPTS`, `EMBEDDING_BACKOFF_SECONDS` | Retry budget for transient provider errors | `3`, `0.5` |
| `RETRIEVAL_RRF_K` | Reciprocal Rank Fusion constant (larger flattens rank advantage) | `60` |
| `RETRIEVAL_CANDIDATE_LIMIT` | Max candidates fetched per retriever before fusion | `50` |
| `RETRIEVAL_TOP_K` | Default number of fused results returned | `10` |
| `RETRIEVAL_MAX_TOP_K` | Upper bound a request's `top_k` is clamped to | `50` |
| `RERANK_ENABLED` | Rerank fused candidates before returning | `true` |
| `RERANK_THRESHOLD` | Minimum normalized rerank score (0-1) to keep a candidate | `0.0` |
| `RERANK_CANDIDATE_LIMIT` | Fused candidates fed to the reranker before truncation | `30` |
| `RAG_TOP_K` | Default evidence passages retrieved for a grounded answer | `8` |
| `RAG_MAX_TOP_K` | Upper bound a request's answer `top_k` is clamped to | `20` |
| `RAG_MAX_EVIDENCE` | Max passages sent to generation (kept minimal) | `6` |
| `RAG_MIN_EVIDENCE` | Passages required to clear the sufficiency gate, else abstain | `1` |
| `RAG_MIN_EVIDENCE_SCORE` | Minimum fused score a passage needs to count as evidence | `0.0` |
| `INJECTION_SCAN_ENABLED` | Scan chunks for prompt injection during ingestion | `true` |
| `INJECTION_FLAG_SCORE` | Aggregate score (0-1) at which a chunk is flagged for review | `0.5` |
| `INJECTION_QUARANTINE_SCORE` | Aggregate score (0-1) at which a chunk quarantines its document | `0.8` |
| `INJECTION_QUARANTINE_ON_HIGH_SEVERITY` | Quarantine when any single high-severity signal fires | `true` |

> **`EMBEDDING_MODEL_VERSION` is not a label.** It salts the hashing trick, so it defines the
> vector space, and `ChunkEmbeddingRepository.search` filters on it, so it also scopes every
> query. Any change to how text becomes features — a tokenizer, a normalizer, the feature set —
> must move it, or vectors written under the old behaviour keep being compared against queries
> embedded under the new one and return silently wrong neighbours. Setting it back to a retired
> value is refused at startup for that reason: the failure it prevents produces plausible
> results rather than an error, so nothing downstream would ever report it.

### Re-embedding after a version change

Moving the version is safe but not free. Vectors at the previous version stop matching, so **dense
retrieval returns nothing for chunks embedded before the change** until they are re-embedded.
Lexical retrieval is unaffected and fusion still runs, so results degrade rather than disappear —
recall drops, and answers that depended on semantic matching may start abstaining.

**There is currently no first-class reindex.** `retry_ingestion` accepts only `FAILED` documents by
design (a second run over a `READY` document would race the first over the same rows), so a
`READY` document cannot be re-embedded through the API. The only path today is to archive the
document, delete it, and upload it again — the per-workspace SHA-256 dedupe is keyed on the
document row, so re-upload succeeds once the row is gone. That is heavy, and it loses the
document's id and history.

A reindex operation that re-runs the embed stage for documents at a stale version is the right fix
and is not in this release. Until it exists, plan a version change as a re-ingestion of the
workspace, not as a configuration edit. `hashing-v1` → `hashing-v2` accompanied the Tamil tokenizer
correction and is the first instance of this.

Injection thresholds are conservative by construction: a document is quarantined when *any* of its
chunks crosses the quarantine bar, and quarantined content is excluded from retrieval as well as
ingestion. Do not weaken these thresholds to make an evaluation pass; extend the corpus and improve
detection instead (see [`services/safety/README.md`](../services/safety/README.md)).

Known local secrets are rejected when `APP_ENV` is `staging` or `production`. Deployed secrets must
come from a secret manager or protected environment configuration, never a checked-in file. Keep
API docs disabled in deployments where public schema discovery is not intended.

In `staging` and `production` the configuration also fails closed when `JWT_SECRET` is shorter than
32 characters or when any `CORS_ALLOWED_ORIGINS` entry is a wildcard or a non-`https` origin;
`MAX_REQUEST_BODY_BYTES` below `MAX_UPLOAD_BYTES` is rejected in every environment. The full
security posture, threat model, and residual risk are documented in [`SECURITY.md`](./SECURITY.md).

## OCR engines

`OCR_ENGINE=tesseract` requires the system `tesseract` binary with the `tam` and `eng` language
models. `OCR_ENGINE=paddle` requires the optional Paddle dependencies, which are not in the base
image because they are large native wheels. To run the PaddleOCR engine, install the extra:

- Local: `pip install -e 'apps/api[paddle]'`
- Container: build with the `PIP_EXTRAS` build arg, for example
  `docker build --build-arg PIP_EXTRAS='[paddle]' apps/api`.

Selecting an engine whose dependency is absent fails fast at recognition time, so match `OCR_ENGINE`
to the image the worker actually runs.

Provider variables are placeholders until their dedicated features land. Empty `LLM_API_KEY`
means no cloud provider is enabled; do not insert fake credentials.

## Web session cookies

The web client stores no configuration in the browser. Session state lives in three `httpOnly`
cookies written by Next.js server code, whose lifetimes follow the API's token TTLs rather than
separate variables:

| Cookie | Contents | Lifetime source |
| --- | --- | --- |
| `ag_access` | Access token | `expires_in` from `POST /auth/login` (`ACCESS_TOKEN_TTL_SECONDS`) |
| `ag_refresh` | Refresh token | 14 days, matching `REFRESH_TOKEN_TTL_SECONDS` |
| `ag_workspace` | Active workspace id | 14 days; cleared on sign-out |

`Secure` is set whenever `NODE_ENV=production`, so a TLS-terminated deployment needs no extra
configuration. If `REFRESH_TOKEN_TTL_SECONDS` is shortened, the refresh cookie outlives the token
only until the next API call, which then clears the session and redirects to sign-in.
