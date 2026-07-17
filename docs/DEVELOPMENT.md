# Development Guide

## Prerequisites

- Python 3.12 or newer
- Node.js 22 and npm
- Docker with Compose v2+
- GNU Make and Git

Copy `.env.example` to `.env`; its credentials are local-only. Never reuse them outside a local or
test environment. Install application dependencies with `make install`, then install hooks with
`make hooks`.

## Local services

Run `make infra-up` to start health-checked PostgreSQL with pgvector, Redis, MinIO, and the local
`nambikkai-documents` bucket. Ports bind to `127.0.0.1`. `make infra-logs` follows service logs and
`make infra-down` stops services without deleting volumes.

Start the API with `make dev-api` and visit `http://127.0.0.1:8000/health` or the versioned
`/api/v1/health`. In a second terminal, start Next.js with `make dev-web` and visit
`http://127.0.0.1:3000`.

## Database migrations

Apply schema migrations with `make migrate-up` and revert the latest one with
`make migrate-down`. After changing models under `apps/api/app/db/models`, generate a
new revision with `make migrate-new m="describe change"` and review it before committing.
The API integration tests provision disposable `nambikkai_test` and
`nambikkai_migration_test` databases on the local PostgreSQL instance, so `make test`
requires `make infra-up` to be running.

## Authentication

The API exposes `/api/v1/auth` endpoints: `register`, `login`, `refresh`, `logout`, and `me`.
Passwords are hashed with Argon2id. Logins return a short-lived HS256 access token (sign-key
`JWT_SECRET`) plus an opaque refresh token whose SHA-256 digest is stored in `refresh_tokens`.
Refreshing rotates the token and revokes the presented one; reusing a revoked token revokes every
session for that account, and logout revokes a single session. Auth failures use stable error
codes (`invalid_credentials`, `invalid_refresh_token`, `not_authenticated`,
`email_already_registered`, `rate_limited`) so clients never parse messages. The credential
endpoints are rate limited per client IP and path with an in-process sliding window; the limiter
sits behind an interface and must move to Redis before the API scales past one replica.

## Workspaces and roles

Workspaces are the tenant boundary. `/api/v1/workspaces` supports creating a workspace (the
creator becomes its owner), listing your workspaces, and managing members. Roles are
`owner`, `admin`, `member`, and `viewer` (read-only reviewer); the matrix lives in
`app/auth/permissions.py`. Admins manage only `member`/`viewer` rosters — privileged roles are
owner-only — and the last owner can never be demoted or removed. Non-members receive the same
404 as a missing workspace so existence is not disclosed, and every membership mutation writes
an audit event in the same transaction.

Authorization is layered: routes resolve a `WorkspaceContext` (membership proof + role check),
repositories scope tenant queries via `WorkspaceScopedRepository`, and PostgreSQL row-level
security policies (`FORCE`, keyed on the transaction-local `app.workspace_id` set by
`bind_workspace`) fence tenant tables underneath both. Superusers bypass RLS, so deployments
must connect as a non-superuser role; the RLS integration tests verify the policies with a
dedicated non-superuser probe role.

## Document uploads

`/api/v1/workspaces/{id}/documents` accepts PDF, TXT, Markdown, and DOCX uploads (multipart)
from members holding the upload capability. Files are validated before a byte reaches object
storage: sanitized basename, allowed extension, declared MIME matching the extension, and
content sniffing (PDF/DOCX magic, UTF-8 text without NULs). Size is capped by
`MAX_UPLOAD_BYTES`, duplicates are detected per workspace by SHA-256, and every upload or
download-link issuance writes an audit event. Object keys are server-generated; downloads are
time-limited presigned URLs (`DOWNLOAD_URL_TTL_SECONDS`) against a private bucket. Storage is
behind the `ObjectStorage` interface (`app/storage/`), implemented for S3/MinIO.

## Ingestion pipeline

Uploads enqueue an ingestion job on a Redis list (`make dev-worker` runs the consumer). The
database is the source of truth — the queue only carries `{job_id, workspace_id}` pointers, so
duplicate delivery is safe: claiming a job is a compare-and-set and terminal states are never
reprocessed. The worker walks the stages `uploaded → validating → scanning → parsing → ocr →
normalizing → chunking → embedding → indexing → ready`, committing each transition so
`GET .../documents/{id}/status` shows live progress. Validating re-downloads the object,
re-checks its SHA-256 and content magic; scanning uses the `MalwareScanner` interface (the
default engine only recognizes the EICAR test signature — a placeholder, not protection) and
quarantines on a hit without retrying. Parsing through indexing are placeholders until issues
#7–#10 land. Transient failures retry up to `INGESTION_MAX_ATTEMPTS`, then dead-letter;
`requeue_stale` recovers jobs whose worker crashed (stale `running`) or whose enqueue was lost
(stale `queued`). Workers bind row-level security per job from the queue message; the
cross-workspace recovery scan means a deployed worker role needs `BYPASSRLS`.

## Parsing and OCR

The parsing stage (`app/parsing/`) extracts page-level text: digital PDFs via `pypdf` with a
`pypdfium2` fallback (malformed files that fail both parsers fail the job permanently), DOCX
via `python-docx`, and TXT/Markdown as a single logical page. A page whose extracted text has
fewer than ~24 non-whitespace characters is treated as scanned and routed to OCR. OCR engines
sit behind the `OcrEngine` protocol, selected by `OCR_ENGINE`: `tesseract` (system binary with
`tam`/`eng` models — install `tesseract-ocr tesseract-ocr-tam`) or `none`, which records
`ocr_engine="unavailable"` provenance instead of inventing text. The planned PaddleOCR adapter
implements the same protocol later. Each OCR'd page keeps engine name, mean confidence,
word-level blocks with bounding boxes (`pages.ocr_blocks`), and a rendered PNG reference in
object storage (`pages.image_storage_key`, disable with `INGESTION_STORE_PAGE_IMAGES=false`).
Reprocessing replaces a version's pages atomically, so retries never duplicate rows.

## Chunking and provenance

The chunking stage (`app/chunking/`) turns pages into retrievable evidence spans. The cardinal
rule: a chunk's content is always the exact substring `page_text[char_start:char_end]` — the
chunker computes boundaries, it never rewrites text — which makes provenance mechanically
verifiable. Markdown and numbered headings build a section hierarchy (carried across page
breaks); paragraphs pack greedily up to `CHUNK_MAX_CHARS` with `CHUNK_OVERLAP_CHARS` of shared
context between neighbors; pipe tables stay atomic whatever their size; chunks never span
pages. Each chunk records page number, character offsets, section path, an approximate
whitespace token count, language, and OCR engine/confidence inherited from its page. Before
persistence every chunk passes `validate_chunk_provenance`, which re-derives the span
equality, SHA-256 content hash, and token count — a failure aborts the job rather than
persisting an untraceable chunk, and reprocessing replaces a version's chunks atomically.

## Verification

- `make format` formats Python and web sources.
- `make lint` runs Ruff and ESLint.
- `make typecheck` runs strict mypy and TypeScript checks.
- `make test` runs backend and frontend coverage suites.
- `make build` creates the production Next.js bundle.
- `make audit` checks installed Python and locked npm dependencies for known vulnerabilities.
- `make compose-build` builds non-root API and web images; the API build also imports the packaged
  application to catch runtime dependency or container-layout configuration failures.
- `make check` runs the primary local quality suite.

Do not lower a threshold to make a change pass. Add deterministic tests for real behavior and add
evaluation cases for retrieval, model, prompt, or verification changes.

## Branch and review workflow

Create one issue and one branch per reviewable feature, for example `feat/project-foundation`.
Use Conventional Commits such as `feat: add versioned health routes`. Review `git diff` before
staging, target `main`, complete every PR template section, and never merge automatically.
