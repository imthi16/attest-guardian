# Safety service

Prompt-injection defence for Attest Guardian. Uploaded files, OCR output, and retrieved chunks are
**untrusted data**; this service finds passages that try to act as *instructions* to the assistant,
scores them, and quarantines poisoned documents so they can never reach retrieval or generation.

The MVP implementation lives in `apps/api/app/safety` (issue #17). The service directory documents
the boundary; issue #18 (security hardening, already merged) layers headers, CORS, and rate limits
on top.

## What it detects

`InjectionDetector` (`app/safety/detector.py`) runs three deterministic passes over untrusted text
and merges their signals into a bounded `[0, 1]` score:

1. **Normalization.** NFKC folding, homoglyph mapping (Cyrillic/Greek look-alikes), zero-width and
   soft-hyphen stripping, and a *de-spaced* view (`i g n o r e` -> `ignore`) so obfuscation cannot
   evade the rules. Matches are mapped back to offsets in the original text.
2. **Rule matching.** Curated regexes for the attack families in the issue:
   - direct instruction overrides ("ignore all previous instructions"),
   - system/role impersonation ("SYSTEM:", "you are now DAN"),
   - exfiltration / tool-use ("reveal the system prompt", "email the api_key"),
   - indirect, data-borne triggers ("when you read this, ignore the question").
3. **Structural heuristics.** Invisible-character density, letter-spacing that collapses to a
   suspicious keyword, and base64/hex blocks that *decode to* instruction-like text (encoded
   payloads). The detector only measures content; it never decodes-and-obeys or executes anything.

Rules are written to fire on **imperative manipulation**, not on benign prose that merely mentions
instructions, systems, rules, or policies. "This policy supersedes all previous versions" and
"follow these instructions when filing a claim" stay below threshold.

A `SafetyDecision` is derived from the score and the presence of any high-severity signal:
`allow`, `flag` (surface for review), or `quarantine` (block). A single unambiguous high-severity
signal quarantines on its own so it cannot be diluted by surrounding benign text.

## Replaceable classifier

`InjectionDetector` accepts an optional `InjectionClassifier` (a hosted or local ML model). Its
probability is blended into the score as one more bounded term and its signals are merged. The
default build ships without one, keeping the pipeline deterministic and dependency-free.

## Where it is enforced (two boundaries)

1. **Ingestion (primary).** After chunking and *before persistence*, the worker
   (`app/ingestion/worker.py`) runs `InjectionScanner.scan_chunks`. If any chunk is quarantined the
   document is marked `QUARANTINED`, **no chunk rows are written**, a `document.quarantined` audit
   event is recorded, and a privacy-safe `prompt_injection_quarantine` security event is emitted. A
   document is quarantined when *any* chunk crosses the threshold: one hidden instruction anywhere
   can poison every answer that might cite the file.
2. **Retrieval (defence in depth).** Both retrievers (`chunks.lexical_search`,
   `chunk_embeddings.search`) only return chunks belonging to a `READY` document, so even if a
   document is quarantined after chunks were persisted, its text can never enter retrieval,
   reranking, generation, or citation.

## Corpus and evaluation

`tests/injection_corpus.py` is the **versioned** attack/benign corpus (`CORPUS_VERSION`). It spans
English, Tamil, and Tanglish across every attack family plus false-positive traps (policy prose,
job titles, "ignore the noise in the sample"). `tests/test_injection_eval.py` asserts recall and
precision floors: every labelled attack must quarantine and no benign sample may. Thresholds must
not be weakened to make a change pass; add corpus samples and improve the detector instead.

## Configuration

Tunable via `Settings` (see `docs/CONFIGURATION.md`): `INJECTION_SCAN_ENABLED`,
`INJECTION_FLAG_SCORE`, `INJECTION_QUARANTINE_SCORE`, `INJECTION_QUARANTINE_ON_HIGH_SEVERITY`.

## Limitations

- Rule-based detection is high-recall on known patterns but cannot catch every novel phrasing; the
  classifier hook exists to raise recall without weakening the deterministic floor.
- Decoding is limited to base64/hex; other encodings are treated structurally only.
- Quarantine is document-level and read-only (no automated deletion); admin review is via the
  audit log and the persisted `QUARANTINED` status.
