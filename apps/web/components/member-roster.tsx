/**
 * Member roster with role changes, removal, and invitations.
 *
 * Controls are rendered only for members the caller's role may manage, which
 * mirrors the API's asymmetric matrix (admins run the day-to-day roster but
 * cannot touch owners). Every mutation still round-trips to the API, so a
 * mirrored rule that drifts fails safely with a stable code rather than
 * granting anything. Removal requires confirmation because it revokes access
 * to every document in the workspace.
 */
"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { changeMemberRoleAction, removeMemberAction } from "../app/workspace-actions";
import { canManageRole, grantableRoles, ROLE_LABELS } from "../lib/permissions";
import { Feedback } from "./feedback";
import type { FormState } from "../app/form-state";
import type { Member, MembershipRole } from "../lib/contracts";

const idleState: FormState = { status: "idle" };

function PendingButton({
  className,
  confirmMessage,
  label,
  pendingLabel,
}: Readonly<{
  className: string;
  confirmMessage?: string;
  label: string;
  pendingLabel: string;
}>) {
  const { pending } = useFormStatus();
  return (
    <button
      aria-busy={pending}
      className={className}
      disabled={pending}
      onClick={
        confirmMessage === undefined
          ? undefined
          : (event) => {
              if (!window.confirm(confirmMessage)) {
                event.preventDefault();
              }
            }
      }
      type="submit"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}

type MemberRowProps = Readonly<{
  actorRole: MembershipRole;
  isSelf: boolean;
  member: Member;
  workspaceId: string;
}>;

function MemberRow({ actorRole, isSelf, member, workspaceId }: MemberRowProps) {
  const [roleState, roleAction] = useActionState(changeMemberRoleAction, idleState);
  const [removeState, removeAction] = useActionState(removeMemberAction, idleState);
  const manageable = canManageRole(actorRole, member.role);
  const roleOptions = grantableRoles(actorRole);
  const selectId = `role-${member.user_id}`;

  return (
    <tr>
      <td data-label="Member">
        <span className="member-name">{member.full_name}</span>
        <span className="member-email">{member.email}</span>
      </td>
      <td data-label="Role">
        {manageable && roleOptions.length > 0 ? (
          <form action={roleAction} className="inline-form">
            <input name="workspaceId" type="hidden" value={workspaceId} />
            <input name="userId" type="hidden" value={member.user_id} />
            <label className="visually-hidden" htmlFor={selectId}>
              Role for {member.full_name}
            </label>
            <select defaultValue={member.role} id={selectId} name="role">
              {roleOptions.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </select>
            <PendingButton className="secondary-button" label="Update" pendingLabel="Updating" />
          </form>
        ) : (
          <span className="role-badge" data-role={member.role}>
            {ROLE_LABELS[member.role]}
          </span>
        )}
        {roleState.status === "error" && roleState.message !== undefined ? (
          <Feedback code={roleState.code} message={roleState.message} tone="error" />
        ) : null}
        {roleState.status === "success" && roleState.message !== undefined ? (
          <Feedback message={roleState.message} tone="success" />
        ) : null}
      </td>
      <td data-label="Actions">
        {manageable && !isSelf ? (
          <form action={removeAction} className="inline-form">
            <input name="workspaceId" type="hidden" value={workspaceId} />
            <input name="userId" type="hidden" value={member.user_id} />
            <PendingButton
              className="danger-button"
              confirmMessage={`Remove ${member.full_name} from this workspace? They lose access to every document in it.`}
              label="Remove"
              pendingLabel="Removing"
            />
          </form>
        ) : (
          <span className="muted-note">{isSelf ? "This is you" : "Not manageable"}</span>
        )}
        {removeState.status === "error" && removeState.message !== undefined ? (
          <Feedback code={removeState.code} message={removeState.message} tone="error" />
        ) : null}
      </td>
    </tr>
  );
}

type MemberRosterProps = Readonly<{
  actorRole: MembershipRole;
  currentUserId: string;
  members: readonly Member[];
  workspaceId: string;
}>;

export function MemberRoster({
  actorRole,
  currentUserId,
  members,
  workspaceId,
}: MemberRosterProps) {
  return (
    <table className="member-table">
      <caption className="visually-hidden">
        Workspace members, their roles, and available actions
      </caption>
      <thead>
        <tr>
          <th scope="col">Member</th>
          <th scope="col">Role</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        {members.map((member) => (
          <MemberRow
            actorRole={actorRole}
            isSelf={member.user_id === currentUserId}
            key={member.user_id}
            member={member}
            workspaceId={workspaceId}
          />
        ))}
      </tbody>
    </table>
  );
}
