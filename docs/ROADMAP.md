# Roadmap and Limitations

What is built, what is deliberately not, and what to do next. Limitations here are gathered from
the documents that own them and linked back — this page is the index, not a second source of truth.

The organizing rule: **a gap is stated, never implied.** An unmentioned limitation reads as a
claim, so anything a reader could reasonably assume works and does not is named below.

## Delivered

All twenty-six planned units of work are complete. Each was one issue, one branch, and one
reviewable pull request against `main`.

| # | Feature | Where it lives |
| --- | --- | --- |
| 1 | Monorepo, CI, Docker, application skeletons | `Makefile`, `.github/workflows/ci.yml` |
| 2 | Schema, migrations, tenant isolation, audit foundation | `apps/api/app/db/`, `infra/migrations/` |
| 3 | Authentication — Argon2id, JWT, rotating refresh tokens | `apps/api/app/auth/` |
| 4 | Workspaces, RBAC, row-level security | `apps/api/app/auth/permissions.py`, migration `0003` |
| 5 | Secure upload, validation, object storage | `apps/api/app/documents/`, `apps/api/app/storage/` |
| 6 | Async ingestion — queue, stages, retries, dead-letter | `apps/api/app/ingestion/` |
| 7 | PDF parsing and OCR | `apps/api/app/parsing/` |
| 8 | Chunking with validated provenance | `apps/api/app/chunking/` |
| 9 | Tamil/Tanglish detection, normalization, transliteration | `apps/api/app/language/` |
| 10 | Multilingual embeddings and pgvector persistence | `apps/api/app/embeddings/` |
| 11 | Permission-filtered hybrid retrieval with RRF | `apps/api/app/retrieval/` |
| 12 | Multilingual reranking | `apps/api/app/reranking/` |
| 13 | Grounded RAG answer pipeline | `apps/api/app/rag/` |
| 14 | Structured citations | `apps/api/app/citations/` |
| 15 | Atomic claim verification | `apps/api/app/verification/` |
| 16 | Confidence calibration and abstention | `apps/api/app/decision/` |
| 17 | Prompt-injection defence | `apps/api/app/safety/` |
| 18 | Security hardening | `apps/api/app/security/`, [`SECURITY.md`](./SECURITY.md) |
| 19 | Authentication and workspace UI | `apps/web/app/(auth)`, `apps/web/lib/` |
| 20 | Document management UI and lifecycle | `apps/api/app/documents/lifecycle.py`, `apps/web/components/` |
| 21 | Chat and evidence UI, conversations API | `apps/api/app/conversations/`, `apps/web/components/evidence-panel.tsx` |
| 22 | Evaluation framework | `evaluation/`, `apps/api/app/evaluation/` |
| 23 | Cross-cutting testing and contract pinning | `packages/contracts/openapi.json`, the drift suites |
| 24 | Observability | `apps/api/app/observability/`, `infra/monitoring/` |
| 25 | Production deployment | `deploy/`, `scripts/`, [`DEPLOYMENT.md`](./DEPLOYMENT.md) |
| 26 | Final product documentation | This directory |

## Limitations

### The models are deterministic stand-ins

Embeddings, reranking, generation, and malware scanning ship local implementations behind the real
interfaces. They are correct wiring and honest plumbing; they are not quality.

| Component | Ships | Intended |
| --- | --- | --- |
| Embeddings | `LocalHashingEmbeddingProvider` — 1024-dim, deterministic, no semantics | BGE-M3 |
| Reranking | `LocalLexicalReranker` — coverage and Jaccard over normalized tokens | `bge-reranker-v2-m3` |
| Generation | `ExtractiveGenerator` — selects the best-covering sentence | A hosted LLM behind `AnswerGenerator` |
| Malware scanning | Recognises the EICAR test signature only | A real engine behind `MalwareScanner` |

**Consequence:** absolute retrieval and answer numbers are not meaningful. The thresholds in
`evaluation/thresholds.json` are a regression contract for the pipeline's own logic, not a forecast
of production quality. The scanner in particular is *a placeholder, not protection* — see
[`SECURITY.md`](./SECURITY.md).

Swapping any of them changes no calling code, which is the point of the interfaces. What it does
change is the evaluation's absolute numbers, and — for a hosted model — the
[threat model](./THREAT_MODEL.md#what-would-invalidate-this-model), because evidence text would
leave the deployment.

### Answer quality

- **Tanglish queries do not reach Tamil-script documents.** Found by running the stack, not by any
  test. Two compounding faults, either of which alone breaks the feature:

  1. `RuleBasedTransliterator` maps every Latin vowel to an **independent** Tamil letter (`i`→இ,
     `u`→உ) and every consonant to a consonant **plus virama** (`v`→வ்), and never combines them.
     Tamil writes a consonant-vowel cluster with a dependent vowel *sign* — வ + ி = வி — so
     "vidupu" transliterates to `வ்இட்உப்உ` where Tamil would write `விடுபு`. The output is
     well-formed Unicode and malformed Tamil, and matches no real document.
  2. Detection needs ≥40% of a Latin query's words to appear in a 31-word conversational marker
     lexicon (`enna`, `eppadi`, `irukku`, …). Domain-vocabulary Tanglish — the realistic case — is
     classified `english`, so no transliteration is attempted at all.

  **Why nothing caught it.** Every transliterator assertion checks only that the output contains at
  least one character in the Tamil Unicode block, which garbage satisfies. And no Tanglish query in
  `evaluation/datasets/queries.json` is graded against a `tam` chunk — every one is graded against
  `tanglish` and `eng` passages — so the single cross-script case the transliterator exists for is
  absent from the corpus, and the metric stays at 1.00 while the feature does not work.

  This is the same shape as the tokenizer defect in [`EVALUATION.md`](./EVALUATION.md#findings): a
  Tamil-correctness bug behind an assertion too weak to see it. **Tamil-script queries work
  correctly** and are unaffected. Fixing it needs a vowel-sign mapping, an assertion on expected
  output rather than a Unicode-range check, and a cross-script case in the corpus.

- **Abstention recall is 0.86.** One of seven unanswerable questions is answered from a passage that
  mentions the topic without addressing it. Left failing deliberately; no threshold fixes it, and
  it needs semantic rather than lexical matching. [`EVALUATION.md`](./EVALUATION.md#known-limitations)
- **Retrieval scores are near-ceiling and should be read as a floor.** The corpus is small and its
  queries were written against it.
- **Injection detection is rule-based.** High recall on known patterns; a novel phrasing can evade
  it, and decoding covers base64 and hex only. [`services/safety/README.md`](../services/safety/README.md)

### Security and operations

Each of these is described where it is owned; this is the index.

| Limitation | Owner |
| --- | --- |
| Rate limiting is in-process, and `API_REPLICAS` defaults to **2**, so the shipped production deployment already divides every limit in two | [`THREAT_MODEL.md`](./THREAT_MODEL.md#sessions-and-credentials) |
| Rate-limit keys use the socket peer address; behind an unconfigured proxy that is the proxy | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| The request body cap relies on `Content-Length`; a chunked request is bounded only by the streaming upload cap | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| The web CSP permits `'unsafe-inline'` pending a nonce-based policy (the API CSP does not) | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| Server actions carry no CSRF token; protection rests on `SameSite=Lax` plus action-id opacity | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| Row-level security is bypassed by PostgreSQL superusers, so the DB role must not be one | [`DEPLOYMENT.md`](./DEPLOYMENT.md#what-this-deployment-assumes) |
| The web upload relay buffers the whole body in memory, bounded per request | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| Deleted bytes are removed but not shredded; storage versioning or backups may retain a copy | [`SECURITY.md`](./SECURITY.md#residual-risks) |
| Secrets are environment variables, visible to anyone who can `docker inspect` the host | [`DEPLOYMENT.md`](./DEPLOYMENT.md#known-gaps) |
| No zero-downtime deploy — `up -d` replaces containers | [`DEPLOYMENT.md`](./DEPLOYMENT.md#known-gaps) |
| The backup and restore scripts have not been run against a real deployment | [`DEPLOYMENT.md`](./DEPLOYMENT.md#known-gaps) |

### Observability

- **No collector is wired.** The formats are standard — JSON logs, W3C trace context, Prometheus
  metrics — and the pipeline that would ship them is not built.
- **The worker exposes no scrape endpoint.** It is not an HTTP server, so the ingestion alerts in
  `infra/monitoring/alerts.yml` are correct and have no data. This is the first task after a first
  deploy, not a detail.
- **OCR is not instrumented**, so the model-provider alert covers two providers of three.
- **Alert thresholds are starting points.** Nothing has run in production; a claim they are tuned
  would be invented. [`OBSERVABILITY.md`](./OBSERVABILITY.md#limitations)

### Data lifecycle

- **There is no first-class reindex.** Changing `EMBEDDING_MODEL_VERSION` invalidates stored vectors,
  and a `READY` document cannot be re-embedded through the API — retry accepts only `FAILED`
  documents by design. The only path today is archive, delete, re-upload, which loses the document's
  id and history. Plan a version change as a re-ingestion of the workspace.
  [`CONFIGURATION.md`](./CONFIGURATION.md#re-embedding-after-a-version-change)
- **No retention or scheduled deletion workflow.** Deletion is per document and manual.
- **Quarantine withholds content; it does not erase it.** The scan runs before *chunk* persistence,
  so quarantined text is unreachable by retrieval — but the uploaded bytes and the extracted page
  text are already stored by then and stay stored. Permanent deletion is what removes them, and any
  export or retention feature added later must not assume otherwise.
  [`THREAT_MODEL.md`](./THREAT_MODEL.md#prompt-injection--direct-and-indirect)
- **No document versioning through the UI.** The schema carries `document_versions`; re-uploading
  changed content is a new document.

### Not built at all

- No SSO, no MFA, no password reset, no email delivery of any kind.
- No workspace invitations — a member is added by an existing admin, by email address of an
  existing account.
- No admin or moderation surface for quarantined content beyond the audit log and the status.
- No usage metering, billing, or per-tenant quotas beyond document count and stored bytes.
- No mobile application; the web app is responsive but not a native client.
- No i18n of the *interface* — the platform is multilingual, the UI chrome is English.

## What to do next

Ordered by what a reader of this repository would most want fixed, not by effort.

### 1. Abstention recall

The single most valuable number in the evaluation. Note what is and is not failing: 0.86 clears the
declared floor of 0.80, so `make evaluate` exits green — it is the *case* that fails, not the
threshold, and no build is knowingly red. That is exactly why it is written down here. The known
case retrieves a topical passage and answers from it, so the fix is semantic matching between the
question and the candidate evidence rather than lexical overlap — which means it lands naturally
alongside a real embedding model, not before one.

### 2. A real embedding model and reranker

BGE-M3 and `bge-reranker-v2-m3` behind the existing interfaces. This is where the evaluation's
absolute numbers become meaningful, and it requires bumping `EMBEDDING_MODEL_VERSION` — which,
without item 3, means re-ingesting every workspace.

### 3. A reindex operation

Re-run the embed and index stages for documents at a stale version, without destroying the document
row. This is the missing operation that makes item 2 an upgrade rather than a migration event.

### 4. Worker telemetry

A push gateway or sidecar exporter, so the ingestion alerts that are already written can fire. The
current state — correct alerts, no data — is the kind of thing discovered during an incident.

### 5. Redis-backed rate limiting

**Already required, not "before scaling".** `deploy/docker-compose.production.yml` defaults
`API_REPLICAS` to 2, so a deployment that follows the runbook verbatim enforces roughly twice every
configured limit — the credential limiter included. The limiter sits behind `RateLimiter`, so the
change is local. Until it lands, a deployment that needs its limits to mean what they say must set
`API_REPLICAS=1` and accept the throughput; that trade belongs to whoever operates it, which is why
the default was documented rather than quietly changed.

### 6. A real malware scanner

Behind the existing `MalwareScanner` interface. The EICAR-only default is honest about being a
placeholder and is not a control.

### 7. Exercise backup and restore

Against staging, on a schedule, confirming that the restored system answers a question with a
resolvable citation. A backup nobody has restored is a hypothesis, and the first version of these
two scripts looked correct and could not have worked.

### 8. A hosted generator

Behind `AnswerGenerator`. Deliberately last: it is the most visible change and the least
load-bearing one, because the verifier's quote match is what would then stand between a
hallucination and a citation — and that is already built and measured. Doing it before items 1–3
would produce a system that sounds much better and is not measurably better, which is the failure
this project is a response to.
