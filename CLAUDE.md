# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Attest Guardian is a secure multilingual document-intelligence platform for Tamil, Tanglish, and
English. It answers only from evidence, attaches precise citations, verifies claims, detects
prompt-injection attempts, and abstains when evidence is insufficient. The full mission and
non-negotiable engineering rules live in [`AGENTS.md`](./AGENTS.md) — read it before making changes;
it is treated as authoritative for the whole repository.

**Current state**: this is an early-stage monorepo skeleton. Only health-check endpoints and CI/local
infra plumbing exist so far (see `git log`). Product features (auth, ingestion, retrieval, generation,
verification, safety) are tracked as separate issues in [`docs/BACKLOG.md`](./docs/BACKLOG.md) and
staged in [`docs/IMPLEMENTATION_PLAN.md`](./docs/IMPLEMENTATION_PLAN.md) — check those before assuming
a subsystem is implemented rather than planned.

## Commands

All commands run from the repo root via `make`; see `make help` for the full list.

```bash
cp .env.example .env      # one-time setup; local-only credentials, never reuse elsewhere
make install              # create apps/api/.venv and install apps/web via npm ci
make hooks                # install pre-commit hooks

make infra-up             # start PostgreSQL(+pgvector), Redis, MinIO; creates the local bucket
make infra-down            # stop infra, keep volumes
make infra-logs            # follow postgres/redis/minio logs

make dev-api               # uvicorn --reload on 127.0.0.1:8000 (health: /health, /api/v1/health)
make dev-web               # next dev on 127.0.0.1:3000

make migrate-up            # alembic upgrade head (infra/migrations)
make migrate-down          # revert latest migration
make migrate-new m="..."   # autogenerate a revision against the running DB

make format                # ruff format + ruff check --fix (api), prettier (web)
make format-check          # same, check-only
make lint                  # ruff check (api) + eslint --max-warnings=0 (web)
make typecheck             # strict mypy (api) + next typegen && tsc --noEmit (web)
make test                  # pytest (api, cov-fail-under=90) + vitest run --coverage (web, 90% thresholds)
make build                 # next build
make audit                 # pip-audit + npm audit --audit-level=high
make check                 # format-check + lint + typecheck + test + build + compose-config — run before considering a change done
make compose-build         # build non-root production api/web images
```

Single-test invocation (no Makefile shortcut — run directly against the venv/npm):

```bash
cd apps/api && .venv/bin/pytest tests/test_health.py -k some_case
npm --prefix apps/web run test -- path/to/file.test.tsx
```

Coverage gates are enforced and must not be lowered to make a change pass (`pyproject.toml`
`--cov-fail-under=90`; `vitest.config.ts` 90% branches/functions/lines/statements). Add real tests
instead. Note: running a single backend test file trips the `pytest-cov` fail-under gate because
coverage is measured against that subset, not the whole app — a failing coverage line there does not
mean the change is broken; run the full `.venv/bin/pytest` (or `make test`) to get the real number.

## Architecture

Target request flow (per `README.md` / `AGENTS.md`), most of which is not yet built:

```
Browser / Next.js
       |
FastAPI API
       |
Authorization + workspace boundary
       |
LangGraph query workflow
  normalize -> retrieve -> rerank -> generate -> verify -> abstain/cite
       |
PostgreSQL + pgvector | Redis | S3/MinIO
       |
Async ingestion workers
  validate -> scan -> parse/OCR -> normalize -> chunk -> embed -> index
```

Repository layout and intended ownership per directory:

- `apps/api` — FastAPI service. `app/main.py` builds the app via `create_app(settings)`; versioned
  routes are mounted under `/api/v1` through `app/api/v1/router.py`, which aggregates routers from
  `app/routes/`. Settings (`app/config.py`) load from process env or the root `.env`, located by
  walking up from the module path to find `AGENTS.md` — do not assume a fixed relative path to the
  env file. `Settings.enforce_deployment_secrets` rejects the checked-in default `JWT_SECRET` /
  `S3_SECRET_KEY` when `APP_ENV` is `staging` or `production`. The database layer lives in
  `app/db/`: SQLAlchemy 2.0 typed models (`models/`), async engine/session + `session_scope()`
  (`session.py`), and repositories (`repositories/`) — tenant-owned data must go through
  `WorkspaceScopedRepository`, which filters every query by `workspace_id`. Schema changes require
  an Alembic revision in `infra/migrations/versions/`; the integration test suite runs
  `alembic check` so models and migrations may not drift. API integration tests need the
  `make infra-up` Postgres (they provision disposable `attest_test` databases). Authentication
  lives in `app/auth/` (Argon2id passwords, HS256 access JWTs, DB-backed rotating refresh tokens
  with reuse detection, sliding-window rate limiting) behind `/api/v1/auth`; protected routes take
  the `CurrentUserDep` dependency, per-app state (`app.state.settings`, `auth_rate_limiter`) is set
  in `create_app`, and auth errors carry stable `{code, message}` details. Workspace RBAC:
  routes under `/workspaces/{id}` resolve a `WorkspaceContext` (`app/auth/workspace.py`) that
  proves membership (non-members get 404, never 403), applies the role matrix in
  `app/auth/permissions.py`, and calls `bind_workspace` so Postgres row-level security
  (migration `0003`, enforced only for non-superuser DB roles) fences tenant tables under the
  repository scoping. Document uploads (`app/documents/`, `app/routes/documents.py`) validate
  filename/extension/declared-MIME/content-magic before any byte reaches storage, dedupe by
  SHA-256 per workspace, and store via the `ObjectStorage` interface (`app/storage/`,
  S3/MinIO impl); downloads are presigned URLs. Post-upload lifecycle lives in
  `app/documents/lifecycle.py`: archive/restore are a reversible `documents.archived_at`
  timestamp (never a `status` rewrite) gated by the new `MANAGE_DOCUMENTS` capability;
  retry (`UPLOAD_DOCUMENTS`) inserts a *new* `QUEUED` job only for a `FAILED` document —
  quarantine is terminal and is never reprocessed, and neither is a job flagged
  `permanent_failure` (deterministic failures would fail identically on the same bytes);
  permanent delete is refused unless the document is already archived *and* no job is
  `RUNNING`. Delete makes **no storage call**: rows and objects cannot share a transaction,
  so it commits a `storage_purges` record (`app/documents/purge.py`, migration `0011`) with
  the row deletion, and the worker's idle loop (`purge_deleted_content` → `run_pending_purges`)
  deletes the objects afterwards and retries — a storage outage delays the purge instead of
  stranding a document whose bytes are gone. The purge sweeps the document's **key prefix**,
  not the keys the deleted rows knew: a page image reaches storage before its `pages` row
  commits, so a run that crashed mid-OCR leaves content no row recorded. Every writer of
  document content must build keys via `app/documents/keys.py` to stay inside that prefix.
  Retry and delete read the document `FOR UPDATE`: the worker's compare-and-set claim dedupes
  duplicate delivery of one job, not two distinct jobs. Terminal worker handlers must never
  `assert` the job row exists — raising from an exception handler escapes `run_forever` and
  stops the worker. Evidence eligibility is one predicate,
  `evidence_eligible()` in `app/db/models/documents.py` (READY **and** not archived), and
  every retrieval gate must use it — lexical, dense, hydration, and citation provenance —
  so archiving stops answers rather than only hiding list rows. Storage integration tests
  need the `make infra-up` MinIO and use a separate `attest-test-documents` bucket. Ingestion
  (`app/ingestion/`): uploads enqueue `{job_id, workspace_id}` on a Redis list; the worker
  (`make dev-worker`, `python -m app.ingestion.worker`) claims jobs by compare-and-set (duplicate
  delivery safe), walks stage enums committed per transition, retries transient failures, and
  dead-letters after `INGESTION_MAX_ATTEMPTS`; quarantine (EICAR placeholder scanner) and
  integrity failures never retry. `_run_stages` must follow `IngestionStage` declaration
  order: normalize before chunk (the chunker copies each page's detected language onto its
  chunks), embed/index after chunk (they need persisted chunk ids). Normalizing classifies
  and never rewrites stored text — consumers apply `normalize_for_match` at read time, and
  rewriting would break `validate_chunk_provenance`. A wrong-width embedding provider is a
  *permanent* failure (`DimensionMismatchError`); every other embedding failure is transient.
  Worker tests use dedicated committed DBs
  (`attest_worker_test`, `attest_parsing_test`), not the rolled-back `db_session`.
  Parsing (`app/parsing/`): pypdf → pdfium fallback, scanned-page heuristic (<24 chars),
  `OcrEngine` protocol (`tesseract` adapter or `none` → `ocr_engine="unavailable"` provenance);
  PDF test fixtures are generated in-memory via `tests/pdftools.py` (reportlab), never
  committed binaries. Tesseract tests skip when the binary is absent (installed in CI).
  Chunking (`app/chunking/`): chunk content must equal `page_text[char_start:char_end]`
  exactly (the chunker computes boundaries, never rewrites text) and
  `validate_chunk_provenance` gates persistence — a provenance failure aborts the job.
  Tables are atomic, chunks never span pages, and the section hierarchy carries across pages.
  Conversations (`app/conversations/`, `app/routes/conversations.py`) persist a
  thread: the user turn keeps original/normalized/transliterated query text, the
  assistant turn keeps its whole grounding verdict — `answer_status` **and** the
  operational `decision`, `decision_reason`, `confidence`, `abstention_reason`
  (migration `0013`), because three different decisions all read as `abstained`
  and a thread keeping only the status degrades what the answer said on reload —
  and each claim writes a `citations` and a `verification_results` row. Both
  rows carry the same `claim_index` (migration `0015`, unique per message):
  claims come back sorted by it while citations come out of an unordered
  relationship, so a client pairing the two lists by position would eventually
  file one claim's passage under another — evidence that looks proven and
  supports a different statement. A persisted citation exposes
  `document_version_id` (from its chunk, no column needed) because
  `/citations/resolve` requires it; without it the evidence panel
  would work on a live answer and be inert on history. The stored `verifier` is
  `trace.verifier`, never a constant. The question is persisted before the
  pipeline runs (a failed run still records what was asked); the answer only from
  a terminal result. Streaming (`POST .../messages/stream`) is SSE over
  `RagGraph.run_streaming`, which reads LangGraph's own `astream` updates — stage
  events are real node completions, and the answer is emitted once at the end
  because extractive generation has no partial text safe to display. Both routes
  build the identical pipeline, so streaming is never a less-checked path.
  Reviewer feedback (`message_feedback`, migration `0012`) is unique per
  (message, reviewer), so it is a `PUT` that revises rather than accumulates —
  written with `ON CONFLICT DO UPDATE`, and accepted only on assistant turns.
  `QUERY` is read-only and deliberately does **not** cover conversations:
  writing a thread, feedback, and deletion need `CONVERSE` (members and up), and
  deletion also requires authorship or `MANAGE_CONVERSATIONS` (owners/admins) and
  is audited before the cascade. A turn is atomic — question and answer share the
  request transaction, so a failed run stores neither. `messages.sequence`
  (migration `0014`) orders turns, assigned under the conversation's row lock,
  because a question and its answer tie on `created_at` (`now()` is
  transaction-start time); that lock also bumps `conversations.updated_at`. A
  streamed failure logs the exception *type* only — driver errors carry bound
  parameters including the raw query.
- `apps/web` — Next.js (App Router) + TypeScript, React 19. Strict TypeScript, strict ESLint
  (`--max-warnings=0`). Backend-for-frontend: tokens live only in `httpOnly` cookies and all
  API calls run in server code (`lib/api-client.ts` → `lib/session.ts` → `lib/attest-api.ts`,
  responses parsed by `lib/contracts.ts` Zod schemas). `lib/permissions.ts` and
  `lib/upload-rules.ts` are advisory mirrors of the API's role matrix and upload validator —
  their tests read the Python sources and fail the build on drift, so never let them diverge.
  The *size* cap is not mirrored: `MAX_UPLOAD_BYTES` is per-deployment, so the browser and the
  relay read it from `GET .../documents/policy` and `DEFAULT_MAX_UPLOAD_BYTES` is only a
  fallback. Mutations are server actions (`app/*-actions.ts`); route handlers exist only where
  an action cannot work — `app/api/workspaces/[workspaceId]/documents/**` (upload needs XHR
  byte progress, download needs a link navigation because the CSP sets `form-action 'self'`)
  and `.../conversations/[conversationId]/stream` (an action returns once and cannot report
  progress). Route handlers get none of a server action's built-in protection, so every relay
  verifies `Origin` against `X-Forwarded-Host`/`Host` (`SameSite=Lax` is per-site, not
  per-origin); every relay also bounds `Content-Length` *before* reading the body, because
  `request.formData()`/`request.json()` buffer the whole thing before any check inside it can
  run. The chat UI consumes SSE stage events for progress only — the
  answer arrives in one event and the page then `router.refresh()`es, so the server-rendered
  thread rather than client state is what a reader sees; a stream that ends without an
  `answer` event is a failure, not a success, since a 200 only means the question was
  accepted. The evidence panel renders
  `supporting_text` from `/citations/resolve`, never the quote the answer supplied, and
  resolves on open because resolution is audited. That field *is* the proven quote
  (`content[start:end]`), so the whole of it is highlighted — `page_quote_char_*` locates it
  inside its page and indexes nothing in the string itself. Timestamps are formatted in the
  browser (`components/local-time.tsx`): a Server Component formats in the server's zone,
  which in a deployment is UTC. Uploaded filenames,
  titles, and worker error strings are untrusted: render them as text children only, never
  preview document contents, and keep `dangerouslySetInnerHTML` out of the app.
- `services/` — planned boundaries for `ingestion`, `retrieval`, `verification`, `safety`, kept as
  separate services rather than folded into `apps/api` so each enforces its own authorization and
  input-trust boundary.
- `packages/` — shared `contracts` (schemas / generated clients), `config`, `observability`
  (tracing/metrics/logging helpers) intended for reuse across `apps/*` and `services/*`.
- `infra/` — Alembic migrations + row-level security (`infra/migrations`), dashboards/alerts
  (`infra/monitoring`).
- `tests/` — cross-cutting `unit`, `integration`, `evaluation` (AI/retrieval regression) suites,
  distinct from the per-app test suites under `apps/api/tests` and `apps/web/**/*.test.tsx`.

Local infra (`docker-compose.yml`): `postgres` (pgvector/pgvector image), `redis`, `minio`, and a
one-shot `minio-create-bucket` job that must complete before the API container starts. `api`/`web`
containers are under the `application` compose profile (`make compose-build` builds them; `infra-up`
does not start them) and run `read_only: true` with a `tmpfs` `/tmp`.

## Non-obvious engineering rules

The full rules are in `AGENTS.md`; the ones most likely to be violated by an unfamiliar change:

- Treat uploaded files, OCR output, webpages, and retrieved chunks as **untrusted data** passed to
  the model, never as instructions — this applies to any ingestion or generation code, not just the
  safety service.
- Enforce workspace/document authorization inside the repository and retrieval layers, not only at
  the route level.
- Preserve full provenance on every chunk: document ID, version, page, section, offsets, language,
  OCR engine, confidence — downstream citation and verification depend on this being present from
  ingestion onward.
- A citation must support the exact claim (numbers, dates, conditions, negation); model-reported
  confidence alone is never a valid confidence score — verification must combine retrieval,
  reranking, OCR, and normalization signals.
- Keep LLM, embedding, OCR, and reranker providers behind interfaces (planned: PaddleOCR, BGE-M3,
  bge-reranker-v2-m3) so providers are swappable.
- MVP is read-only: no new external side effects without explicit approval and threat modelling.
- Any AI/RAG-affecting change needs a measurable regression/evaluation test, not just unit tests.
- Branches: `feat/`, `fix/`, `docs/`, `test/`, `chore/` prefixes; Conventional Commit messages; one
  issue/branch per reviewable feature; never merge automatically.
