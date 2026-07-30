import { render, screen } from "@testing-library/react";

import {
  AnswerBadge,
  ConfidenceMeter,
  VerdictBadge,
  describeAnswer,
  describeConfidence,
  describeVerdict,
} from "./answer-state";
import { answerDecisionSchema, claimVerdictSchema } from "../lib/contracts";

describe("describeAnswer", () => {
  it("has distinct wording for every decision the API can return", () => {
    const labels = answerDecisionSchema.options.map(
      (decision) => describeAnswer(decision, null).label,
    );
    // Distinct because the whole point is telling three abstentions apart.
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("distinguishes the three abstaining decisions", () => {
    // All three report `answer_status: "abstained"`; only the decision says
    // whether there is nothing here, the question was too broad, or a human
    // should look at it.
    const noEvidence = describeAnswer("abstain", "abstained");
    const tooBroad = describeAnswer("ask_for_clarification", "abstained");
    const conflict = describeAnswer("escalate_for_review", "abstained");

    expect(noEvidence.label).not.toBe(tooBroad.label);
    expect(tooBroad.label).not.toBe(conflict.label);
    expect(tooBroad.explanation).toMatch(/narrow|naming/i);
    expect(conflict.explanation).toMatch(/review|conflict/i);
  });

  it("never presents a refusal as an answer", () => {
    expect(describeAnswer("abstain", "abstained").tone).toBe("refused");
    expect(describeAnswer("answer_with_warning", "answered").tone).toBe("caution");
    expect(describeAnswer("answer", "answered").tone).toBe("answered");
  });

  it("falls back to the status when a stored turn has no decision", () => {
    // Turns written before decisions were persisted carry only a status.
    expect(describeAnswer(null, "answered").tone).toBe("answered");
    expect(describeAnswer(null, "partial").tone).toBe("caution");
    expect(describeAnswer(null, "abstained").tone).toBe("refused");
  });

  it("treats a turn with neither as giving no answer", () => {
    expect(describeAnswer(null, null).tone).toBe("refused");
  });
});

describe("describeVerdict", () => {
  it("has wording for every verdict the API can return", () => {
    for (const verdict of claimVerdictSchema.options) {
      expect(describeVerdict(verdict).label.length).toBeGreaterThan(0);
    }
  });

  it("marks an unsupported claim as refused and a contradiction for review", () => {
    expect(describeVerdict("unsupported").tone).toBe("refused");
    expect(describeVerdict("contradicted").tone).toBe("review");
  });
});

describe("describeConfidence", () => {
  it("bands the figure rather than implying precision", () => {
    expect(describeConfidence(0.9).band).toBe("High");
    expect(describeConfidence(0.6).band).toBe("Moderate");
    expect(describeConfidence(0.2).band).toBe("Low");
  });

  it("still reports the exact percentage", () => {
    expect(describeConfidence(0.873).percent).toBe("87%");
    expect(describeConfidence(0).percent).toBe("0%");
    expect(describeConfidence(1).percent).toBe("100%");
  });
});

describe("badges", () => {
  it("renders the decision, verdict, and confidence for a reader", () => {
    render(
      <>
        <AnswerBadge decision="answer_with_warning" status="answered" />
        <VerdictBadge verdict="contradicted" />
        <ConfidenceMeter confidence={0.42} />
      </>,
    );

    expect(screen.getByText("Answered with caution")).toBeInTheDocument();
    expect(screen.getByText("Contradicted")).toBeInTheDocument();
    expect(screen.getByText("Low (42%)")).toBeInTheDocument();
  });
});
