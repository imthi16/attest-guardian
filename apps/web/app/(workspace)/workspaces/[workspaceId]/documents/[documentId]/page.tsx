import Link from "next/link";
import { redirect } from "next/navigation";

import { AccessNotice } from "../../../../../../components/access-notice";
import { DocumentControls } from "../../../../../../components/document-controls";
import { IngestionState } from "../../../../../../components/ingestion-state";
import { SystemState } from "../../../../../../components/system-state";
import { WorkspaceNav } from "../../../../../../components/workspace-nav";
import {
  fetchCurrentUser,
  fetchDocument,
  fetchDocumentProgress,
  fetchWorkspace,
} from "../../../../../../lib/attest-api";
import { allows } from "../../../../../../lib/permissions";
import { formatBytes } from "../../../../../../lib/upload-rules";
import { SESSION_EXPIRED } from "../../../../../../lib/session";

export const dynamic = "force-dynamic";

type DocumentPageProps = Readonly<{
  params: Promise<Readonly<{ documentId: string; workspaceId: string }>>;
}>;

/**
 * One document: its identity, its exact processing state, and its controls.
 *
 * Nothing here previews document contents. The file's own text is untrusted
 * input to the model and is only ever surfaced through cited evidence spans, so
 * this page shows verifiable facts about the file — name, type, size, content
 * hash, lifecycle — and never renders bytes from it as markup.
 */
export default async function DocumentDetailPage({ params }: DocumentPageProps) {
  const { documentId, workspaceId } = await params;
  const [user, workspace, document, progress] = await Promise.all([
    fetchCurrentUser(),
    fetchWorkspace(workspaceId),
    fetchDocument(workspaceId, documentId),
    fetchDocumentProgress(workspaceId, documentId),
  ]);

  for (const result of [user, workspace, document, progress]) {
    if (!result.ok && result.code === SESSION_EXPIRED) {
      redirect(`/login?expired=1&next=/workspaces/${workspaceId}/documents/${documentId}`);
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
  const nav = (
    <WorkspaceNav
      role={role}
      userEmail={user.ok ? user.data.email : "Signed in"}
      workspaceId={workspace.data.id}
      workspaceName={workspace.data.name}
    />
  );

  if (!document.ok) {
    return (
      <>
        {nav}
        <main className="workspace-main" id="main-content">
          <AccessNotice code={document.code} message={document.message} />
        </main>
      </>
    );
  }

  return (
    <>
      {nav}
      <main className="workspace-main" id="main-content">
        <section aria-labelledby="document-title" className="workspace-intro">
          <p className="eyebrow">DOCUMENT</p>
          <h1 id="document-title">{document.data.title}</h1>
          <p className="auth-copy">
            <Link href={`/workspaces/${workspace.data.id}/documents`}>
              Back to {workspace.data.name} documents
            </Link>
          </p>
        </section>

        <section aria-labelledby="facts-title" className="workspace-document-facts">
          <h2 id="facts-title">File</h2>
          <dl className="document-facts">
            <div>
              <dt>Original filename</dt>
              <dd>{document.data.source_filename}</dd>
            </div>
            <div>
              <dt>Detected type</dt>
              <dd>{document.data.mime_type}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{formatBytes(document.data.size_bytes)}</dd>
            </div>
            <div>
              <dt>Content hash (SHA-256)</dt>
              <dd className="document-hash">{document.data.sha256}</dd>
            </div>
            <div>
              <dt>Uploaded</dt>
              <dd>
                <time dateTime={document.data.created_at}>{document.data.created_at}</time>
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="state-title" className="workspace-document-state">
          <h2 id="state-title">Processing</h2>
          {progress.ok ? (
            <IngestionState progress={progress.data} />
          ) : (
            <SystemState
              description={progress.message}
              state="error"
              title="The processing state could not be loaded"
            />
          )}
        </section>

        <section aria-labelledby="controls-title" className="workspace-document-controls">
          <h2 id="controls-title">Actions</h2>
          <DocumentControls
            capabilities={{ canManage: allows(role, "manageDocuments") }}
            entry={document.data}
            workspaceId={workspace.data.id}
          />
        </section>
      </main>
    </>
  );
}
