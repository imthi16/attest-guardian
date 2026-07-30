"use client";

/**
 * Reviewer verdict on one answer.
 *
 * Three ratings, because "unhelpful" and "incorrect" are different findings: an
 * unhelpful answer may be correctly refusing to answer, while an incorrect one
 * is a grounding failure worth investigating. Collapsing them would lose exactly
 * the signal that matters for evaluation.
 *
 * Submitting again revises this reviewer's verdict rather than adding another —
 * the API keys feedback by (message, reviewer) — so the control stays usable
 * after a first click instead of locking.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Feedback } from "./feedback";
import { submitFeedbackAction } from "../app/conversation-actions";
import { idleState } from "../app/form-state";
import type { FeedbackRating } from "../lib/contracts";

type AnswerFeedbackProps = Readonly<{
  conversationId: string;
  messageId: string;
  workspaceId: string;
}>;

const RATINGS: readonly Readonly<{ label: string; value: FeedbackRating }>[] = [
  { label: "Helpful", value: "helpful" },
  { label: "Not helpful", value: "unhelpful" },
  { label: "Incorrect", value: "incorrect" },
];

function SubmitButtons() {
  const { pending } = useFormStatus();
  return (
    <span className="feedback-buttons">
      {RATINGS.map((rating) => (
        <button
          className="secondary-button"
          disabled={pending}
          key={rating.value}
          name="rating"
          type="submit"
          value={rating.value}
        >
          {rating.label}
        </button>
      ))}
    </span>
  );
}

export function AnswerFeedback({ conversationId, messageId, workspaceId }: AnswerFeedbackProps) {
  const [state, action] = useActionState(submitFeedbackAction, idleState);
  const noteId = `feedback-note-${messageId}`;

  return (
    <form action={action} className="answer-feedback">
      <input name="conversationId" type="hidden" value={conversationId} />
      <input name="messageId" type="hidden" value={messageId} />
      <input name="workspaceId" type="hidden" value={workspaceId} />

      <fieldset className="feedback-fieldset">
        <legend className="feedback-legend">Was this answer right?</legend>
        <label className="field-label" htmlFor={noteId}>
          What was wrong or missing? (optional)
        </label>
        <textarea className="feedback-note" id={noteId} maxLength={2000} name="note" rows={2} />
        <SubmitButtons />
      </fieldset>

      {state.status === "idle" ? null : (
        <Feedback
          code={state.status === "error" ? state.code : undefined}
          message={state.message ?? "Your review was recorded."}
          tone={state.status === "error" ? "error" : "success"}
        />
      )}
    </form>
  );
}
