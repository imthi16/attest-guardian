import { redirect } from "next/navigation";

import { createWorkspaceAction } from "../../workspace-actions";
import { AccessNotice } from "../../../components/access-notice";
import { CreateWorkspaceForm } from "../../../components/create-workspace-form";
import { WorkspaceList } from "../../../components/workspace-list";
import { fetchCurrentUser, fetchWorkspaces } from "../../../lib/attest-api";
import { readActiveWorkspaceId, SESSION_EXPIRED } from "../../../lib/session";

export const metadata = { title: "Workspaces — Attest Guardian" };
export const dynamic = "force-dynamic";

/**
 * Workspace selection. The list comes from the API scoped to the caller's
 * memberships, so a workspace the visitor cannot access is never listed.
 */
export default async function WorkspacesPage() {
  const [user, workspaces] = await Promise.all([fetchCurrentUser(), fetchWorkspaces()]);
  if (!user.ok && user.code === SESSION_EXPIRED) {
    redirect("/login?expired=1&next=/workspaces");
  }
  if (!workspaces.ok) {
    if (workspaces.code === SESSION_EXPIRED) {
      redirect("/login?expired=1&next=/workspaces");
    }
    return (
      <main className="workspace-main" id="main-content">
        <AccessNotice code={workspaces.code} message={workspaces.message} />
      </main>
    );
  }

  const activeWorkspaceId = await readActiveWorkspaceId();

  return (
    <main className="workspace-main" id="main-content">
      <section aria-labelledby="workspaces-title" className="workspace-intro">
        <p className="eyebrow">WORKSPACES</p>
        <h1 id="workspaces-title">Choose a workspace</h1>
        <p className="auth-copy">
          Every question is answered only from documents in the workspace you select, and only if
          your role permits it.
        </p>
        {user.ok ? <p className="signed-in-as">Signed in as {user.data.email}</p> : null}
      </section>

      <section aria-labelledby="workspace-choices-title" className="workspace-choices">
        <h2 id="workspace-choices-title">Your memberships</h2>
        <WorkspaceList activeWorkspaceId={activeWorkspaceId} workspaces={workspaces.data} />
      </section>

      <section aria-labelledby="create-workspace-title" className="workspace-create">
        <h2 id="create-workspace-title">Create a workspace</h2>
        <CreateWorkspaceForm action={createWorkspaceAction} />
      </section>
    </main>
  );
}
