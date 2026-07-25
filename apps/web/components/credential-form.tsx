/**
 * Credential forms for signup and login.
 *
 * Both submit to a server action, so credentials never pass through client
 * state and the resulting session lands in an httpOnly cookie. The submit
 * button reports pending status through `aria-busy` and disables itself, which
 * makes the loading state explicit and prevents double submission.
 */
"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Feedback } from "./feedback";
import { Field } from "./field";
import type { FormState } from "../app/form-state";

const idleState: FormState = { status: "idle" };

function SubmitButton({ label, pendingLabel }: Readonly<{ label: string; pendingLabel: string }>) {
  const { pending } = useFormStatus();
  return (
    <button aria-busy={pending} className="primary-button" disabled={pending} type="submit">
      {pending ? pendingLabel : label}
    </button>
  );
}

type CredentialFormProps = Readonly<{
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  mode: "login" | "register";
  nextPath?: string;
}>;

export function CredentialForm({ action, mode, nextPath }: CredentialFormProps) {
  const [state, formAction] = useActionState(action, idleState);
  const isRegister = mode === "register";
  const fieldErrors = state.fieldErrors ?? {};

  return (
    <form action={formAction} className="credential-form" noValidate>
      {state.status === "error" && state.message !== undefined ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}

      {isRegister ? (
        <Field autoComplete="name" error={fieldErrors.fullName} label="Full name" name="fullName" />
      ) : null}

      <Field
        autoComplete="email"
        error={fieldErrors.email}
        label="Email address"
        name="email"
        type="email"
      />

      <Field
        autoComplete={isRegister ? "new-password" : "current-password"}
        error={fieldErrors.password}
        hint={isRegister ? "At least 8 characters." : undefined}
        label="Password"
        name="password"
        type="password"
      />

      {nextPath === undefined ? null : <input name="next" type="hidden" value={nextPath} />}

      <SubmitButton
        label={isRegister ? "Create account" : "Sign in"}
        pendingLabel={isRegister ? "Creating account" : "Signing in"}
      />
    </form>
  );
}
