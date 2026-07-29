/**
 * Server actions for the document lifecycle.
 *
 * Uploads and downloads run through route handlers instead (see
 * `app/api/workspaces/[workspaceId]/documents/`): an upload needs byte-level
 * progress in the browser, and a download must be a plain link navigation so
 * the presigned URL is not a form target — `form-action 'self'` in the CSP
 * would refuse that. Everything else is a small state change that belongs in
 * an action: each one relays the API's stable error code and revalidates the
 * affected paths, so the list a caller sees after acting is the API's view
 * rather than an optimistic guess.
 */
"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import {
  archiveDocument,
  deleteDocument,
  restoreDocument,
  retryDocumentIngestion,
} from "../lib/attest-api";
import { SESSION_EXPIRED, type AuthorizedResult } from "../lib/session";
import { fieldErrorsFrom, invalidInput, type FormState } from "./form-state";

function relayFailure<T>(result: AuthorizedResult<T>): FormState {
  if (result.ok) {
    return { status: "success" };
  }
  if (result.code === SESSION_EXPIRED) {
    redirect("/login?expired=1");
  }
  return { code: result.code, message: result.message, status: "error" };
}

const documentTargetSchema = z.object({
  documentId: z.string().uuid("Select a valid document."),
  workspaceId: z.string().uuid("Select a valid workspace."),
});

type DocumentTarget = z.infer<typeof documentTargetSchema>;

function parseTarget(formData: FormData): DocumentTarget | FormState {
  const parsed = documentTargetSchema.safeParse({
    documentId: String(formData.get("documentId") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  return parsed.success ? parsed.data : invalidInput(fieldErrorsFrom(parsed.error));
}

function isFormState(value: DocumentTarget | FormState): value is FormState {
  return "status" in value;
}

/** Refresh both the list and the detail view of one document. */
function revalidateDocument(target: DocumentTarget): void {
  revalidatePath(`/workspaces/${target.workspaceId}/documents`);
  revalidatePath(`/workspaces/${target.workspaceId}/documents/${target.documentId}`);
}

export async function archiveDocumentAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const target = parseTarget(formData);
  if (isFormState(target)) {
    return target;
  }

  const state = relayFailure(await archiveDocument(target.workspaceId, target.documentId));
  if (state.status === "success") {
    revalidateDocument(target);
    return {
      message: "The document is archived and will no longer be used as evidence.",
      status: "success",
    };
  }
  return state;
}

export async function restoreDocumentAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const target = parseTarget(formData);
  if (isFormState(target)) {
    return target;
  }

  const result = await restoreDocument(target.workspaceId, target.documentId);
  const state = relayFailure(result);
  if (state.status !== "success" || !result.ok) {
    return state;
  }
  revalidateDocument(target);
  // Restoring only clears `archived_at`. A document that never finished
  // processing is still excluded from evidence by its status, so promising it
  // is usable again would be wrong for exactly the documents most likely to be
  // archived in the first place.
  return {
    message:
      result.data.status === "ready"
        ? "The document is available as evidence again."
        : "The document is restored, but it is not evidence yet: processing has not completed successfully.",
    status: "success",
  };
}

export async function retryDocumentAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const target = parseTarget(formData);
  if (isFormState(target)) {
    return target;
  }

  const state = relayFailure(await retryDocumentIngestion(target.workspaceId, target.documentId));
  if (state.status === "success") {
    revalidateDocument(target);
    return { message: "Processing was queued again.", status: "success" };
  }
  return state;
}

/**
 * Permanently delete a document.
 *
 * The API refuses this unless the document is archived first, so an accidental
 * click can never destroy evidence that is still in use. On success the caller
 * is sent back to the list, because the detail page it came from no longer
 * describes anything.
 */
export async function deleteDocumentAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const target = parseTarget(formData);
  if (isFormState(target)) {
    return target;
  }

  const state = relayFailure(await deleteDocument(target.workspaceId, target.documentId));
  if (state.status === "error") {
    return state;
  }
  revalidateDocument(target);
  redirect(`/workspaces/${target.workspaceId}/documents?deleted=1`);
}
