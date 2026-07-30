import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EvidencePanel, splitForHighlight } from "./evidence-panel";
import { resolveCitationAction } from "../app/conversation-actions";
import type { CitationRecord } from "../lib/contracts";

vi.mock("../app/conversation-actions", () => ({ resolveCitationAction: vi.fn() }));

const mockedResolve = vi.mocked(resolveCitationAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

const citation: CitationRecord = {
  chunk_id: "44444444-4444-4444-8444-444444444444",
  document_id: "55555555-5555-4555-8555-555555555555",
  document_version_id: "66666666-6666-4666-8666-666666666666",
  claim_text: "Payment is due within thirty days.",
  quote_text: "due within thirty days",
  quote_start: 23,
  quote_end: 45,
  page_number: 4,
};

const resolved = {
  ok: true as const,
  citation: {
    document_id: citation.document_id,
    document_title: "Lease agreement",
    document_version_id: citation.document_version_id,
    version_number: 1,
    chunk_id: citation.chunk_id,
    chunk_index: 0,
    page_number: 4,
    section: "Payment terms",
    language: "eng",
    quote: "due within thirty days",
    quote_char_start: 23,
    quote_char_end: 45,
    page_quote_char_start: 23,
    page_quote_char_end: 45,
    supporting_text: "The invoice payment is due within thirty days of receipt.",
    ocr_engine: null,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("splitForHighlight", () => {
  it("splits the passage at the cited offsets", () => {
    expect(splitForHighlight("abcdef", 2, 4)).toEqual({
      before: "ab",
      quote: "cd",
      after: "ef",
    });
  });

  it("shows the passage unhighlighted rather than highlighting the wrong words", () => {
    // A wrong highlight would misrepresent which words the citation covers,
    // which is worse than no highlight at all.
    for (const [start, end] of [
      [-1, 3],
      [2, 99],
      [4, 4],
      [5, 2],
    ]) {
      const parts = splitForHighlight("abcdef", start, end);
      expect(parts).toEqual({ before: "", quote: "abcdef", after: "" });
    }
  });
});

describe("EvidencePanel", () => {
  it("resolves on open and shows the text read back from the document", async () => {
    mockedResolve.mockResolvedValue(resolved);
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);

    const button = screen.getByRole("button", { name: /Page 4/ });
    expect(button).toHaveAttribute("aria-expanded", "false");
    // Nothing is resolved until it is opened: resolution is audited, so
    // resolving unopened citations would log reading that never happened.
    expect(mockedResolve).not.toHaveBeenCalled();

    await userEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText("Lease agreement")).toBeInTheDocument();
    });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(mockedResolve).toHaveBeenCalledWith(WORKSPACE_ID, {
      chunk_id: citation.chunk_id,
      document_version_id: citation.document_version_id,
      quote: citation.quote_text,
      quote_char_end: citation.quote_end,
      quote_char_start: citation.quote_start,
    });

    // The displayed passage is `supporting_text`, not the answer's quote, and
    // it is split into before/highlight/after nodes rather than one string.
    const passage = document.querySelector(".evidence-quote");
    expect(passage).toHaveTextContent("The invoice payment is due within thirty days of receipt.");
    const highlighted = document.querySelector("mark");
    expect(highlighted).toHaveTextContent("due within thirty days");
    expect(screen.getByText(/page 4 · Payment terms/)).toBeInTheDocument();
  });

  it("says the citation could not be verified instead of showing it anyway", async () => {
    // If a citation does not match its source, displaying the model's version of
    // the passage would be the exact failure this platform exists to prevent.
    mockedResolve.mockResolvedValue({
      ok: false,
      code: "citation_out_of_range",
      message: "The quoted span is outside the cited chunk.",
    });
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: /Page 4/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("could not be verified");
    expect(alert).toHaveTextContent("Reference: citation_out_of_range");
    expect(document.querySelector("mark")).toBeNull();
  });

  it("warns when the evidence was read by OCR", async () => {
    mockedResolve.mockResolvedValue({
      ok: true,
      citation: { ...resolved.citation, ocr_engine: "tesseract" },
    });
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: /Page 4/ }));

    expect(await screen.findByText(/Read by OCR \(tesseract\)/)).toBeInTheDocument();
  });

  it("collapses again on a second click", async () => {
    mockedResolve.mockResolvedValue(resolved);
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);
    const button = screen.getByRole("button", { name: /Page 4/ });

    await userEvent.click(button);
    await waitFor(() => expect(button).toHaveAttribute("aria-expanded", "true"));
    await userEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Lease agreement")).not.toBeInTheDocument();
  });

  it("labels evidence with no page number without inventing one", async () => {
    mockedResolve.mockResolvedValue(resolved);
    render(
      <EvidencePanel
        citation={{ ...citation, page_number: null }}
        index={2}
        workspaceId={WORKSPACE_ID}
      />,
    );

    expect(screen.getByRole("button", { name: /Evidence/ })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});
