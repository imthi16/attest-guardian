# Security Hardening

This document describes the application-layer security controls added in PR 18, how they are
configured per environment, the CSRF strategy, the automated scans that gate CI, and the residual
risks that remain. It complements the authorization, tenant-isolation, and upload-validation
boundaries described in [`ARCHITECTURE.md`](./ARCHITECTURE.md) and the non-negotiable rules in
[`AGENTS.md`](../AGENTS.md). Controls here are defense in depth; they do not replace those
boundaries.

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

Enforcement has two boundaries. During ingestion the worker scans every chunk **before
persistence**: a quarantine verdict marks the document `QUARANTINED`, writes no chunk rows, records
a `document.quarantined` audit event, and emits a privacy-safe `prompt_injection_quarantine`
security event (counts, categories, and score only — never chunk text). As defence in depth, both
retrievers only return chunks of a `READY` document, so quarantined content can never reach
retrieval, reranking, generation, or citation even if it was quarantined after chunking.

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
- **Superuser bypass of row-level security.** RLS policies only bite for non-superuser database
  roles; deployments must connect the app as a non-superuser role.
