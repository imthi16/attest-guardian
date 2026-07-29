/**
 * Role-aware workspace navigation.
 *
 * Links are shown only for capabilities the caller's role actually holds, so
 * the UI never advertises an action the API will refuse. This is presentation
 * only; the API re-authorizes every request regardless of what is rendered.
 */
import Link from "next/link";

import { logoutAction } from "../app/auth-actions";
import { allows, ROLE_LABELS } from "../lib/permissions";
import type { MembershipRole } from "../lib/contracts";

type WorkspaceNavProps = Readonly<{
  role: MembershipRole;
  userEmail: string;
  workspaceId: string;
  workspaceName: string;
}>;

export function WorkspaceNav({ role, userEmail, workspaceId, workspaceName }: WorkspaceNavProps) {
  const base = `/workspaces/${workspaceId}`;
  return (
    <header className="workspace-header">
      <div className="workspace-identity">
        <Link className="workspace-home" href="/workspaces">
          Attest Guardian
        </Link>
        <p className="workspace-name">{workspaceName}</p>
        <p className="role-badge" data-role={role}>
          {ROLE_LABELS[role]}
        </p>
      </div>

      <nav aria-label="Workspace" className="workspace-nav">
        <ul>
          <li>
            <Link href={base}>Overview</Link>
          </li>
          <li>
            <Link href={`${base}/documents`}>Documents</Link>
          </li>
          {allows(role, "manageMembers") ? (
            <li>
              <Link href={`${base}/members`}>Members</Link>
            </li>
          ) : null}
          <li>
            <Link href="/workspaces">Switch workspace</Link>
          </li>
        </ul>
      </nav>

      <form action={logoutAction} className="logout-form">
        <p className="signed-in-as">{userEmail}</p>
        <button className="secondary-button" type="submit">
          Sign out
        </button>
      </form>
    </header>
  );
}
