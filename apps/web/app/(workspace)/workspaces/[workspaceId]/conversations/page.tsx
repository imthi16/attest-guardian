import Link from "next/link";
import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../../components/access-notice";
import { Feedback } from "../../../../../components/feedback";
import { StartConversationForm } from "../../../../../components/start-conversation-form";
import { SystemState } from "../../../../../components/system-state";
import { WorkspaceNav } from "../../../../../components/workspace-nav";
import { errorCodes } from "../../../../../lib/contracts";
import {
  fetchConversations,
  fetchCurrentUser,
  fetchWorkspace,
} from "../../../../../lib/attest-api";
import { allows } from "../../../../../lib/permissions";
import { SESSION_EXPIRED } from "../../../../../lib/session";

export const dynamic = "force-dynamic";

type ConversationsPageProps = Readonly<{
  params: Promise<Readonly<{ workspaceId: string }>>;
  searchParams: Promise<Readonly<{ deleted?: string }>>;
}>;

/**
 * The workspace's question threads.
 *
 * Reading a thread needs only `view`, because the answers are drawn from
 * documents the reader may already see. Starting one is a change to workspace
 * state and needs `converse`, so a viewer gets an explanation instead of a
 * composer — the API enforces this regardless of what is rendered.
 */
export default async function ConversationsPage({ params, searchParams }: ConversationsPageProps) {
  const { workspaceId } = await params;
  const { deleted } = await searchParams;

  const [user, workspace, conversations] = await Promise.all([
    fetchCurrentUser(),
    fetchWorkspace(workspaceId),
    fetchConversations(workspaceId),
  ]);

  for (const result of [user, workspace, conversations]) {
    if (!result.ok && result.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}/conversations`);
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
  const canConverse = allows(role, "converse");

  return (
    <>
      <WorkspaceNav
        role={role}
        userEmail={user.ok ? user.data.email : "Signed in"}
        workspaceId={workspace.data.id}
        workspaceName={workspace.data.name}
      />
      <main className="workspace-main" id="main-content">
        <section aria-labelledby="conversations-title" className="workspace-intro">
          <p className="eyebrow">ASK</p>
          <h1 id="conversations-title">Questions about {workspace.data.name}</h1>
          <p className="auth-copy">
            Every answer is drawn only from this workspace&apos;s documents and carries a citation
            you can open. When the evidence is not enough, the platform says so instead of guessing.
          </p>
        </section>

        {deleted === "1" ? (
          <Feedback
            message="The thread, its answers, and its citation records were deleted. The documents they cited were not touched."
            tone="notice"
          />
        ) : null}

        {canConverse ? null : (
          <AccessNotice
            code={errorCodes.insufficientRole}
            message="You can read the questions asked here, but only members, admins, and owners can ask new ones."
          />
        )}

        {canConverse ? <StartConversationForm workspaceId={workspace.data.id} /> : null}

        <section aria-labelledby="threads-title" className="workspace-threads">
          <h2 id="threads-title">Threads</h2>
          {conversations.ok ? (
            conversations.data.length === 0 ? (
              <SystemState
                description="No one has asked anything in this workspace yet."
                state="empty"
                title="No conversations yet"
              />
            ) : (
              <ul className="thread-list">
                {conversations.data.map((conversation) => (
                  <li className="thread-summary" key={conversation.id}>
                    <Link
                      href={`/workspaces/${workspace.data.id}/conversations/${conversation.id}`}
                    >
                      {/* Titles are caller-supplied text, rendered as a text child. */}
                      {conversation.title ?? "Untitled thread"}
                    </Link>
                    <time className="thread-time" dateTime={conversation.updated_at}>
                      {new Date(conversation.updated_at).toLocaleString()}
                    </time>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <SystemState
              description={conversations.message}
              state="error"
              title="The threads could not be loaded"
            />
          )}
        </section>
      </main>
    </>
  );
}
