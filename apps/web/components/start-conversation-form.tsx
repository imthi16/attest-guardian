"use client";

/**
 * Start a new thread.
 *
 * The title is optional: making someone name a thread before they know what
 * they are going to ask is friction for no benefit, and an untitled thread is
 * labelled "Untitled thread" in the list until it is renamed.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Feedback } from "./feedback";
import { Field } from "./field";
import { startConversationAction } from "../app/conversation-actions";
import { idleState } from "../app/form-state";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button className="primary-button" disabled={pending} type="submit">
      {pending ? "Starting…" : "Start a thread"}
    </button>
  );
}

export function StartConversationForm({ workspaceId }: Readonly<{ workspaceId: string }>) {
  const [state, action] = useActionState(startConversationAction, idleState);

  return (
    <form action={action} className="start-thread-form">
      <input name="workspaceId" type="hidden" value={workspaceId} />
      <Field
        error={state.fieldErrors?.title}
        hint="Optional — name it after the question you are investigating."
        label="Thread title"
        name="title"
        required={false}
      />
      <SubmitButton />
      {state.status === "error" ? (
        <Feedback
          code={state.code}
          message={state.message ?? "The thread could not be started."}
          tone="error"
        />
      ) : null}
    </form>
  );
}
