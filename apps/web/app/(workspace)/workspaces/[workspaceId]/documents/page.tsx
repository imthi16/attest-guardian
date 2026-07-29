import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../../components/access-notice";
import { DocumentList } from "../../../../../components/document-list";
import { DocumentUpload } from "../../../../../components/document-upload";
import { SystemState } from "../../../../../components/system-state";
import { WorkspaceNav } from "../../../../../components/workspace-nav";
import { Feedback } from "../../../../../components/feedback";
import { errorCodes } from "../../../../../lib/contracts";
import {
  fetchCurrentUser,
  fetchDocuments,
  fetchUploadPolicy,
  fetchWorkspace,
} from "../../../../../lib/attest-api";
import { ACCEPTED_EXTENSIONS, DEFAULT_MAX_UPLOAD_BYTES } from "../../../../../lib/upload-rules";
import { allows } from "../../../../../lib/permissions";
import { SESSION_EXPIRED } from "../../../../../lib/session";

export const dynamic = "force-dynamic";

type DocumentsPageProps = Readonly<{
  params: Promise<Readonly<{ workspaceId: string }>>;
  searchParams: Promise<Readonly<{ archived?: string; deleted?: string }>>;
}>;

/**
 * Document management for one workspace.
 *
 * Archived documents are hidden by default because they are withdrawn from
 * evidence; the caller can ask for them explicitly and act on them from here.
 * Roles come from the API's own answer, and every control still round-trips to
 * it — a viewer sees the library and an explanation instead of upload controls.
 */
export default async function DocumentsPage({ params, searchParams }: DocumentsPageProps) {
  const { workspaceId } = await params;
  const { archived, deleted } = await searchParams;
  const includeArchived = archived === "1";

  const [user, workspace, documents, policy] = await Promise.all([
    fetchCurrentUser(),
    fetchWorkspace(workspaceId),
    fetchDocuments(workspaceId, { includeArchived }),
    fetchUploadPolicy(workspaceId),
  ]);

  for (const result of [user, workspace, documents, policy]) {
    if (!result.ok && result.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}/documents`);
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
  const canUpload = allows(role, "uploadDocuments");
  const canManage = allows(role, "manageDocuments");

  return (
    <>
      <WorkspaceNav
        role={role}
        userEmail={user.ok ? user.data.email : "Signed in"}
        workspaceId={workspace.data.id}
        workspaceName={workspace.data.name}
      />
      <main className="workspace-main" id="main-content">
        <section aria-labelledby="documents-title" className="workspace-intro">
          <p className="eyebrow">DOCUMENTS</p>
          <h1 id="documents-title">{workspace.data.name} documents</h1>
          <p className="auth-copy">
            Only a document that finished processing can be cited. Everything here shows its exact
            state, so an answer is never grounded in a file that failed, was quarantined, or has
            been withdrawn.
          </p>
        </section>

        {deleted === "1" ? (
          <Feedback
            message="The document, its text, and its evidence spans were permanently deleted."
            tone="notice"
          />
        ) : null}

        {canUpload ? null : (
          <AccessNotice
            code={errorCodes.insufficientRole}
            message="You can read this workspace's documents, but only members, admins, and owners can add them."
          />
        )}

        <section aria-labelledby="library-title" className="workspace-documents">
          <div className="section-heading">
            <h2 id="library-title">Library</h2>
            <a
              className="secondary-button"
              href={`/workspaces/${workspace.data.id}/documents${includeArchived ? "" : "?archived=1"}`}
            >
              {includeArchived ? "Hide archived" : "Show archived"}
            </a>
          </div>
          {documents.ok ? (
            documents.data.length === 0 ? (
              <SystemState
                description={
                  includeArchived
                    ? "This workspace has no documents at all yet."
                    : "No active documents. Upload one, or show archived documents if you expected to see something here."
                }
                state="empty"
                title="No documents to show"
              />
            ) : (
              <DocumentList
                capabilities={{ canManage, canUpload }}
                documents={documents.data}
                workspaceId={workspace.data.id}
              />
            )
          ) : (
            <SystemState
              description={documents.message}
              state="error"
              title="The document list could not be loaded"
            />
          )}
        </section>

        {canUpload ? (
          <section aria-labelledby="upload-title" className="workspace-upload">
            <h2 id="upload-title">Add a document</h2>
            {/* The deployment's own limits when the policy loaded; the API
                defaults only as a fallback for the hint text, since the API
                still decides every upload. */}
            <DocumentUpload
              acceptedExtensions={
                policy.ok ? policy.data.accepted_extensions : [...ACCEPTED_EXTENSIONS]
              }
              maxUploadBytes={policy.ok ? policy.data.max_upload_bytes : DEFAULT_MAX_UPLOAD_BYTES}
              workspaceId={workspace.data.id}
            />
          </section>
        ) : null}
      </main>
    </>
  );
}
