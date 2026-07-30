import { render, screen } from "@testing-library/react";

import { ConversationThread } from "./conversation-thread";
import type { ConversationMessage } from "../lib/contracts";

vi.mock("../app/conversation-actions", () => ({
  resolveCitationAction: vi.fn(),
  submitFeedbackAction: vi.fn(),
}));

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";

function question(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "q1",
    role: "user",
    content: "When is the invoice payment due?",
    language: "eng",
    normalized_content: "when is the invoice payment due",
    transliterated_content: "when is the invoice payment due",
    answer_status: null,
    decision: null,
    decision_reason: null,
    confidence: null,
    abstention_reason: null,
    created_at: "2026-07-30T09:00:00Z",
    citations: [],
    claims: [],
    ...overrides,
  };
}

function answer(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "a1",
    role: "assistant",
    content: "Payment is due within thirty days of receipt.",
    language: "eng",
    normalized_content: null,
    transliterated_content: null,
    answer_status: "answered",
    decision: "answer",
    decision_reason: "Every claim is supported.",
    confidence: 0.88,
    abstention_reason: null,
    created_at: "2026-07-30T09:00:05Z",
    citations: [
      {
        chunk_id: "c1",
        document_version_id: "v1",
        claim_index: 0,
        claim_text: "Payment is due within thirty days of receipt.",
        quote_text: "due within thirty days",
        quote_start: 23,
        quote_end: 45,
        page_number: 4,
      },
    ],
    claims: [
      {
        claim_index: 0,
        claim_text: "Payment is due within thirty days of receipt.",
        verdict: "supported",
        confidence: 0.88,
        verifier: "entailment-verifier-v1",
      },
    ],
    ...overrides,
  };
}

function renderThread(messages: readonly ConversationMessage[], canReview = true) {
  render(
    <ConversationThread
      canReview={canReview}
      conversationId={CONVERSATION_ID}
      messages={messages}
      workspaceId={WORKSPACE_ID}
    />,
  );
}

describe("ConversationThread", () => {
  it("shows the question, the verdict, the answer, and its evidence", async () => {
    renderThread([question(), answer()]);

    expect(screen.getByText("When is the invoice payment due?")).toBeInTheDocument();
    expect(screen.getByText("Answered")).toBeInTheDocument();
    // Generation is extractive, so a single-claim answer repeats its claim
    // verbatim: once as the answer, once as the claim it rests on.
    expect(screen.getAllByText("Payment is due within thirty days of receipt.")).toHaveLength(2);
    expect(screen.getByText("High (88%)")).toBeInTheDocument();
    expect(screen.getByText("Supported")).toBeInTheDocument();
    expect(screen.getByText(/entailment-verifier-v1/)).toBeInTheDocument();
    // The citation is openable, which is how evidence is reached.
    expect(screen.getByRole("button", { name: /Page 4/ })).toBeInTheDocument();
  });

  it("shows how a Tanglish question was actually read", () => {
    // Otherwise a wrong transliteration looks like "no results" rather than
    // "you searched for something else".
    renderThread([
      question({
        content: "payment eppo due?",
        language: "tanglish",
        transliterated_content: "பேமெண்ட் எப்போ due?",
      }),
    ]);

    expect(screen.getByText(/Read as:/)).toBeInTheDocument();
    expect(screen.getByText("பேமெண்ட் எப்போ due?")).toBeInTheDocument();
  });

  it("does not repeat an English question as its own reading", () => {
    renderThread([question()]);

    expect(screen.queryByText(/Read as:/)).not.toBeInTheDocument();
  });

  it("presents an abstention as a refusal, not a quiet answer", () => {
    renderThread([
      question(),
      answer({
        answer_status: "abstained",
        confidence: 0.1,
        content: "There is not enough evidence in this workspace to answer that.",
        decision: "abstain",
        decision_reason: null,
        abstention_reason: "No evidence passed the sufficiency threshold.",
        citations: [],
        claims: [],
      }),
    ]);

    expect(screen.getByText("No answer given")).toBeInTheDocument();
    expect(screen.getByText(/No evidence passed the sufficiency threshold./)).toBeInTheDocument();
    // With no supported claim, the reader is told nothing here is citable.
    expect(screen.getByText(/nothing in this answer should be relied on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Page/ })).not.toBeInTheDocument();
  });

  it("distinguishes a question that needs narrowing from having no evidence", () => {
    renderThread([
      question(),
      answer({
        answer_status: "abstained",
        decision: "ask_for_clarification",
        decision_reason: null,
        claims: [],
        citations: [],
      }),
    ]);

    expect(screen.getByText("Needs a narrower question")).toBeInTheDocument();
    expect(screen.queryByText("No answer given")).not.toBeInTheDocument();
  });

  it("flags a contradiction for human review", () => {
    renderThread([
      question(),
      answer({
        decision: "escalate_for_review",
        claims: [
          {
            claim_index: 0,
            claim_text: "The notice period is ninety days.",
            verdict: "contradicted",
            confidence: 0.3,
            verifier: "entailment-verifier-v1",
          },
        ],
      }),
    ]);

    expect(screen.getByText("Needs human review")).toBeInTheDocument();
    expect(screen.getByText("Contradicted")).toBeInTheDocument();
  });

  it("falls back to the status when a stored turn has no decision", () => {
    renderThread([question(), answer({ decision: null, decision_reason: null })]);

    expect(screen.getByText("Answered")).toBeInTheDocument();
  });

  it("offers review controls only to someone who may record feedback", () => {
    renderThread([question(), answer()], false);

    expect(screen.queryByText("Was this answer right?")).not.toBeInTheDocument();
  });

  it("offers the three review verdicts when the caller may review", () => {
    renderThread([question(), answer()]);

    expect(screen.getByRole("button", { name: "Helpful" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not helpful" })).toBeInTheDocument();
    // "Incorrect" is deliberately separate from "not helpful": a refusal may be
    // correct but unhelpful, and only one of those is a grounding failure.
    expect(screen.getByRole("button", { name: "Incorrect" })).toBeInTheDocument();
  });

  it("puts each claim's evidence under that claim, not under its neighbour", () => {
    // Claims come back sorted by index; citations come out of an unordered
    // relationship. Pairing the two lists by position would file the second
    // claim's passage under the first, which is a citation that looks proven and
    // supports a different statement.
    renderThread([
      question(),
      answer({
        content: "- The notice period is ninety days.\n- Payment is due within thirty days.",
        citations: [
          {
            chunk_id: "c2",
            document_version_id: "v1",
            claim_index: 1,
            claim_text: "Payment is due within thirty days.",
            quote_text: "due within thirty days",
            quote_start: 23,
            quote_end: 45,
            page_number: 12,
          },
          {
            chunk_id: "c1",
            document_version_id: "v1",
            claim_index: 0,
            claim_text: "The notice period is ninety days.",
            quote_text: "ninety days",
            quote_start: 4,
            quote_end: 15,
            page_number: 7,
          },
        ],
        claims: [
          {
            claim_index: 0,
            claim_text: "The notice period is ninety days.",
            verdict: "supported",
            confidence: 0.9,
            verifier: "entailment-verifier-v1",
          },
          {
            claim_index: 1,
            claim_text: "Payment is due within thirty days.",
            verdict: "supported",
            confidence: 0.85,
            verifier: "entailment-verifier-v1",
          },
        ],
      }),
    ]);

    const claims = document.querySelectorAll(".claim");
    expect(claims).toHaveLength(2);
    expect(claims[0]).toHaveTextContent("The notice period is ninety days.");
    expect(claims[0]).toHaveTextContent("Page 7");
    expect(claims[1]).toHaveTextContent("Payment is due within thirty days.");
    expect(claims[1]).toHaveTextContent("Page 12");
  });

  it("marks a Tamil question as Tamil so it is not read out as English", () => {
    // The document is `lang="en"`; an unmarked Tamil string is announced with
    // English pronunciation rules, which is not merely accented but unusable.
    renderThread([question({ content: "பணம் எப்போது செலுத்த வேண்டும்?", language: "tam" })]);

    expect(screen.getByText("பணம் எப்போது செலுத்த வேண்டும்?")).toHaveAttribute("lang", "ta");
  });

  it("leaves Tanglish unmarked rather than mislabelling its script", () => {
    // Tamil written in Latin script is neither `ta` nor `en`, and claiming
    // either would make a screen reader read it wrongly with confidence.
    renderThread([question({ content: "payment eppo due?", language: "tanglish" })]);

    expect(screen.getByText("payment eppo due?")).not.toHaveAttribute("lang");
  });

  it("explains a refusal instead of printing its machine code", () => {
    renderThread([
      question(),
      answer({
        answer_status: "abstained",
        content: "There is not enough evidence in this workspace to answer that.",
        decision: "abstain",
        // The early gates put the same stable code in both fields.
        decision_reason: "insufficient_evidence",
        abstention_reason: "insufficient_evidence",
        citations: [],
        claims: [],
      }),
    ]);

    expect(screen.queryByText(/insufficient_evidence/)).not.toBeInTheDocument();
    // Said once, not twice, even though both fields carried it.
    expect(
      screen.getAllByText(/Nothing in this workspace's documents was close enough/),
    ).toHaveLength(1);
  });

  it("keeps the pipeline's own prose when it wrote prose", () => {
    renderThread([
      question(),
      answer({ decision_reason: "the cited evidence is a low-confidence OCR reading" }),
    ]);

    expect(
      screen.getByText("the cited evidence is a low-confidence OCR reading"),
    ).toBeInTheDocument();
  });

  it("keeps a multi-claim answer's line structure", () => {
    // The answer is composed as one `- claim` line per statement; collapsing
    // those newlines runs distinct statements into one sentence.
    renderThread([
      question(),
      answer({ content: "- The notice period is ninety days.\n- Payment is due in thirty." }),
    ]);

    const text = document.querySelector(".answer-text");
    expect(text?.textContent).toContain("\n");
  });

  it("renders a claim with no matching citation without inventing evidence", () => {
    renderThread([
      question(),
      answer({
        citations: [],
        claims: [
          {
            claim_index: 0,
            claim_text: "Something asserted with no citation row.",
            verdict: "unsupported",
            confidence: 0.2,
            verifier: "entailment-verifier-v1",
          },
        ],
      }),
    ]);

    expect(screen.getByText("Unsupported")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /show the passage/ })).not.toBeInTheDocument();
  });
});
