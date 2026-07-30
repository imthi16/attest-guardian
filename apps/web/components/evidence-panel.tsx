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
 * Document titles, section names, and evidence text all originate in uploaded
 * files. They are rendered as text children only, and the highlight is built by
 * slicing the string — never by injecting markup.
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
 * Split the surrounding text into before / quote / after at the page offsets.
 *
 * Falls back to showing the passage unhighlighted if the offsets do not describe
 * a slice of this text. A wrong highlight would misrepresent which words the
 * citation actually covers, and that is worse than no highlight.
 */
export function splitForHighlight(
  text: string,
  start: number,
  end: number,
): Readonly<{ after: string; before: string; quote: string }> {
  if (start < 0 || end > text.length || start >= end) {
    return { after: "", before: "", quote: text };
  }
  return {
    after: text.slice(end),
    before: text.slice(0, start),
    quote: text.slice(start, end),
  };
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
  const parts = splitForHighlight(
    citation.supporting_text,
    citation.page_quote_char_start,
    citation.page_quote_char_end,
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
        {citation.ocr_engine === null ? null : (
          // Scanned text is read by OCR and can be misread, so the reader is
          // told when a passage came from a picture rather than from text.
          <span className="evidence-ocr">Read by OCR ({citation.ocr_engine})</span>
        )}
      </figcaption>
      <blockquote className="evidence-quote">
        {parts.before}
        <mark>{parts.quote}</mark>
        {parts.after}
      </blockquote>
    </figure>
  );
}
