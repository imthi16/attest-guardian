"use client";

/**
 * The evidence behind one claim, proven before it is shown.
 *
 * Opening a citation resolves it server side and renders `supporting_text` —
 * text read back from the stored document at validated offsets — never the quote
 * the answer supplied. That distinction is the whole point: if a citation does
 * not match its source, this fails visibly instead of displaying the model's
 * version of the passage as though the document said it.
 *
 * Resolution happens on open rather than for every citation up front, because
 * the API audits each resolution; resolving citations nobody looked at would
 * make the audit log describe reading that never happened.
 *
 * What is shown is exactly the proven passage. The resolver returns the text it
 * read back at the validated offsets, so the whole of it is the quote; the page
 * offsets locate that passage inside its page and are stated as a locator rather
 * than used to highlight part of it.
 *
 * Document titles, section names, and evidence text all originate in uploaded
 * files. They are rendered as text children only — never by injecting markup.
 */
import { useState } from "react";

import { Feedback } from "./feedback";
import { resolveCitationAction, type CitationResolution } from "../app/conversation-actions";
import type { CitationRecord } from "../lib/contracts";

type EvidencePanelProps = Readonly<{
  citation: CitationRecord;
  index: number;
  workspaceId: string;
}>;

type PanelState =
  | Readonly<{ kind: "closed" }>
  | Readonly<{ kind: "failed"; code: string; message: string }>
  | Readonly<{ kind: "loading" }>
  | Readonly<{ kind: "open"; resolution: Extract<CitationResolution, { ok: true }> }>;

/**
 * Where the passage sits in its page, as a locator a reader can act on.
 *
 * The offsets are positions in the full page text, not in `supporting_text` —
 * that field is the proven quote and nothing more — so they are stated rather
 * than used to slice it. Returns `null` when there is no page to locate it in.
 */
export function describeLocation(
  pageNumber: number | null,
  start: number,
  end: number,
): string | null {
  if (pageNumber === null || start < 0 || end <= start) {
    return null;
  }
  return `Page ${pageNumber}, characters ${start + 1}–${end}`;
}

/**
 * How much the reading of this passage can be trusted, in words.
 *
 * Born-digital text is read exactly; OCR text is worth its recorded confidence,
 * and OCR text with *no* recorded confidence is of unknown reliability — which
 * must never be presented as if it were a good reading.
 */
export function describeReliability(
  ocrEngine: string | null,
  ocrConfidence: number | null,
  supportScore: number | null,
): string | null {
  if (ocrEngine === null) {
    return null;
  }
  if (ocrConfidence === null || supportScore === null) {
    return `Read by OCR (${ocrEngine}); the engine recorded no confidence, so how well it read this passage is unknown.`;
  }
  const percent = `${Math.round(supportScore * 100)}%`;
  const band = supportScore >= 0.9 ? "high" : supportScore >= 0.7 ? "moderate" : "low";
  return `Read by OCR (${ocrEngine}) with ${band} confidence (${percent}). Check the page image before relying on exact figures.`;
}

export function EvidencePanel({ citation, index, workspaceId }: EvidencePanelProps) {
  const [state, setState] = useState<PanelState>({ kind: "closed" });
  const panelId = `evidence-${citation.chunk_id}-${index}`;

  async function open(): Promise<void> {
    if (state.kind === "open") {
      setState({ kind: "closed" });
      return;
    }
    setState({ kind: "loading" });
    const resolution = await resolveCitationAction(workspaceId, {
      chunk_id: citation.chunk_id,
      document_version_id: citation.document_version_id,
      quote: citation.quote_text,
      quote_char_end: citation.quote_end,
      quote_char_start: citation.quote_start,
    });
    setState(
      resolution.ok
        ? { kind: "open", resolution }
        : { code: resolution.code, kind: "failed", message: resolution.message },
    );
  }

  return (
    <div className="evidence">
      <button
        aria-controls={panelId}
        aria-expanded={state.kind === "open"}
        className="citation-button"
        onClick={open}
        type="button"
      >
        <span className="citation-marker">{index + 1}</span>
        <span className="citation-summary">
          {citation.page_number === null ? "Evidence" : `Page ${citation.page_number}`}
          {state.kind === "open" ? " — hide" : " — show the passage"}
        </span>
      </button>

      <div className="evidence-body" id={panelId}>
        {state.kind === "loading" ? (
          <p aria-live="polite" className="evidence-loading">
            Checking this citation against the document…
          </p>
        ) : null}

        {state.kind === "failed" ? (
          <Feedback
            code={state.code}
            id={`${panelId}-error`}
            message={`This citation could not be verified against its document, so the passage is not shown. ${state.message}`}
            tone="error"
          />
        ) : null}

        {state.kind === "open" ? <ResolvedEvidence resolution={state.resolution} /> : null}
      </div>
    </div>
  );
}

function ResolvedEvidence({
  resolution,
}: Readonly<{ resolution: Extract<CitationResolution, { ok: true }> }>) {
  const { citation } = resolution;
  const location = describeLocation(
    citation.page_number,
    citation.page_quote_char_start,
    citation.page_quote_char_end,
  );
  const reliability = describeReliability(
    citation.ocr_engine,
    citation.ocr_confidence,
    citation.support_score,
  );
  return (
    <figure className="evidence-card">
      <figcaption className="evidence-provenance">
        <span className="evidence-document">{citation.document_title}</span>
        <span className="evidence-locator">
          Version {citation.version_number}
          {citation.page_number === null ? "" : ` · page ${citation.page_number}`}
          {citation.section === null ? "" : ` · ${citation.section}`}
        </span>
        {location === null ? null : <span className="evidence-offsets">{location}</span>}
        {reliability === null ? null : (
          // Scanned text is read by OCR and can be misread, so the reader is
          // told both that the passage came from a picture and how well it was
          // read — an engine name alone cannot separate a clean scan from a bad
          // one.
          <span className="evidence-ocr">{reliability}</span>
        )}
      </figcaption>
      {/*
        The whole passage is the quote: the resolver returns the text it read
        back from the document at the validated offsets, having refused the
        citation if it did not match. Marking all of it is therefore accurate —
        highlighting a slice of it using the page offsets would mark the wrong
        words, since those positions index the page and not this string.
      */}
      <blockquote className="evidence-quote">
        <mark>{citation.supporting_text}</mark>
      </blockquote>
    </figure>
  );
}
