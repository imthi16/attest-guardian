# Screenshots

**None are committed yet.** This file is the placeholder: it names each capture, what must be
visible in it, and where it belongs, so a screenshot added later documents something rather than
decorating a page.

Add the file here under the exact name below, then reference it from the linked document. Until a
file exists, do not add its image link — a broken image is worse than an absent one, and
`apps/api/tests/test_documentation.py` fails the build both on a link to a file that is not there
and on an image committed here that no document renders.

## Captures

Numbered to match the scenes in [`../DEMO.md`](../DEMO.md).

| File | Scene | Must show | Belongs in |
| --- | --- | --- | --- |
| `01-roles.png` | 1 | The same workspace as a viewer and as an owner, side by side — no composer, no upload control for the viewer | `DEMO.md`, `ARCHITECTURE.md` |
| `02-ingestion.png` | 2 | The document detail page mid-run, with a named stage and the attempt count | `DEMO.md` |
| `03-upload-rejected.png` | 2 | An upload refused with a stable code (`content_mismatch` or `unsupported_file_type`) | `DEMO.md`, `SECURITY.md` |
| `04-answer.png` | 3 | A grounded answer with per-claim verdicts and a banded confidence | `README.md`, `DEMO.md` |
| `05-evidence-panel.png` | 3 | **The most important capture.** The resolved passage highlighted, with document, page, section, and OCR provenance visible | `README.md`, `DEMO.md`, `DESIGN_RATIONALE.md` |
| `06-tanglish.png` | 4 | A romanized-Tamil question answered from a Tamil-script document, with the Tamil citation legible | `README.md`, `DEMO.md` |
| `07-abstention.png` | 5 | A refusal showing *which* decision it was, not just "abstained" | `README.md`, `DEMO.md` |
| `08-quarantine.png` | 6 | A document at `quarantined`, with the reason and no retry control offered | `DEMO.md`, `SECURITY.md` |
| `09-archived.png` | 7 | The same question abstaining after the source document was archived | `DEMO.md` |
| `10-evaluation.png` | 8 | `make evaluate` output with the thresholds table and the failing abstention line | `README.md`, `EVALUATION.md` |

## Rules for a capture

- **Synthetic content only.** No tenant document, no personal data, no real credential, no real
  email address. The demo corpus is written for this purpose; use it.
- **Redact nothing after the fact.** If a capture would need redacting, retake it with synthetic
  data — a black box over a field is an invitation to look for the original.
- **No tokens or ids that resolve.** Presigned URLs, bearer tokens, and workspace ids must not be
  legible; keep them out of the frame rather than blurring them.
- **Light theme, 1440px wide, PNG.** Consistent framing makes two captures comparable.
- **A capture must show a claim this project makes.** If it only shows that the app renders, it is
  not worth the diff.
