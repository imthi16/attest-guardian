/**
 * Server actions for conversations.
 *
 * Asking a question goes through a route handler instead (see
 * `app/api/workspaces/[workspaceId]/conversations/[conversationId]/stream`),
 * because an action returns once and cannot report progress while the pipeline
 * runs. Everything else is a small state change that belongs in an action: each
 * relays the API's stable error code and revalidates the affected paths, so what
 * the caller sees afterwards is the API's view rather than an optimistic guess.
 */
"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import {
  createConversation,
  deleteConversation,
  resolveCitation,
  submitFeedback,
} from "../lib/attest-api";
import { feedbackRatingSchema, type ResolvedCitation } from "../lib/contracts";
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

const workspaceSchema = z.object({
  workspaceId: z.string().uuid("Select a valid workspace."),
});

const conversationSchema = workspaceSchema.extend({
  conversationId: z.string().uuid("Select a valid conversation."),
});

const startSchema = workspaceSchema.extend({
  // A thread does not need a title; an untitled one is labelled by its first
  // question instead of forcing the asker to name it up front.
  title: z.string().trim().max(500, "Keep the title under 500 characters.").optional(),
});

const feedbackSchema = conversationSchema.extend({
  messageId: z.string().uuid("Select a valid answer."),
  note: z.string().trim().max(2000, "Keep the note under 2000 characters.").optional(),
  rating: feedbackRatingSchema,
});

/**
 * Start a thread and go to it.
 *
 * The redirect is outside the try/catch shape used elsewhere because Next.js
 * signals redirects by throwing; catching it here would swallow the navigation.
 */
export async function startConversationAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = startSchema.safeParse({
    title: String(formData.get("title") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const title =
    parsed.data.title === undefined || parsed.data.title === "" ? null : parsed.data.title;
  const result = await createConversation(parsed.data.workspaceId, title);
  const state = relayFailure(result);
  if (state.status !== "success" || !result.ok) {
    return state;
  }
  revalidatePath(`/workspaces/${parsed.data.workspaceId}/conversations`);
  redirect(`/workspaces/${parsed.data.workspaceId}/conversations/${result.data.id}`);
}

export async function deleteConversationAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = conversationSchema.safeParse({
    conversationId: String(formData.get("conversationId") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const state = relayFailure(
    await deleteConversation(parsed.data.workspaceId, parsed.data.conversationId),
  );
  if (state.status === "error") {
    return state;
  }
  revalidatePath(`/workspaces/${parsed.data.workspaceId}/conversations`);
  redirect(`/workspaces/${parsed.data.workspaceId}/conversations?deleted=1`);
}

export async function submitFeedbackAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = feedbackSchema.safeParse({
    conversationId: String(formData.get("conversationId") ?? ""),
    messageId: String(formData.get("messageId") ?? ""),
    note: String(formData.get("note") ?? ""),
    rating: String(formData.get("rating") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const state = relayFailure(
    await submitFeedback(
      parsed.data.workspaceId,
      parsed.data.conversationId,
      parsed.data.messageId,
      {
        note: parsed.data.note === undefined || parsed.data.note === "" ? null : parsed.data.note,
        rating: parsed.data.rating,
      },
    ),
  );
  if (state.status !== "success") {
    return state;
  }
  revalidatePath(
    `/workspaces/${parsed.data.workspaceId}/conversations/${parsed.data.conversationId}`,
  );
  return { message: "Thanks — your review was recorded.", status: "success" };
}

export type CitationResolution =
  | Readonly<{ code: string; message: string; ok: false }>
  | Readonly<{ citation: ResolvedCitation; ok: true }>;

/**
 * Prove one citation and return the evidence to show.
 *
 * Called from the evidence panel on demand rather than resolving every citation
 * up front: resolution is audited server side, and auditing a citation nobody
 * opened would make the log describe reading that never happened.
 *
 * The panel renders `supporting_text` from this result, never the quote the
 * answer supplied, so evidence displayed is always text read back from the
 * stored document at validated offsets.
 */
export async function resolveCitationAction(
  workspaceId: string,
  citation: {
    chunk_id: string;
    document_version_id: string;
    quote: string;
    quote_char_end: number;
    quote_char_start: number;
  },
): Promise<CitationResolution> {
  const result = await resolveCitation(workspaceId, citation);
  if (result.ok) {
    return { citation: result.data, ok: true };
  }
  if (result.code === SESSION_EXPIRED) {
    redirect("/login?expired=1");
  }
  return { code: result.code, message: result.message, ok: false };
}
