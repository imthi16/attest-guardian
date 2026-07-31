# Screenshots

Four are captured, from a real local stack — the API, the ingestion worker, PostgreSQL, Redis, and
MinIO, with synthetic documents. The rest are named below with what they must show, so a screenshot
added later documents something rather than decorating a page.

This page is the index, not the gallery. Each capture is rendered in the document that makes its
claim — `05-evidence-panel.png` in the README and `DESIGN_RATIONALE.md`, `08-quarantine.png` in
`SECURITY.md`, `05` and `07` in `DEMO.md` — because a reader following the main documentation should
see the evidence, not a filename. `04-answer.png` is rendered only here, for the reason under its
own heading.

**All four carry a defect.** They were taken against `next dev`, so the Next.js development
indicator — a red badge reading *1 Issue* — sits in the bottom-left corner of `04` and `05`. It is
the dev overlay reporting on the dev server, not a failure in the answer above it, but an unexplained
error badge in a screenshot whose entire purpose is credibility reads as one. Every capture in this
set should be retaken against a production build (`make build`, or the `application` compose
profile), where the overlay does not exist.

Add a file under the exact name below, then reference it from the linked document. Until a file
exists, do not add its image link — a broken image is worse than an absent one, and
`apps/api/tests/test_documentation.py` fails the build both on a link to a file that is not there
and on an image committed here that no document renders.

## Captured

### `04-answer.png` — a grounded answer

![A grounded answer with a caution badge, banded confidence, a per-claim SUPPORTED verdict, the verifier that checked it, and the resolved citation.](./04-answer.png)

The claim carries `SUPPORTED` and the verifier that produced it (`entailment-verifier-v1`), not a
bare assertion. Confidence is banded — *Low (42%)* — because a bare percentage invites false
precision, and the caution badge is keyed on the decision rather than the status.

**It is the same frame as `05-evidence-panel.png`,** scrolled down far enough to lose the
conversation title and gain the feedback controls. Both were captured with the evidence panel
already expanded, so the pair cannot illustrate the two beats the demo script asks for — *read the
answer*, then *open the panel*. That is why `DEMO.md` renders `05` alone there rather than the same
screen twice. Retaking `04` with the panel collapsed is what makes it a distinct capture, and until
then it earns its place only as the wider view of the answer card.

### `05-evidence-panel.png` — the citation resolved against stored content

![The evidence panel showing travel-expense-policy.pdf, Version 1, page 1, characters 139-215, with the proven passage highlighted.](./05-evidence-panel.png)

The most important capture in the set. `Page 1, characters 139–215` is the citation's range, and the
highlighted text was read back from the stored chunk at those offsets by `/citations/resolve` —
not supplied by the answer. A quote that did not match would render a failure here instead of a
passage.

Section and OCR reliability are absent here **because this evidence has neither**: the chunker
assigned no section, and the source is a born-digital PDF that was read exactly rather than scanned.
Both lines are conditional by design. A capture showing OCR provenance needs scanned evidence and
belongs with `06-tanglish.png`; the panel never displays the chunk's language.

### `07-abstention.png` — a refusal that says which kind it is

![An abstention reading "There is related material, but nothing that answers this exact question", with confidence 0%.](./07-abstention.png)

*"There is related material, but nothing that answers this exact question"* — the
`ask_for_clarification` decision, distinct from "there is nothing here" and from "a human should
look at this". Confidence is `0%`, which a reader must take as an absence rather than a score.

Cropped to the card from a full-page capture; nothing else is altered. Worth retaking full-frame
alongside `09-archived.png`, since the two belong side by side.

### `08-quarantine.png` — quarantine is terminal

![The document library showing vendor-notice.md as QUARANTINED alongside two READY documents, offering only Download and Archive.](./08-quarantine.png)

`vendor-notice.md` carried an injected instruction and was quarantined during ingestion, before any
chunk was persisted. Note what the row does **not** offer: there is no retry control, because the
verdict is terminal at every role.

What this image shows is the *state and its consequence*, not the cause — the library lists status
and actions, and the worker's reason lives on the document detail page. Do not read it as evidence
that injection detection produced the verdict; `03-quarantine-reason.png` below is the capture that
would establish that.

## Still to capture

| File | Scene | Must show | Belongs in |
| --- | --- | --- | --- |
| `01-roles.png` | 1 | The same workspace as a viewer and as an owner, side by side — no composer, no upload control for the viewer | `DEMO.md`, `ARCHITECTURE.md` |
| `02-ingestion.png` | 2 | The document detail page mid-run, with a named stage and the attempt count | `DEMO.md` |
| `03-upload-rejected.png` | 2 | An upload refused with a stable code (`content_mismatch` or `unsupported_file_type`) | `DEMO.md`, `SECURITY.md` |
| `03-quarantine-reason.png` | 6 | The **detail** page for a quarantined document: the worker's reported reason and the absent retry control in one frame, so the image establishes *why* the verdict happened | `DEMO.md`, `SECURITY.md` |
| `04-answer.png` (retake) | 4 | The answer card with the evidence panel **collapsed**, so that it and `05` are a before and after rather than one frame twice. Against a production build, so the dev overlay is absent | `DEMO.md` |
| `06-tanglish.png` | 4 | A romanized-Tamil question answered from a Tamil-script document, with the Tamil citation legible. No longer blocked — the transliterator was fixed, and `eettiya viduppu ethanai naal` now answers from the Tamil leave policy | `README.md`, `DEMO.md` |
| `09-archived.png` | 7 | The same question abstaining after the source document was archived | `DEMO.md` |
| `10-evaluation.png` | 8 | `make evaluate` output with the thresholds table and the abstention line | `README.md`, `EVALUATION.md` |

## Rules for a capture

- **Synthetic content only.** No tenant document, no personal data, no real credential, no real
  email address. The demo corpus is written for this purpose; use it.
- **Redact nothing after the fact.** If a capture would need redacting, retake it with synthetic
  data — a black box over a field is an invitation to look for the original.
- **No tokens or ids that resolve.** Presigned URLs, bearer tokens, and workspace ids must not be
  legible; keep them out of the frame rather than blurring them.
- **Light theme, 1440px wide, PNG.** Consistent framing makes two captures comparable.
- **Capture against a production build, never `next dev`.** The development overlay puts an error
  indicator in the corner of the frame, and a reader cannot tell it is reporting on the dev server
  rather than on the answer beside it.
- **A capture must show a claim this project makes.** If it only shows that the app renders, it is
  not worth the diff.
