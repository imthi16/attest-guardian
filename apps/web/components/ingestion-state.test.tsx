import { render, screen } from "@testing-library/react";

import { describeState, IngestionState, stageLabel, StatusBadge } from "./ingestion-state";
import {
  documentStatusSchema,
  ingestionStageSchema,
  type DocumentProgress,
  type DocumentStatus,
} from "../lib/contracts";

const DOCUMENT_ID = "44444444-4444-4444-8444-444444444444";

function progress(overrides: Partial<DocumentProgress> = {}): DocumentProgress {
  return {
    document_id: DOCUMENT_ID,
    status: "ready",
    job_status: "succeeded",
    stage: "ready",
    attempts: 1,
    error: null,
    updated_at: "2026-07-29T10:00:00Z",
    archived: false,
    retryable: false,
    ...overrides,
  };
}

describe("ingestion state copy", () => {
  it("gives every backend status its own explicit wording", () => {
    // A state with no wording would render as a blank badge, which is exactly
    // the silent ambiguity the product refuses.
    for (const status of documentStatusSchema.options) {
      const copy = describeState(status, false);
      expect(copy.label).not.toBe("");
      expect(copy.explanation).not.toBe("");
    }
  });

  it("gives every ingestion stage a human label", () => {
    for (const stage of ingestionStageSchema.options) {
      expect(stageLabel(stage)).not.toBe("");
    }
  });

  it("says archived even when the document processed successfully", () => {
    // The document is still READY; what changed is that it may no longer be
    // used as evidence, and that is what a reviewer needs to read.
    const copy = describeState("ready", true);

    expect(copy.label).toBe("Archived");
    expect(copy.explanation).toContain("Withdrawn from evidence");
    expect(copy.tone).toBe("withdrawn");
  });

  it("marks states that cannot be cited as not ready", () => {
    const tones: Record<DocumentStatus, string> = {
      pending: "pending",
      processing: "pending",
      ready: "ready",
      failed: "blocked",
      quarantined: "blocked",
    };
    for (const [status, tone] of Object.entries(tones)) {
      expect(describeState(status as DocumentStatus, false).tone).toBe(tone);
    }
  });
});

describe("StatusBadge", () => {
  it("shows the state and its tone", () => {
    render(<StatusBadge archived={false} status="quarantined" />);

    const badge = screen.getByText("Quarantined");
    expect(badge).toHaveAttribute("data-tone", "blocked");
  });
});

describe("IngestionState", () => {
  it("explains a running job stage by stage", () => {
    render(<IngestionState progress={progress({ status: "processing", stage: "ocr" })} />);

    expect(screen.getByText("Processing")).toBeInTheDocument();
    expect(screen.getByText("Reading scanned pages")).toBeInTheDocument();
    expect(screen.getByText("Attempts")).toBeInTheDocument();
  });

  it("reports why a document failed", () => {
    render(
      <IngestionState
        progress={progress({
          status: "failed",
          job_status: "failed",
          stage: "parsing",
          attempts: 3,
          error: "ParserError: no extractable text",
        })}
      />,
    );

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/ParserError: no extractable text/)).toBeInTheDocument();
  });

  it("renders a worker error as text, never as markup", () => {
    // The error string can quote bytes from an untrusted upload. If it were
    // ever injected as HTML, a crafted document could inject script into a
    // reviewer's page.
    const hostile = '<img src=x onerror="alert(1)">';
    const { container } = render(
      <IngestionState progress={progress({ status: "failed", error: hostile })} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(new RegExp("<img src=x"))).toBeInTheDocument();
  });

  it("omits stage and job facts when no job exists yet", () => {
    render(<IngestionState progress={progress({ job_status: null, stage: null })} />);

    expect(screen.queryByText("Furthest stage")).not.toBeInTheDocument();
    expect(screen.queryByText("Job")).not.toBeInTheDocument();
  });
});
