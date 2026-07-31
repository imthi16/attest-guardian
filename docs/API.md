# API Reference

The HTTP surface of the FastAPI service. This page is a guide to the shape and the rules; the
authoritative description is [`packages/contracts/openapi.json`](../packages/contracts/openapi.json),
which the application generates about itself (`make contracts`) and which
`apps/api/tests/test_contracts.py` fails on if it drifts. Every path listed here is asserted to
exist in that document by `apps/api/tests/test_documentation.py`, so a renamed route breaks this
page's build rather than a reader's expectations.

With `API_DOCS_ENABLED=true` (the local default), Swagger UI is at `/docs` and ReDoc at `/redoc`.
Deployments turn both off; `scripts/smoke.sh` checks that they are closed.

## Conventions

**Versioning.** Everything except the probes lives under `/api/v1`. Probes deliberately do not:
`/health` and `/readyz` are infrastructure contracts, not application ones.

**Authentication.** `Authorization: Bearer <access token>`. Access tokens are short-lived (15
minutes by default); refresh tokens are opaque, travel in request bodies, rotate on every use, and
a token presented after revocation ends every session for that account. No endpoint sets a cookie —
the browser session cookies described in [`SECURITY.md`](./SECURITY.md#browser-session-model) are
written by the Next.js tier, not by the API.

**Errors.** Failures carry a stable, machine-readable envelope. Parse the code; the message is
human wording and may change.

```json
{ "detail": { "code": "insufficient_role", "message": "Your workspace role does not allow this action." } }
```

`422` from request-schema validation is FastAPI's own list-shaped body. Application-level `422`s
(upload validation) use the envelope above.

**Not found means not found.** A workspace you are not a member of returns `404
workspace_not_found`, never `403`. Membership, and therefore workspace existence, is not something
a caller can probe. The same applies to another tenant's document, conversation, or message id.

**Tracing.** Every response carries `X-Request-ID`. An inbound `X-Request-ID` is never honoured —
it is a value this service assigns. W3C `traceparent` *is* honoured. See
[`OBSERVABILITY.md`](./OBSERVABILITY.md).

**Rate limits.** A global per-IP limit applies to every route except the health probes; credential
endpoints carry a stricter limit of their own. Both answer `429 rate_limited` with `Retry-After`.
Both are per process — see [`SECURITY.md`](./SECURITY.md#residual-risks).

## Capabilities

Workspace routes resolve a membership and check one capability from the matrix in
`apps/api/app/auth/permissions.py`. This table is mirrored (advisorily) by
`apps/web/lib/permissions.ts`, whose test reads the Python source and fails the build on drift.

| Capability | Owner | Admin | Member | Viewer |
| --- | :-: | :-: | :-: | :-: |
| `view` — read the workspace, documents, threads | ● | ● | ● | ● |
| `query` — ask a question, resolve a citation | ● | ● | ● | ● |
| `converse` — write threads, feedback, delete own threads | ● | ● | ● | |
| `upload_documents` — upload, retry a failed ingestion | ● | ● | ● | |
| `manage_conversations` — delete anyone's thread | ● | ● | | |
| `manage_documents` — archive, restore, delete | ● | ● | | |
| `manage_members` — manage the roster | ● | ● | | |

`query` is read-only on purpose, which is why a viewer holds it and why it does **not** cover
conversations: writing a durable thread is a change to workspace state. Admins manage only
`member` and `viewer` rosters — privileged roles are owner-only — and a workspace can never lose
its last owner.

## Probes

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Liveness. Touches nothing. Never wire a restart to anything else. |
| `GET` | `/readyz` | Checks the database, queue, and bucket. **Do not wire this to a restart** — a dependency blip would restart a healthy process. |
| `GET` | `/api/v1/health` | The versioned health route. |
| `GET` | `/metrics` | Prometheus text. Served only when `METRICS_ENABLED=true`; it has no authentication of its own, so keep it off the public listener. |

## Authentication

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/register` | — | Argon2id. `409 email_already_registered`. |
| `POST` | `/api/v1/auth/login` | — | Returns `{access_token, refresh_token, expires_in}`. |
| `POST` | `/api/v1/auth/refresh` | refresh token in body | Rotates. Revokes the presented token. |
| `POST` | `/api/v1/auth/logout` | refresh token in body | Idempotent; revokes one session. |
| `GET` | `/api/v1/auth/me` | bearer | The caller's account. |

Credential and token failures collapse to one code each — `invalid_credentials`,
`invalid_refresh_token` — so a response cannot be used to enumerate accounts or sessions.

## Workspaces and members

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces` | authenticated; the creator becomes owner |
| `GET` | `/api/v1/workspaces` | authenticated; only your memberships |
| `GET` | `/api/v1/workspaces/{workspace_id}` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/members` | `view` |
| `POST` | `/api/v1/workspaces/{workspace_id}/members` | `manage_members` |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | `manage_members` |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | `manage_members` |

Every membership mutation writes an audit event in the same transaction as the change, so the log
cannot record something the database rolled back.

Codes: `slug_already_exists`, `user_not_found`, `member_not_found`, `member_already_exists`,
`cannot_manage_role`, `last_owner`.

## Documents

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents` | `upload_documents` |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/policy` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/status` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/download` | `view` |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/retry` | `upload_documents` |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/archive` | `manage_documents` |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/restore` | `manage_documents` |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | `manage_documents` |

**Upload** is `multipart/form-data` with a single `file` part. Validation runs before a byte
reaches storage: sanitized basename, allowed extension, declared MIME matching the extension, and
content sniffing (PDF/DOCX magic, UTF-8 text without NULs). PDF, TXT, Markdown, and DOCX are
accepted. Content is deduplicated per workspace by SHA-256. Upload and download-link issuance are
both audited.

Codes: `invalid_filename`, `unsupported_file_type`, `mime_mismatch`, `content_mismatch`,
`empty_file` (`422`); `file_too_large`, `workspace_document_limit_reached`,
`workspace_storage_quota_exceeded` (`413`); `duplicate_document` (`409`).

**`/policy`** reports this deployment's effective limits. Read it rather than compiling a cap in:
`MAX_UPLOAD_BYTES` is per-deployment, so a hard-coded browser check will eventually reject files
the API accepts or advertise ones it will refuse.

**`/status`** returns the live stage walk — `uploaded → validating → scanning → parsing → ocr →
normalizing → chunking → embedding → indexing → ready` — with attempt counts and any failure. It
also reports `retryable`, which is scoped to *this* caller: it accounts for the document's state,
whether its failure was permanent, and the caller's own role. Render the control from that field,
never from `status == "failed"`.

**`/download`** returns a short-lived presigned URL against a private bucket
(`DOWNLOAD_URL_TTL_SECONDS`). It is minted per request and is never embedded in a page.

**Lifecycle rules**, each of which is a refusal a client should expect:

- Retry requires `status == failed` and an unarchived document. A quarantined document is never
  reprocessed — the verdict is terminal (`document_not_retryable`).
- Retry refuses a deterministic failure — a hash mismatch, an unparseable file, a provenance
  violation would fail identically on the same bytes (`document_permanently_failed`).
- Delete requires the document to be archived first (`document_delete_requires_archive`) and
  refuses while a job is `RUNNING` (`document_processing`).
- Archiving is a reversible timestamp, not a status rewrite, and it withdraws the document from
  **evidence** immediately — not just from list views.

Delete makes no storage call. It commits the row deletion together with a durable purge record; the
worker deletes the objects afterwards and retries until it succeeds. A storage outage delays the
purge instead of stranding a document whose bytes are already gone.

## Retrieval

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/retrieval/search` | `query` |

Runs lexical and dense retrieval, fuses the rankings with reciprocal-rank fusion, and reranks.
`top_k` is clamped to `RETRIEVAL_MAX_TOP_K`. Optional `document_id` and `language` filters narrow
both retrievers identically. The response carries a `RetrievalTrace` — candidate counts, per-source
ranks, fused scores, filters, timings — which contains no query text and no chunk content, so it is
safe to log.

## Answers

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/answer` | `query` |

The one-shot grounded answer. It writes no conversation, message, or citation — which is why a
viewer holding only the read-only `query` capability may call it — but it is **not** a read-only
request: every run appends a `rag.answer` audit row carrying the workspace, the actor, and the
non-sensitive trace, and that row commits with the request. Treat the endpoint as "persists no
answer content", not as "touches nothing". `top_k` is clamped to `RAG_MAX_TOP_K`.

The response is an outcome, not prose. `outcome` is `answered`, `partial` (some candidate claims
were dropped), or `abstained`; `abstained` is also a boolean of its own. Treat `answered` and
`partial` as the only outcomes carrying an answer — on an abstention the `answer` text is a fixed
refusal and `claims` is empty.

An abstention carries the operational `decision`, its `decision_reason`, an `abstention_reason`,
and `confidence` — which is `0.0` on every withheld answer and must be read as an absence rather
than a score. Three distinct decisions all report `abstained`: no usable evidence, a question that
needs narrowing, and evidence that contradicts itself. A client that renders only the status cannot
tell a reader which happened, and those are the difference between "there is nothing here", "ask me
differently", and "a human should look at this".

Each claim carries its own `citation` inline, plus `index`, `verdict`, `confidence`, and an
`explanation`. The `trace` is the same non-sensitive `RagTrace` described above: gate decisions,
counts, and timings, with no query, evidence, or answer text.

## Citations

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/citations/resolve` | `query` |

Resolves a citation to `supporting_text`, read back from the stored chunk at the citation's
offsets. That field *is* the proven span — the resolver defines it as `content[start:end]` and
refuses the citation if the quote does not match — so render it whole. Never render the quote the
answer supplied; displaying a model's version of a passage as though the document said it is the
failure this platform exists to prevent.

Resolution is audited, so resolve on demand rather than eagerly: auditing unopened citations would
record reading that never happened.

Codes: `citation_not_found`, `citation_out_of_range`, `citation_quote_mismatch`.

## Conversations

| Method | Path | Capability |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations` | `converse` |
| `GET` | `/api/v1/workspaces/{workspace_id}/conversations` | `view` |
| `GET` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | `view` |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | `converse` |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream` | `converse` |
| `PUT` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | `converse` |
| `GET` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | `view` |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | `converse` + author or `manage_conversations` |

Asking returns the same body as `/answer` plus the `message_id` it was stored under. Reading a
thread back returns something different, and the difference matters. A persisted assistant message
carries `answer_status` (`answered`, `partial`, `abstained`), the operational `decision`,
`decision_reason`, `abstention_reason`, and `confidence` — all four because three decisions read as
`abstained`, and a thread keeping only the status would degrade what the answer said on reload. A
user message keeps its original `content`, `normalized_content`, and `transliterated_content`, so a
Tanglish question can be re-run later without guessing what was meant. All the answer fields are
`null` on a user turn, and on rows written before the decision columns existed.

A persisted message exposes `claims` and `citations` as **two lists**, unlike the live answer where
each claim carries its citation inline. Both rows carry the same `claim_index`. **Pair them by
`claim_index`, never by list position** — claims come back sorted and citations come out of an
unordered relationship, so on a multi-claim answer positional pairing eventually files one claim's
passage under another. That is worse than a missing citation: the evidence looks proven and
supports a different statement.

**On `.../messages`, a turn is atomic**: the question and its answer share the request transaction,
and a pipeline failure propagates out of the route, so the transaction rolls back and stores
neither.

**On `.../messages/stream` it is not**, and a client must not assume otherwise. The question is
persisted before streaming begins, and a pipeline failure is caught and reported as an `error`
event rather than raised — the response is already `200`, so there is nothing left to fail with.
The generator then finishes normally and the transaction commits, leaving the question stored with
no answer beside it. That is the same question-only outcome as a stream cut short, described under
[Streaming](#streaming), and it is deliberate: what was asked survives even when answering it did
not.

Turn order comes from `messages.sequence`, not from `created_at` — the two rows of a turn are
written in one transaction and PostgreSQL's `now()` is transaction-start time, so they tie.

Feedback is unique per (message, reviewer), so `PUT` revises rather than accumulates: the row is
that reviewer's current opinion, not a log of their clicks. It is accepted only on assistant turns
(`feedback_requires_answer`).

Deleting a thread removes its turns and citations but never the evidence — a cited chunk is
protected from disappearing under an answer. The deletion is audited *before* the cascade, because
afterwards the audit event is the only remaining record that the history existed.

Codes: `conversation_not_found`, `message_not_found`, `feedback_requires_answer`.

### Streaming

`.../messages/stream` is Server-Sent Events over the same pipeline through the same gates — a
client cannot obtain a less-checked answer by choosing this route. Responses carry
`Cache-Control: no-store` and `X-Accel-Buffering: no`.

| Event | Payload | Meaning |
| --- | --- | --- |
| `stage` | `{"stage": "retrieve"}` | A pipeline node *completed*. These are LangGraph's own updates, not labels announced around the call. |
| `answer` | `{"message_id", ...}` — the full answer body | The terminal result. Emitted exactly once. |
| `error` | `{"code": "answer_failed", "message": ...}` | The pipeline failed after the response was already `200`. |

**The answer is not streamed word by word.** Generation is extractive, so there is no partial text
that is safe to display, and a half-composed answer could show a claim whose citation had not yet
been verified.

**Success is the arrival of an `answer` event, never the end of the body.** A `200` means the
question was accepted, and the question is persisted before the pipeline runs — so a proxy that
closes the stream cleanly after only `stage` events ends the read loop normally with nothing but
the question stored. Treat that as *uncertain* rather than failed: the cut may equally have come
after the answer committed, so re-read the thread instead of asking the user to repeat a question
that may already be answered.

## What the web app adds

The Next.js tier is a backend-for-frontend and holds the session in `httpOnly` cookies, so its own
route handlers exist only where a server action cannot work — byte-level upload progress, a link
navigation for a presigned download, and stream progress. They are relays: they exchange the
cookie for a bearer token server side and never soften an API decision. Each verifies `Origin`
against `X-Forwarded-Host`/`Host` and caps the request body before buffering it, because a route
handler gets none of a server action's built-in protection. See
[`ARCHITECTURE.md`](./ARCHITECTURE.md#upload-and-download-paths).
