import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../../components/access-notice";
import { AddMemberForm } from "../../../../../components/add-member-form";
import { MemberRoster } from "../../../../../components/member-roster";
import { SystemState } from "../../../../../components/system-state";
import { WorkspaceNav } from "../../../../../components/workspace-nav";
import { fetchCurrentUser, fetchMembers, fetchWorkspace } from "../../../../../lib/attest-api";
import { allows } from "../../../../../lib/permissions";
import { errorCodes } from "../../../../../lib/contracts";
import { SESSION_EXPIRED } from "../../../../../lib/session";

export const dynamic = "force-dynamic";

type MembersPageProps = Readonly<{
  params: Promise<Readonly<{ workspaceId: string }>>;
}>;

/**
 * Member management. Viewers and members can see the roster but get an
 * explicit access notice instead of controls, matching the API's matrix; the
 * API still refuses any mutation they attempt directly.
 */
export default async function MembersPage({ params }: MembersPageProps) {
  const { workspaceId } = await params;
  const [user, workspace, members] = await Promise.all([
    fetchCurrentUser(),
    fetchWorkspace(workspaceId),
    fetchMembers(workspaceId),
  ]);

  for (const result of [user, workspace, members]) {
    if (!result.ok && result.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}/members`);
    }
  }

  if (!workspace.ok) {
    return (
      <main className="workspace-main" id="main-content">
        <AccessNotice code={workspace.code} message={workspace.message} />
      </main>
    );
  }

  const role = workspace.data.role;
  const canManage = allows(role, "manageMembers");

  return (
    <>
      <WorkspaceNav
        role={role}
        userEmail={user.ok ? user.data.email : "Signed in"}
        workspaceId={workspace.data.id}
        workspaceName={workspace.data.name}
      />
      <main className="workspace-main" id="main-content">
        <section aria-labelledby="members-title" className="workspace-intro">
          <p className="eyebrow">MEMBERS</p>
          <h1 id="members-title">{workspace.data.name} members</h1>
          <p className="auth-copy">
            Membership decides which documents may ever be used as evidence. Roles are enforced by
            the API on every request, not by this page.
          </p>
        </section>

        {canManage ? null : (
          <AccessNotice
            code={errorCodes.insufficientRole}
            message="You can see who is in this workspace, but only owners and admins can change membership."
          />
        )}

        <section aria-labelledby="roster-title" className="workspace-roster">
          <h2 id="roster-title">Current members</h2>
          {members.ok ? (
            members.data.length === 0 ? (
              <SystemState
                description="No members were returned for this workspace."
                state="empty"
                title="No members to show"
              />
            ) : (
              <MemberRoster
                actorRole={role}
                currentUserId={user.ok ? user.data.id : ""}
                members={members.data}
                workspaceId={workspace.data.id}
              />
            )
          ) : (
            <SystemState
              description={members.message}
              state="error"
              title="The member list could not be loaded"
            />
          )}
        </section>

        {canManage ? (
          <section aria-labelledby="invite-title" className="workspace-invite">
            <h2 id="invite-title">Invite</h2>
            <AddMemberForm actorRole={role} workspaceId={workspace.data.id} />
          </section>
        ) : null}
      </main>
    </>
  );
}
