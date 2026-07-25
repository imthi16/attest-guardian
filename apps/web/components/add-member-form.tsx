/**
 * Invitation form for adding an existing account to the workspace.
 *
 * The role choices are limited to what the caller may grant, matching the
 * API's rule that admins cannot mint privileged roles. The API remains the
 * enforcement point and returns a stable code when the rule is violated.
 */
"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { addMemberAction } from "../app/workspace-actions";
import { grantableRoles, ROLE_DESCRIPTIONS, ROLE_LABELS } from "../lib/permissions";
import { Feedback } from "./feedback";
import { Field } from "./field";
import type { FormState } from "../app/form-state";
import type { MembershipRole } from "../lib/contracts";

const idleState: FormState = { status: "idle" };

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button aria-busy={pending} className="primary-button" disabled={pending} type="submit">
      {pending ? "Adding member" : "Add member"}
    </button>
  );
}

type AddMemberFormProps = Readonly<{
  actorRole: MembershipRole;
  workspaceId: string;
}>;

export function AddMemberForm({ actorRole, workspaceId }: AddMemberFormProps) {
  const [state, formAction] = useActionState(addMemberAction, idleState);
  const roleOptions = grantableRoles(actorRole);
  const fieldErrors = state.fieldErrors ?? {};

  return (
    <form action={formAction} className="add-member-form" noValidate>
      <h3>Add a member</h3>
      <p className="form-copy">
        The person must already have an Attest Guardian account. Membership decides which documents
        can be used as evidence for their questions.
      </p>

      {state.status === "error" && state.message !== undefined ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}
      {state.status === "success" && state.message !== undefined ? (
        <Feedback message={state.message} tone="success" />
      ) : null}

      <input name="workspaceId" type="hidden" value={workspaceId} />

      <Field
        autoComplete="email"
        error={fieldErrors.email}
        label="Member email address"
        name="email"
        type="email"
      />

      <p className="field">
        <label htmlFor="role">Role</label>
        <select defaultValue={roleOptions.at(-1)} id="role" name="role">
          {roleOptions.map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]} — {ROLE_DESCRIPTIONS[role]}
            </option>
          ))}
        </select>
      </p>

      <SubmitButton />
    </form>
  );
}
