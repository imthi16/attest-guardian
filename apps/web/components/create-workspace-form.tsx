/**
 * Workspace creation form. The creator becomes the owner, which the API
 * enforces; the slug is derived server side so it stays URL-safe.
 */
"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Feedback } from "./feedback";
import { Field } from "./field";
import type { FormState } from "../app/form-state";

const idleState: FormState = { status: "idle" };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button aria-busy={pending} className="primary-button" disabled={pending} type="submit">
      {pending ? "Creating workspace" : "Create workspace"}
    </button>
  );
}

type CreateWorkspaceFormProps = Readonly<{
  action: (state: FormState, formData: FormData) => Promise<FormState>;
}>;

export function CreateWorkspaceForm({ action }: CreateWorkspaceFormProps) {
  const [state, formAction] = useActionState(action, idleState);
  const fieldErrors = state.fieldErrors ?? {};

  return (
    <form action={formAction} className="create-workspace-form" noValidate>
      <p className="form-copy">You become its owner and can add members afterwards.</p>
      {state.status === "error" && state.message !== undefined ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}
      <Field error={fieldErrors.name} label="Workspace name" name="name" />
      <SubmitButton />
    </form>
  );
}
