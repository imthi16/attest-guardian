"use client";

/**
 * Permanently delete a thread.
 *
 * Confirms first, because the answers, claim verdicts, and citation records go
 * with it. The API additionally refuses unless the caller started the thread or
 * holds `manageConversations`, so a member cannot destroy a colleague's history
 * even though this control is rendered for them — the confirmation is a courtesy,
 * the authorization is the API's.
 *
 * The cited documents are untouched, and the copy says so: "delete" next to
 * evidence-backed answers is alarming enough that the scope should be explicit.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Feedback } from "./feedback";
import { deleteConversationAction } from "../app/conversation-actions";
import { idleState } from "../app/form-state";

function ConfirmButton() {
  const { pending } = useFormStatus();
  return (
    <button
      className="danger-button"
      disabled={pending}
      onClick={(event) => {
        if (
          !window.confirm(
            "Delete this thread? Its questions, answers, and citation records are removed permanently. The documents they cited are not affected.",
          )
        ) {
          event.preventDefault();
        }
      }}
      type="submit"
    >
      {pending ? "Deleting…" : "Delete this thread"}
    </button>
  );
}

export function DeleteConversationForm({
  conversationId,
  workspaceId,
}: Readonly<{ conversationId: string; workspaceId: string }>) {
  const [state, action] = useActionState(deleteConversationAction, idleState);

  return (
    <form action={action} className="delete-thread-form">
      <input name="conversationId" type="hidden" value={conversationId} />
      <input name="workspaceId" type="hidden" value={workspaceId} />
      <ConfirmButton />
      {state.status === "error" ? (
        <Feedback
          code={state.code}
          message={state.message ?? "The thread could not be deleted."}
          tone="error"
        />
      ) : null}
    </form>
  );
}
