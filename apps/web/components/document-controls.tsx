/**
 * Lifecycle controls for one document, shared by the list and the detail page.
 *
 * Which controls appear mirrors the API's role matrix and the document's own
 * state — retry only for a failed document, restore only for an archived one —
 * so the UI never advertises an action that is guaranteed to fail. It is a
 * mirror, not a gate: every control posts to the API, which re-authorizes it
 * and answers with a stable code if this mirror has drifted.
 *
 * Destructive controls confirm first, and permanent deletion is offered only
 * once a document is archived, so evidence still in use cannot be destroyed by
 * one mistaken click. Titles come from uploaded files and are rendered as text.
 */
"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import {
  archiveDocumentAction,
  deleteDocumentAction,
  restoreDocumentAction,
  retryDocumentAction,
} from "../app/document-actions";
import { Feedback } from "./feedback";
import type { FormState } from "../app/form-state";
import type { Document } from "../lib/contracts";

const idleState: FormState = { status: "idle" };

export type DocumentCapabilities = Readonly<{
  canManage: boolean;
  canUpload: boolean;
}>;

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

type ActionFormProps = Readonly<{
  action: (previous: FormState, formData: FormData) => Promise<FormState>;
  buttonClassName: string;
  confirmMessage?: string;
  documentId: string;
  label: string;
  pendingLabel: string;
  workspaceId: string;
}>;

/** One control plus the feedback for its own outcome. */
function ActionForm({
  action,
  buttonClassName,
  confirmMessage,
  documentId,
  label,
  pendingLabel,
  workspaceId,
}: ActionFormProps) {
  const [state, formAction] = useActionState(action, idleState);
  return (
    <>
      <form action={formAction} className="inline-form">
        <input name="workspaceId" type="hidden" value={workspaceId} />
        <input name="documentId" type="hidden" value={documentId} />
        <PendingButton
          className={buttonClassName}
          confirmMessage={confirmMessage}
          label={label}
          pendingLabel={pendingLabel}
        />
      </form>
      {state.status === "error" && state.message !== undefined ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}
      {state.status === "success" && state.message !== undefined ? (
        <Feedback message={state.message} tone="success" />
      ) : null}
    </>
  );
}

type DocumentControlsProps = Readonly<{
  capabilities: DocumentCapabilities;
  entry: Document;
  workspaceId: string;
}>;

export function DocumentControls({ capabilities, entry, workspaceId }: DocumentControlsProps) {
  const archived = entry.archived_at !== null;
  return (
    <div className="document-actions">
      {/* A link, not a form: the presigned URL is minted by the route handler
          at click time, and `form-action 'self'` would refuse a form redirect
          to the storage origin. */}
      <a
        className="secondary-button"
        href={`/api/workspaces/${workspaceId}/documents/${entry.id}/download`}
      >
        Download
      </a>
      {capabilities.canUpload && entry.status === "failed" && !archived ? (
        <ActionForm
          action={retryDocumentAction}
          buttonClassName="secondary-button"
          documentId={entry.id}
          label="Process again"
          pendingLabel="Queueing"
          workspaceId={workspaceId}
        />
      ) : null}
      {capabilities.canManage ? (
        archived ? (
          <>
            <ActionForm
              action={restoreDocumentAction}
              buttonClassName="secondary-button"
              documentId={entry.id}
              label="Restore"
              pendingLabel="Restoring"
              workspaceId={workspaceId}
            />
            <ActionForm
              action={deleteDocumentAction}
              buttonClassName="danger-button"
              confirmMessage={`Permanently delete ${entry.title}? The file, its text, and every evidence span are destroyed and cannot be recovered.`}
              documentId={entry.id}
              label="Delete permanently"
              pendingLabel="Deleting"
              workspaceId={workspaceId}
            />
          </>
        ) : (
          <ActionForm
            action={archiveDocumentAction}
            buttonClassName="secondary-button"
            confirmMessage={`Archive ${entry.title}? Answers stop using it as evidence until it is restored.`}
            documentId={entry.id}
            label="Archive"
            pendingLabel="Archiving"
            workspaceId={workspaceId}
          />
        )
      ) : (
        <span className="muted-note">Owners and admins manage the library</span>
      )}
    </div>
  );
}
