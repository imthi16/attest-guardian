import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EvidencePanel, describeLocation, describeReliability } from "./evidence-panel";
import { resolveCitationAction } from "../app/conversation-actions";
import type { CitationRecord } from "../lib/contracts";

vi.mock("../app/conversation-actions", () => ({ resolveCitationAction: vi.fn() }));

const mockedResolve = vi.mocked(resolveCitationAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

const citation: CitationRecord = {
  chunk_id: "44444444-4444-4444-8444-444444444444",
  document_version_id: "66666666-6666-4666-8666-666666666666",
  claim_index: 0,
  claim_text: "Payment is due within thirty days.",
  quote_text: "due within thirty days",
  quote_start: 23,
  quote_end: 45,
  page_number: 4,
};

/**
 * The resolver's real contract: `supporting_text` is `content[start:end]`, so it
 * *is* the quote — the `page_quote_char_*` fields locate it within its page and
 * do not index into it.
 */
const resolved = {
  ok: true as const,
  citation: {
    document_id: "55555555-5555-4555-8555-555555555555",
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
    // The chunk's own position on the page; `page_quote_char_*` is the sum.
    chunk_char_start: 489,
    chunk_char_end: 620,
    page_quote_char_start: 512,
    page_quote_char_end: 534,
    supporting_text: "due within thirty days",
    ocr_engine: null,
    ocr_confidence: null,
    support_score: 1,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("describeLocation", () => {
  it("states where the passage sits in its page", () => {
    expect(describeLocation(4, 512, 534)).toBe("Page 4, characters 513–534");
  });

  it("says nothing when there is no page or no usable span", () => {
    expect(describeLocation(null, 512, 534)).toBeNull();
    expect(describeLocation(4, -1, 534)).toBeNull();
    expect(describeLocation(4, 534, 534)).toBeNull();
  });
});

describe("describeReliability", () => {
  it("says nothing about born-digital text, which was read exactly", () => {
    expect(describeReliability(null, null, 1)).toBeNull();
  });

  it("reports how well OCR read the passage", () => {
    expect(describeReliability("tesseract", 0.95, 0.95)).toContain("high confidence (95%)");
    expect(describeReliability("tesseract", 0.72, 0.72)).toContain("moderate confidence (72%)");
    expect(describeReliability("tesseract", 0.4, 0.4)).toContain("low confidence (40%)");
  });

  it("calls unrecorded OCR confidence unknown rather than good", () => {
    // Presenting an unmeasured reading as reliable is the failure this wording
    // exists to prevent: unknown is not the same as high.
    expect(describeReliability("tesseract", null, null)).toContain("unknown");
    expect(describeReliability("tesseract", null, null)).not.toContain("%");
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

    // The displayed passage is `supporting_text` — the text read back from the
    // document — not the quote this component was handed. The whole of it is
    // the proven span, so the whole of it is marked; the page offsets are
    // stated as a locator rather than used to slice a string they do not index.
    const passage = document.querySelector(".evidence-quote");
    expect(passage).toHaveTextContent("due within thirty days");
    expect(document.querySelector("mark")).toHaveTextContent("due within thirty days");
    expect(screen.getByText(/page 4 · Payment terms/)).toBeInTheDocument();
    expect(screen.getByText("Page 4, characters 513–534")).toBeInTheDocument();
  });

  it("shows the resolved passage even when it differs from the stored quote", async () => {
    // The stored quote is never displayed. If the two ever disagreed, showing
    // the answer's version would be the exact failure this panel prevents.
    mockedResolve.mockResolvedValue({
      ok: true,
      citation: { ...resolved.citation, supporting_text: "read back from the document" },
    });
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: /Page 4/ }));

    expect(await screen.findByText("read back from the document")).toBeInTheDocument();
    expect(screen.queryByText(citation.quote_text)).not.toBeInTheDocument();
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

  it("warns when the evidence was read by OCR, and says how well", async () => {
    mockedResolve.mockResolvedValue({
      ok: true,
      citation: {
        ...resolved.citation,
        ocr_engine: "tesseract",
        ocr_confidence: 0.61,
        support_score: 0.61,
      },
    });
    render(<EvidencePanel citation={citation} index={0} workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: /Page 4/ }));

    const warning = await screen.findByText(/Read by OCR \(tesseract\)/);
    // The engine name alone cannot separate a clean scan from an unreliable one.
    expect(warning).toHaveTextContent("low confidence (61%)");
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
