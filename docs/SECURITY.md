# Security Hardening

This document describes the application-layer security controls added in PR 18, how they are
configured per environment, the CSRF strategy, the automated scans that gate CI, and the residual
risks that remain. It complements the authorization, tenant-isolation, and upload-validation
boundaries described in [`ARCHITECTURE.md`](./ARCHITECTURE.md) and the non-negotiable rules in
[`AGENTS.md`](../AGENTS.md). Controls here are defense in depth; they do not replace those
boundaries.

This document describes *what is implemented*. For the assets, actors, and trust boundaries that
decide which controls are worth having — and for what is explicitly out of scope — see
[`THREAT_MODEL.md`](./THREAT_MODEL.md). Where the two disagree, this one describes the code and
wins.

## Response headers

`app.security.middleware.SecurityHeadersMiddleware` attaches the following to every API response,
including error responses such as `401`, `413`, and `429`:

- `Content-Security-Policy` — a locked-down JSON-API policy
  (`default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`), overridable
  via `SECURITY_CSP`.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`.
- `Permissions-Policy` denying geolocation, camera, microphone, and browsing-topics.
- `Strict-Transport-Security` — only when `SECURITY_HSTS_ENABLED=true` (enable once TLS terminates
  in front of the API); off by default so local HTTP is not pinned.
- The `Server` banner is replaced with a static value so the implementation and version are not
  advertised.

The Next.js web app sets an equivalent header set (including a browser-appropriate CSP) in
`apps/web/next.config.ts` and disables the `X-Powered-By` banner.

## CORS

`CORS_ALLOWED_ORIGINS` is a comma-separated allowlist; empty means same-origin only. Credentials
are never reflected (`allow_credentials=False`) because the API authenticates with bearer tokens
rather than cookies. In `staging`/`production` a wildcard origin is rejected and every origin must
be `https`.

## CSRF strategy

The API is not cookie-authenticated: access tokens are sent in the `Authorization: Bearer` header
and refresh tokens travel in request bodies. Browsers do not attach `Authorization` headers to
cross-site requests automatically, and no `Set-Cookie` is ever issued, so there is no ambient
credential for a cross-site request to abuse. Combined with a credential-free CORS policy, this
makes classic CSRF inapplicable. Should cookie-based sessions ever be introduced, this decision must
be revisited and an explicit anti-CSRF token or `SameSite=strict` cookie added.

## Rate limits, body cap, and quotas

- **Global rate limit** — `GlobalRateLimitMiddleware` caps requests per client IP across all routes
  (`GLOBAL_RATE_LIMIT_ATTEMPTS` per `GLOBAL_RATE_LIMIT_WINDOW_SECONDS`), independent of and in
  addition to the stricter per-endpoint auth limiter. `/health` endpoints are exempt so probes are
  never throttled. Rejections return `429` with a `Retry-After` header.
- **Request body cap** — `RequestBodyLimitMiddleware` rejects requests whose declared
  `Content-Length` exceeds `MAX_REQUEST_BODY_BYTES` (`413`), a coarse memory-exhaustion guard. It is
  configured at or above `MAX_UPLOAD_BYTES`; the upload route additionally streams with its own hard
  byte cap.
- **Workspace quotas** — uploads are rejected (`413`) once a workspace reaches
  `WORKSPACE_MAX_DOCUMENTS` or `WORKSPACE_STORAGE_QUOTA_BYTES`, enforced inside the upload service
  before any byte reaches storage.

## Audit logging and security telemetry

Successful, committed, security-relevant actions are written to the append-only `audit_logs` table:
account registration and login (`auth.*`), document upload, and download-link issuance. Rejections
happen on the request-error path, where the per-request transaction rolls back and cannot persist an
audit row; these (failed logins, rate-limit hits, oversized bodies, quota rejections) are emitted to
the `app.security` logger via `log_security_event`, which never records request bodies, credentials,
tokens, or email addresses.

## Prompt-injection defence

Uploaded files, OCR output, and retrieved chunks are treated as **untrusted data**, never as
instructions. `app/safety` detects instruction-like passages (direct overrides, system/role
impersonation, exfiltration and tool-use requests, indirect "when you read this" triggers, and
obfuscated or encoded payloads), scores them, and turns the result into an `allow` / `flag` /
`quarantine` decision. Detection combines rule matching over normalized text (NFKC, homoglyph
folding, zero-width stripping, and a de-spaced view) with structural heuristics and an optional
replaceable classifier; a model's self-report is never trusted.

Enforcement has two boundaries. During ingestion the worker scans every chunk **before chunk
persistence**: a quarantine verdict marks the document `QUARANTINED`, writes no chunk rows, records
a `document.quarantined` audit event, and emits a privacy-safe `prompt_injection_quarantine`
security event (counts, categories, and score only — never chunk text). As defence in depth, both
retrievers only return chunks of a `READY` document, so quarantined content can never reach
retrieval, reranking, generation, or citation even if it was quarantined after chunking.

Note the exact scope: the chunk is the only unit retrieval returns, so withholding it is what makes
the content unreachable — but the uploaded bytes are already in object storage and the parse stage
has already committed the extracted and OCR'd page text by the time the scan runs. Quarantine
withholds content from answers; it does not erase it. Permanent deletion is what removes it, and a
retention or export feature added later must not assume otherwise.

A versioned attack/benign corpus (`tests/injection_corpus.py`) drives recall/precision regression
tests across English, Tamil, and Tanglish. Thresholds are conservative and must not be weakened to
pass evaluations. See [`services/safety/README.md`](../services/safety/README.md) for detail and
limitations.

## Automated scanning in CI

- `gitleaks` — secret scanning across full git history.
- `pip-audit` and `npm audit --audit-level=high` — dependency vulnerability audits.
- `trivy` — container image scanning of the built API and web images for `CRITICAL`/`HIGH` OS and
  library vulnerabilities (`ignore-unfixed`), gating the pipeline.

## Least-privilege containers

The API and web images run as a non-root user, with `read_only` root filesystems, a `tmpfs` `/tmp`,
and `no-new-privileges` (see `docker-compose.yml` and the `Dockerfile`s).

## Browser session model

The web client is a backend-for-frontend: it never receives an access or refresh token. Login
credentials are posted to a Next.js server action, which exchanges them with the API and stores the
pair in cookies flagged `httpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` when
`NODE_ENV=production`.

| Cookie | Contents | Lifetime |
| --- | --- | --- |
| `ag_access` | Access token | The API's `expires_in` (15 minutes by default) |
| `ag_refresh` | Refresh token | 14 days, matching `REFRESH_TOKEN_TTL_SECONDS` |
| `ag_workspace` | Active workspace id | 14 days; cleared on sign-out |

Consequences of this design:

- Client JavaScript cannot read a token, so an XSS foothold cannot exfiltrate a session. The audit
  check `rg "localStorage|sessionStorage" apps/web` must stay empty.
- Sign-out revokes the refresh token at `POST /api/v1/auth/logout` **before** clearing cookies, so a
  stolen cookie copy is useless afterwards. The endpoint is idempotent, so a session that is already
  gone still clears cleanly.
- An expired access token is refreshed exactly once per request; a failed refresh clears all three
  cookies and redirects to `/login?expired=1`. There is no retry loop that could hammer the API.
- `SameSite=Lax` plus the API's own CSRF posture means a cross-site form post cannot ride the
  session for state-changing requests, which are all `POST`/`PATCH`/`DELETE`.
- The post-login `next` parameter is rejected unless it is a single-slash relative path, so a crafted
  link cannot bounce an authenticated visitor to an attacker origin.

### UI role checks are not authorization

`apps/web/lib/permissions.ts` mirrors the API role matrix so the interface does not offer actions
that would be refused. It is presentation only. Enforcement stays in
`apps/api/app/auth/permissions.py` and the repository layer, and every UI mutation round-trips to the
API. `apps/web/lib/permissions.test.ts` reads the Python matrix and fails if the mirror drifts, so a
stale mirror is a build failure rather than a silent authorization gap. Non-membership continues to
return `workspace_not_found`, so the UI cannot be used to probe which workspaces exist.

### Document lifecycle exposure

The document library adds four state-changing endpoints, all inside the workspace context so
membership is proven and row-level security is bound before any tenant row moves:

| Endpoint | Capability | Notes |
| --- | --- | --- |
| `POST .../documents/{id}/archive` | `MANAGE_DOCUMENTS` | Reversible; audited as `document.archived` |
| `POST .../documents/{id}/restore` | `MANAGE_DOCUMENTS` | Audited as `document.restored` |
| `POST .../documents/{id}/retry` | `UPLOAD_DOCUMENTS` | Refused unless `status == FAILED`; never for a quarantined or permanently failed document |
| `DELETE .../documents/{id}` | `MANAGE_DOCUMENTS` | Refused unless already archived and not mid-run; purges rows and every stored object; audited as `document.deleted` |
| `GET .../documents/policy` | `VIEW` | Reports the deployment's effective upload limits |

Security-relevant properties:

- **Quarantine stays terminal.** A quarantined document cannot be reprocessed through the API at
  all, so a scanner or prompt-injection verdict cannot be undone by a caller with upload rights.
- **Archival removes evidence, not just rows in a list.** `evidence_eligible()` gates lexical
  retrieval, dense retrieval, hydration, and citation resolution, so an archived document stops
  contributing to answers immediately.
- **Deletion is two-step and audited.** The audit row is written before the document row is deleted
  and survives it, because audit rows reference resources by id rather than by foreign key.
- **Deletion purges the document's whole key prefix.** When `INGESTION_STORE_PAGE_IMAGES` is on,
  ingestion writes a PNG per page — pictures of the document's content — and writes each one to
  storage *before* the `pages` row that records it is committed. A purge driven by those rows would
  therefore miss every image from a run that crashed mid-OCR, so the purge sweeps the document's
  server-generated prefix instead and treats the recorded keys as a fallback. Without that, a
  "permanent" deletion could leave the document's pages readable in object storage indefinitely.
- **Deletion is durable before it is complete.** Rows and objects cannot be deleted in one
  transaction, so the request never calls storage: it commits the row deletion with a
  `storage_purges` record, and a sweeper deletes the objects afterwards and retries until it
  succeeds. A crash or a storage outage therefore delays the purge rather than losing the
  instruction — and never leaves a surviving document whose bytes are already gone. Retention
  monitoring should alert on purge records that stay pending, since that is what a worker without
  `BYPASSRLS`, or a persistent storage failure, looks like.
- **Deletion cannot destabilise a worker.** It is refused while a job is `RUNNING`, because the
  cascade would remove the row a worker is still writing stages to. That check and the cascade are
  not atomic, so the worker also treats a vanished job as an abandoned one rather than asserting —
  losing one document can never stop the ingestion process.
- **State transitions are serialized, in one lock order.** Retry and delete read the document
  `FOR UPDATE`. The worker's claim is a compare-and-set on a single job id, so it makes duplicate
  *delivery* safe but does not deduplicate two distinct jobs; without the row lock, two concurrent
  retries would each enqueue one and two workers would race over the same pages and chunks. Every
  path that writes both a document and its job takes the *document* lock first — the worker included
  — because the reverse order would deadlock against a delete, and PostgreSQL would abort one of the
  two: the worker at a point where it can record nothing, or the request as a 500. Holding the
  document lock is also what makes delete's "is a job running?" check meaningful, since no claim can
  start behind it.
- **Deterministic failures are not retryable.** A hash mismatch, an unparseable file, or a
  provenance violation is recorded as `permanent_failure`, so a caller cannot queue unbounded runs
  that are certain to fail identically on the same bytes.
- **`retryable` is scoped to the caller, and is the only source of the control.** One predicate
  (`may_retry`) answers whether *this* caller may retry — state, permanence, and their own role — and
  it is reported on the document itself as well as on the status endpoint. The UI renders "Process
  again" from that field rather than from `status == "failed"`, so a permanently failed document
  never presents an action that can only return 409.
- **Non-members still learn nothing.** Every lifecycle route answers `workspace_not_found` for a
  non-member and `document_not_found` for another tenant's document id.

### Upload and download relays

`POST /api/workspaces/[id]/documents` and `GET /api/workspaces/[id]/documents/[docId]/download` are
Next.js route handlers that exchange the `httpOnly` session cookie for a bearer token server side.
They are relays and never soften an API decision; regression tests pin that a 403 or 401 from the API
is passed through unchanged. The upload relay forwards only the `file` part, so no client-supplied
title or metadata becomes tenant content.

The upload relay carries two protections a server action would have provided for free:

- **Origin is verified.** `SameSite=Lax` scopes the session cookie to the *site*, not the origin, so
  in a deployment with an attacker-controlled sibling origin under the same registrable domain, a
  script there could otherwise send a credentialed cross-origin upload and spend the victim's
  workspace quota. The handler compares `Origin` against `X-Forwarded-Host`/`Host` and refuses a
  request that does not match or omits `Origin` entirely. Next.js applies the equivalent check to
  server actions itself; a route handler has to make it explicitly.
- **The body is bounded before it is parsed.** `request.formData()` materializes the whole request in
  memory, so checking the file's size afterwards is too late to stop concurrent oversized requests
  from exhausting the process. `Content-Length` is checked first, and a request that declares no
  length is refused with `411`.

Both the relay and the browser take the size cap from `GET .../documents/policy` rather than a
compiled-in constant, so raising or lowering `MAX_UPLOAD_BYTES` in a deployment cannot leave the web
tier rejecting files the API accepts or advertising ones it will refuse. The two handle an
*unavailable* policy differently, on purpose: the relay must bound the body it buffers, so it refuses
the upload outright, while the browser treats an unknown cap as unknown and skips its local size
check rather than enforcing the compiled-in default — which on a deployment that raised the cap would
refuse a perfectly valid file because one request happened to fail.

Presigned download URLs are minted per click, carry `Cache-Control: no-store`, and are never
rendered into HTML, so they cannot be scraped from a page or survive in a cache.

### Error disclosure

Failures reach the UI as the API's stable `{code, message}` envelope. Transport and schema failures
are mapped to local codes (`api_unreachable`, `invalid_api_response`) so an internal exception or
connection string is never rendered. Submitted passwords are never echoed into returned form state,
which is covered by a regression test.

## Residual risks

- **In-process rate limiting.** Both limiters store state per process, so a horizontally scaled
  deployment enforces the window per replica. A Redis-backed limiter is required before scale-out;
  the limiter is kept behind `RateLimiter` so the swap is local.
- **Client IP trust.** Rate-limit keys use the socket peer address. Behind a proxy, a trusted
  `ProxyHeaders`/`X-Forwarded-For` configuration must be added or the limit applies to the proxy.
- **Body cap on chunked uploads.** The body cap relies on `Content-Length`; requests without it
  bypass the middleware and are bounded only by the streaming upload cap.
- **Web CSP inline allowances.** The web CSP permits `'unsafe-inline'` scripts/styles pending a
  nonce-based policy; the JSON API CSP does not.
- **No CSRF token on server actions.** Protection currently rests on `SameSite=Lax` cookies plus
  Next.js action-id opacity. A double-submit or origin-check token should be added before the app is
  exposed to untrusted browser extensions or embedded contexts.
- **Refresh-token reuse is detected but not alerted on.** A revoked token presented again revokes
  every session for that account, which is the right containment, and it is the strongest available
  signal that a token was captured — yet it raises no alert and appears nowhere an operator would
  look. Wiring it to `log_security_event` and an alert rule is the missing half.
- **Superuser bypass of row-level security.** RLS policies only bite for non-superuser database
  roles; deployments must connect the app as a non-superuser role.
- **Buffered upload relay.** The web upload route reads the whole multipart body into memory
  before forwarding it, bounded by `MAX_UPLOAD_BYTES` (25 MiB) per request. Concurrent uploads
  therefore consume memory in the Next.js process; streaming the body through is the fix if that
  becomes a scaling limit.
- **Deleted bytes are not shredded.** Permanent deletion removes the object from the bucket, but
  storage-level retention, versioning, or backups may still hold a copy. A documented retention
  and shredding workflow is Phase 6 work.
