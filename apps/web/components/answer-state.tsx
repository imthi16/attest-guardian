/**
 * Explicit wording for every outcome an answer can have.
 *
 * The platform abstains rather than guesses, and the UI has to be equally
 * explicit: an answer that is partly supported, or refused for lack of
 * evidence, must not look like a confident one. Every value of `AnswerDecision`
 * and `ClaimVerdict` has copy here, so a new backend state cannot render blank.
 *
 * The decision, not the status, drives the wording. Three different decisions
 * all report `answer_status: "abstained"` — no usable evidence, a question that
 * needs narrowing, and something a human should look at — and telling them apart
 * is the difference between "there is nothing here" and "ask me differently".
 *
 * All text on this page comes from this module. Answer text, claim text, and
 * quotes originate in uploaded documents, so they are rendered as text children
 * only.
 */
import type { AnswerDecision, AnswerStatus, ClaimVerdict } from "../lib/contracts";

export type AnswerTone = "answered" | "caution" | "refused" | "review";

type DecisionCopy = Readonly<{ explanation: string; label: string; tone: AnswerTone }>;

const DECISION_COPY: Record<AnswerDecision, DecisionCopy> = {
  answer: {
    label: "Answered",
    explanation: "Every statement below is supported by a citation you can open.",
    tone: "answered",
  },
  answer_with_warning: {
    label: "Answered with caution",
    explanation:
      "Supported, but the evidence is weaker than usual. Check the citations before relying on it.",
    tone: "caution",
  },
  ask_for_clarification: {
    label: "Needs a narrower question",
    explanation:
      "The documents hold related material, but not enough to answer this exactly. Try naming the document, date, or clause you mean.",
    tone: "caution",
  },
  abstain: {
    label: "No answer given",
    explanation:
      "The evidence was not sufficient to support an answer, so none was produced. Nothing here is a guess.",
    tone: "refused",
  },
  escalate_for_review: {
    label: "Needs human review",
    explanation:
      "The evidence conflicts with itself, so answering automatically would be unsafe. A reviewer should look at this.",
    tone: "review",
  },
};

/** Used when a stored turn predates decision persistence and has none. */
const STATUS_FALLBACK: Record<AnswerStatus, DecisionCopy> = {
  answered: {
    label: "Answered",
    explanation: "Supported by the citations below.",
    tone: "answered",
  },
  partial: {
    label: "Partly answered",
    explanation: "Only some of this question could be supported by the evidence.",
    tone: "caution",
  },
  abstained: {
    label: "No answer given",
    explanation: "The evidence was not sufficient to support an answer.",
    tone: "refused",
  },
};

const VERDICT_COPY: Record<ClaimVerdict, Readonly<{ label: string; tone: AnswerTone }>> = {
  supported: { label: "Supported", tone: "answered" },
  unsupported: { label: "Unsupported", tone: "refused" },
  contradicted: { label: "Contradicted", tone: "review" },
  ambiguous: { label: "Ambiguous", tone: "caution" },
};

/**
 * Wording for the stable machine codes the pipeline reports as a reason.
 *
 * `abstention_reason` is always a code, and `decision_reason` is prose except on
 * the early gates, which put the same code in both. Rendered raw, a reader is
 * shown `insufficient_evidence` — sometimes twice — where an explanation of why
 * the platform refused belongs.
 */
const REASON_COPY: Readonly<Record<string, string>> = {
  insufficient_evidence: "Nothing in this workspace's documents was close enough to the question.",
  unauthorized: "You do not have access to the documents that would answer this.",
  abstain: "The evidence was too weak to support any statement, so none was made.",
  ask_for_clarification: "There is related material, but nothing that answers this exact question.",
  escalate_for_review: "The documents disagree with each other, so this needs a human reviewer.",
};

/**
 * A reason in words, or `null` when there is nothing to say.
 *
 * An unrecognized value is passed through: the prose reasons the decision policy
 * writes are meant to be read, and swallowing an unknown code would hide why an
 * answer was withheld — worse than showing an unfamiliar phrase.
 */
export function explainReason(reason: string | null): string | null {
  if (reason === null || reason.trim() === "") {
    return null;
  }
  return REASON_COPY[reason] ?? reason;
}

export function describeAnswer(
  decision: AnswerDecision | null,
  status: AnswerStatus | null,
): DecisionCopy {
  if (decision !== null) {
    return DECISION_COPY[decision];
  }
  return status === null ? DECISION_COPY.abstain : STATUS_FALLBACK[status];
}

export function describeVerdict(verdict: ClaimVerdict): Readonly<{
  label: string;
  tone: AnswerTone;
}> {
  return VERDICT_COPY[verdict];
}

/**
 * Confidence as a coarse band, plus the exact figure for anyone who wants it.
 *
 * A bare percentage invites false precision — it is a calibrated estimate, not a
 * probability of correctness — so the band leads and the number follows.
 */
export function describeConfidence(
  confidence: number,
): Readonly<{ band: string; percent: string }> {
  const percent = `${Math.round(confidence * 100)}%`;
  if (confidence >= 0.75) {
    return { band: "High", percent };
  }
  if (confidence >= 0.5) {
    return { band: "Moderate", percent };
  }
  return { band: "Low", percent };
}

export function AnswerBadge({
  decision,
  status,
}: Readonly<{ decision: AnswerDecision | null; status: AnswerStatus | null }>) {
  const copy = describeAnswer(decision, status);
  return (
    <p className="answer-badge" data-tone={copy.tone}>
      {copy.label}
    </p>
  );
}

export function VerdictBadge({ verdict }: Readonly<{ verdict: ClaimVerdict }>) {
  const copy = describeVerdict(verdict);
  return (
    <span className="verdict-badge" data-tone={copy.tone}>
      {copy.label}
    </span>
  );
}

export function ConfidenceMeter({ confidence }: Readonly<{ confidence: number }>) {
  const copy = describeConfidence(confidence);
  return (
    <p className="confidence-meter" data-band={copy.band.toLowerCase()}>
      <span className="confidence-label">Confidence</span>
      <span className="confidence-value">
        {copy.band} ({copy.percent})
      </span>
    </p>
  );
}
