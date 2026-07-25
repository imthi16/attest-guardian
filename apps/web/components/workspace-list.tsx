/**
 * Workspace picker with explicit empty and populated states.
 *
 * Selection is submitted to a server action that records the choice in a
 * server-side cookie, so the active workspace survives navigation without the
 * browser holding tenant state that could be tampered with.
 */
import { selectWorkspaceAction } from "../app/workspace-actions";
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from "../lib/permissions";
import { SystemState } from "./system-state";
import type { WorkspaceWithRole } from "../lib/contracts";

type WorkspaceListProps = Readonly<{
  activeWorkspaceId: string | null;
  workspaces: readonly WorkspaceWithRole[];
}>;

export function WorkspaceList({ activeWorkspaceId, workspaces }: WorkspaceListProps) {
  if (workspaces.length === 0) {
    return (
      <SystemState
        description="You are not a member of any workspace yet. Create one, or ask an owner to add you."
        state="empty"
        title="No workspaces available"
      />
    );
  }

  return (
    <ul className="workspace-list">
      {workspaces.map((workspace) => (
        <li key={workspace.id}>
          <form action={selectWorkspaceAction} className="workspace-card">
            <input name="workspaceId" type="hidden" value={workspace.id} />
            <div>
              <h3>{workspace.name}</h3>
              <p className="workspace-slug">{workspace.slug}</p>
              <p className="role-badge" data-role={workspace.role}>
                {ROLE_LABELS[workspace.role]}
              </p>
              <p className="workspace-role-copy">{ROLE_DESCRIPTIONS[workspace.role]}</p>
            </div>
            <button className="primary-button" type="submit">
              <span className="visually-hidden">
                {workspace.id === activeWorkspaceId ? "Continue in " : "Open "}
                {workspace.name}
              </span>
              <span aria-hidden="true">
                {workspace.id === activeWorkspaceId ? "Continue" : "Open"}
              </span>
            </button>
          </form>
        </li>
      ))}
    </ul>
  );
}
