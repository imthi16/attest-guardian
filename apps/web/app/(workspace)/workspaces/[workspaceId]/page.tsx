import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../components/access-notice";
import { SystemState } from "../../../../components/system-state";
import { WorkspaceNav } from "../../../../components/workspace-nav";
import { fetchCurrentUser, fetchWorkspace } from "../../../../lib/attest-api";
import { allows, ROLE_DESCRIPTIONS, ROLE_LABELS } from "../../../../lib/permissions";
import { SESSION_EXPIRED } from "../../../../lib/session";

export const dynamic = "force-dynamic";

type WorkspacePageProps = Readonly<{
  params: Promise<Readonly<{ workspaceId: string }>>;
}>;

/**
 * Workspace overview. Membership and role are resolved by the API, so a
 * non-member sees the same "not found" notice as for a missing workspace.
 */
export default async function WorkspaceOverviewPage({ params }: WorkspacePageProps) {
  const { workspaceId } = await params;
  const [user, workspace] = await Promise.all([fetchCurrentUser(), fetchWorkspace(workspaceId)]);

  if (!workspace.ok) {
    if (workspace.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}`);
    }
    return (
      <main className="workspace-main" id="main-content">
        <AccessNotice code={workspace.code} message={workspace.message} />
      </main>
    );
  }

  const role = workspace.data.role;
  return (
    <>
      <WorkspaceNav
        role={role}
        userEmail={user.ok ? user.data.email : "Signed in"}
        workspaceId={workspace.data.id}
        workspaceName={workspace.data.name}
      />
      <main className="workspace-main" id="main-content">
        <section aria-labelledby="workspace-title" className="workspace-intro">
          <p className="eyebrow">{workspace.data.slug}</p>
          <h1 id="workspace-title">{workspace.data.name}</h1>
          <p className="auth-copy">
            You are a <strong>{ROLE_LABELS[role]}</strong> here. {ROLE_DESCRIPTIONS[role]}
          </p>
          <p className="tamil-sample" lang="ta">
            ஆதாரத்துடன் பதில். ஆதாரம் இல்லையெனில் மறுப்பு.
          </p>
        </section>

        <section aria-labelledby="capability-title" className="workspace-capabilities">
          <h2 id="capability-title">What you can do here</h2>
          <ul className="capability-checklist">
            <li data-allowed={allows(role, "query")}>Ask evidence-grounded questions</li>
            <li data-allowed={allows(role, "uploadDocuments")}>Upload documents for ingestion</li>
            <li data-allowed={allows(role, "manageMembers")}>Manage workspace members</li>
          </ul>
        </section>

        <section aria-labelledby="next-title" className="workspace-next">
          <h2 id="next-title">Coming next</h2>
          <SystemState
            description="Document management and the evidence chat arrive in the following milestones. Until then, this workspace only manages access."
            state="empty"
            title="No documents yet"
          />
        </section>
      </main>
    </>
  );
}
