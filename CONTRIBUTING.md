# Contributing

Read [`AGENTS.md`](./AGENTS.md) first. It holds the non-negotiable rules and is authoritative for
the whole repository — including for coding agents, which must follow it before changing anything.

## Getting set up

[`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) has the full local setup. The short version:

```bash
cp .env.example .env
make install && make hooks
make infra-up && make migrate-up
make check                      # the gate every change must pass
```

## The shape of a change

One issue, one branch, one reviewable pull request against `main`. Branches are prefixed `feat/`,
`fix/`, `docs/`, `test/`, or `chore/`; commits are Conventional Commits, kept small and intentional.
Open a draft pull request early for anything large, complete every section of the template, and
never merge automatically.

Run `make check` before opening the pull request: formatting, linting, strict typing, both test
suites with their coverage floors, the evaluation, the production build, and Compose validation.

## What review will ask about

These are the rules a change most often trips over, and the reasons a reviewer will send one back.
Each is stated in full in `AGENTS.md`; this is what they look like in practice.

**Authorization belongs in the data layer.** A route check is necessary and not sufficient. Tenant
data goes through `WorkspaceScopedRepository`, and row-level security sits underneath. A filter
applied after retrieval will be sent back.

**Provenance is preserved end to end.** Document id, version, page, section, offsets, language, OCR
engine, and confidence travel with every chunk. Chunk content must equal
`page_text[char_start:char_end]` exactly — the chunker computes boundaries and never rewrites text,
because citation resolution proves a quote by re-reading that span. Normalize at read time instead.

**Document-derived content is untrusted data.** Uploaded files, OCR output, and retrieved chunks are
quoted, scored, and cited — never obeyed, never rendered as markup, never previewed.

**Never tokenize with `[^\W_]+`.** Python's `\w` excludes Unicode marks, and a Tamil vowel sign is a
spacing combining mark, so that regex splits Tamil words into bare consonants and silently inflates
every lexical score built on them. Use `app.language.tokenize` or `match_tokens`. This one has bitten
six modules at once.

**Any change to how text becomes features bumps `EMBEDDING_MODEL_VERSION`.** It salts the vectors and
scopes every search; leaving it means old vectors are compared against new queries and return
plausible wrong neighbours with nothing to report it.

**A citation must support the exact claim** — numbers, dates, conditions, negation. A model's
self-reported confidence is never a confidence score; combine retrieval, rerank, OCR, and
normalization signals.

**The MVP is read-only.** No new external side effect without explicit approval and a threat-model
update. See [`docs/THREAT_MODEL.md`](./docs/THREAT_MODEL.md#what-would-invalidate-this-model) for
the changes that reopen that document rather than being absorbed.

## Tests

Behavioural changes need tests. AI- and RAG-affecting changes need a measurable regression or
evaluation case, not only unit tests — `make evaluate` and the suites under
`apps/api/tests/evaluation/`.

**Coverage floors are 90% on both sides and are not negotiable.** Do not lower a floor, weaken a
threshold, or edit an evaluation dataset to make a change pass; add real tests instead. Lowering a
floor is a change to what the product promises: it belongs in its own commit, with the reason, and
never bundled with the change that needed it lowered.

Note that running a *subset* of the API suite trips the coverage gate, because coverage is then
measured against that subset rather than the application. A failing coverage line on a single file
is not a signal that the change is broken — run the full suite for the real number.

## Contracts and mirrors

Several files exist in two places on purpose, and each pair has a test that fails the build on
drift. If you change one side, change the other in the same commit:

| Source of truth | Mirror | Pinned by |
| --- | --- | --- |
| The FastAPI application | `packages/contracts/openapi.json` (`make contracts`) | `apps/api/tests/test_contracts.py` |
| `packages/contracts/openapi.json` | `apps/web/lib/contracts.ts` | `contracts.drift.test.ts`, `attest-api.drift.test.ts` |
| `apps/api/app/auth/permissions.py` | `apps/web/lib/permissions.ts` | `permissions.test.ts` |
| `apps/api/app/documents/validation.py` | `apps/web/lib/upload-rules.ts` | its own test |
| The application and Makefile | `docs/API.md`, and the docs' links | `apps/api/tests/test_documentation.py` |

Regenerate the OpenAPI document deliberately and read the diff. It is the contract two separate
programs agree by.

## Documentation

Update the docs in the same change, not afterwards. Architecture-level reasoning goes in
[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md), the HTTP surface in
[`docs/API.md`](./docs/API.md), configuration in
[`docs/CONFIGURATION.md`](./docs/CONFIGURATION.md), and security consequences in
[`docs/SECURITY.md`](./docs/SECURITY.md) or
[`docs/THREAT_MODEL.md`](./docs/THREAT_MODEL.md).

A new limitation goes in [`docs/ROADMAP.md`](./docs/ROADMAP.md). Write it down even — especially —
when it is unflattering: an unmentioned limitation reads as a claim, and the value of every other
number in this repository rests on the gaps being stated.

## Never commit

Secrets, credentials, real or private documents, PII, or generated model artifacts. `gitleaks` runs
in CI over the full history as a second line, not as the first one. Test data is synthetic
throughout, and evaluation datasets are read by CI, printed into reports, and cloned by anyone with
the repository — treat them accordingly.

Report a suspected vulnerability privately rather than in an issue; see [`SECURITY.md`](./SECURITY.md).
