import Link from "next/link";
import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../../../components/access-notice";
import { ConversationThread } from "../../../../../../components/conversation-thread";
import { DeleteConversationForm } from "../../../../../../components/delete-conversation-form";
import { QuestionComposer } from "../../../../../../components/question-composer";
import { SystemState } from "../../../../../../components/system-state";
import { WorkspaceNav } from "../../../../../../components/workspace-nav";
import { errorCodes } from "../../../../../../lib/contracts";
import {
  fetchConversation,
  fetchCurrentUser,
  fetchWorkspace,
} from "../../../../../../lib/attest-api";
import { allows } from "../../../../../../lib/permissions";
import { SESSION_EXPIRED } from "../../../../../../lib/session";

export const dynamic = "force-dynamic";

type ConversationPageProps = Readonly<{
  params: Promise<Readonly<{ conversationId: string; workspaceId: string }>>;
}>;

/**
 * One thread: its turns, the evidence behind each answer, and a composer.
 *
 * The thread is server-rendered from the stored record, so what a reader sees is
 * what was persisted — including the decision and confidence, which are the
 * answer's verdict and not recoverable from the text.
 */
export default async function ConversationPage({ params }: ConversationPageProps) {
  const { conversationId, workspaceId } = await params;

  const [user, workspace, detail] = await Promise.all([
    fetchCurrentUser(),
    fetchWorkspace(workspaceId),
    fetchConversation(workspaceId, conversationId),
  ]);

  for (const result of [user, workspace, detail]) {
    if (!result.ok && result.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}/conversations/${conversationId}`);
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
  const base = `/workspaces/${workspace.data.id}/conversations`;

  return (
    <>
      <WorkspaceNav
        role={role}
        userEmail={user.ok ? user.data.email : "Signed in"}
        workspaceId={workspace.data.id}
        workspaceName={workspace.data.name}
      />
      <main className="workspace-main" id="main-content">
        {detail.ok ? (
          <>
            <section aria-labelledby="thread-title" className="workspace-intro">
              <p className="eyebrow">
                <Link href={base}>All threads</Link>
              </p>
              <h1 id="thread-title">{detail.data.conversation.title ?? "Untitled thread"}</h1>
            </section>

            {detail.data.messages.length === 0 ? (
              <SystemState
                description="Ask the first question to start this thread."
                state="empty"
                title="Nothing asked yet"
              />
            ) : (
              <ConversationThread
                canReview={canConverse}
                conversationId={detail.data.conversation.id}
                messages={detail.data.messages}
                workspaceId={workspace.data.id}
              />
            )}

            {canConverse ? (
              <QuestionComposer
                conversationId={detail.data.conversation.id}
                workspaceId={workspace.data.id}
              />
            ) : (
              <AccessNotice
                code={errorCodes.insufficientRole}
                message="You can read this thread, but only members, admins, and owners can ask questions or review answers."
              />
            )}

            {canConverse ? (
              <DeleteConversationForm
                conversationId={detail.data.conversation.id}
                workspaceId={workspace.data.id}
              />
            ) : null}
          </>
        ) : (
          <AccessNotice code={detail.code} message={detail.message} />
        )}
      </main>
    </>
  );
}
