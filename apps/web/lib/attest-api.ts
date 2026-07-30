/**
 * Typed use cases against the FastAPI auth and workspace endpoints.
 *
 * Each function is server-only and returns a validated result, so pages and
 * server actions never touch raw fetch responses. Authorization decisions are
 * made by the API; these helpers only carry them through faithfully.
 */
import { z } from "zod";

import { apiRequest, type ApiResult } from "./api-client";
import {
  conversationDetailSchema,
  conversationListSchema,
  conversationSchema,
  documentListSchema,
  documentProgressSchema,
  documentSchema,
  downloadLinkSchema,
  memberListSchema,
  memberSchema,
  messageFeedbackListSchema,
  messageFeedbackSchema,
  resolvedCitationSchema,
  tokenPairSchema,
  uploadPolicySchema,
  userSchema,
  workspaceListSchema,
  workspaceWithRoleSchema,
  type Conversation,
  type ConversationDetail,
  type Document,
  type DocumentProgress,
  type DownloadLink,
  type FeedbackRating,
  type Member,
  type MembershipRole,
  type MessageFeedback,
  type ResolvedCitation,
  type TokenPair,
  type UploadPolicy,
  type User,
  type WorkspaceWithRole,
} from "./contracts";
import { authorizedRequest, type AuthorizedResult } from "./session";

/** 204 responses carry no body; `null` is the only valid payload. */
const noContentSchema = z.null();

/** Path prefix for one workspace's conversations, with both ids escaped. */
function conversationsPath(workspaceId: string, conversationId?: string): string {
  const base = `/workspaces/${encodeURIComponent(workspaceId)}/conversations`;
  return conversationId === undefined ? base : `${base}/${encodeURIComponent(conversationId)}`;
}

/** Path prefix for one workspace's documents, with both ids escaped. */
function documentsPath(workspaceId: string, documentId?: string): string {
  const base = `/workspaces/${encodeURIComponent(workspaceId)}/documents`;
  return documentId === undefined ? base : `${base}/${encodeURIComponent(documentId)}`;
}

export function registerAccount(input: {
  email: string;
  fullName: string;
  password: string;
}): Promise<ApiResult<User>> {
  return apiRequest({
    body: { email: input.email, full_name: input.fullName, password: input.password },
    method: "POST",
    path: "/auth/register",
    schema: userSchema,
  });
}

export function requestTokenPair(input: {
  email: string;
  password: string;
}): Promise<ApiResult<TokenPair>> {
  return apiRequest({
    body: { email: input.email, password: input.password },
    method: "POST",
    path: "/auth/login",
    schema: tokenPairSchema,
  });
}

/** Revoke one refresh-token session server side; idempotent by design. */
export function revokeRefreshToken(refreshToken: string): Promise<ApiResult<null>> {
  return apiRequest({
    body: { refresh_token: refreshToken },
    method: "POST",
    path: "/auth/logout",
    schema: noContentSchema,
  });
}

export function fetchCurrentUser(): Promise<AuthorizedResult<User>> {
  return authorizedRequest({ path: "/auth/me", schema: userSchema });
}

export function fetchWorkspaces(): Promise<AuthorizedResult<WorkspaceWithRole[]>> {
  return authorizedRequest({ path: "/workspaces", schema: workspaceListSchema });
}

export function fetchWorkspace(workspaceId: string): Promise<AuthorizedResult<WorkspaceWithRole>> {
  return authorizedRequest({
    path: `/workspaces/${encodeURIComponent(workspaceId)}`,
    schema: workspaceWithRoleSchema,
  });
}

export function createWorkspace(name: string): Promise<AuthorizedResult<WorkspaceWithRole>> {
  return authorizedRequest({
    body: { name },
    method: "POST",
    path: "/workspaces",
    schema: workspaceWithRoleSchema,
  });
}

export function fetchMembers(workspaceId: string): Promise<AuthorizedResult<Member[]>> {
  return authorizedRequest({
    path: `/workspaces/${encodeURIComponent(workspaceId)}/members`,
    schema: memberListSchema,
  });
}

export function addMember(input: {
  email: string;
  role: MembershipRole;
  workspaceId: string;
}): Promise<AuthorizedResult<Member>> {
  return authorizedRequest({
    body: { email: input.email, role: input.role },
    method: "POST",
    path: `/workspaces/${encodeURIComponent(input.workspaceId)}/members`,
    schema: memberSchema,
  });
}

export function changeMemberRole(input: {
  role: MembershipRole;
  userId: string;
  workspaceId: string;
}): Promise<AuthorizedResult<Member>> {
  return authorizedRequest({
    body: { role: input.role },
    method: "PATCH",
    path: `/workspaces/${encodeURIComponent(input.workspaceId)}/members/${encodeURIComponent(
      input.userId,
    )}`,
    schema: memberSchema,
  });
}

export function removeMember(input: {
  userId: string;
  workspaceId: string;
}): Promise<AuthorizedResult<null>> {
  return authorizedRequest({
    method: "DELETE",
    path: `/workspaces/${encodeURIComponent(input.workspaceId)}/members/${encodeURIComponent(
      input.userId,
    )}`,
    schema: noContentSchema,
  });
}

/**
 * The upload limits this deployment enforces.
 *
 * Read from the API so the browser and the upload relay fail fast against the
 * deployed configuration rather than a compiled-in copy of the defaults.
 */
export function fetchUploadPolicy(workspaceId: string): Promise<AuthorizedResult<UploadPolicy>> {
  return authorizedRequest({
    path: `${documentsPath(workspaceId)}/policy`,
    schema: uploadPolicySchema,
  });
}

/**
 * List a workspace's documents. Archived documents are withdrawn from evidence
 * and hidden unless explicitly asked for, matching the API's default.
 */
export function fetchDocuments(
  workspaceId: string,
  options: { includeArchived?: boolean } = {},
): Promise<AuthorizedResult<Document[]>> {
  const query = options.includeArchived === true ? "?include_archived=true" : "";
  return authorizedRequest({
    path: `${documentsPath(workspaceId)}${query}`,
    schema: documentListSchema,
  });
}

export function fetchDocument(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<Document>> {
  return authorizedRequest({
    path: documentsPath(workspaceId, documentId),
    schema: documentSchema,
  });
}

export function fetchDocumentProgress(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<DocumentProgress>> {
  return authorizedRequest({
    path: `${documentsPath(workspaceId, documentId)}/status`,
    schema: documentProgressSchema,
  });
}

/**
 * Mint a short-lived presigned download URL.
 *
 * The link is requested at the moment of the click rather than embedded in a
 * rendered page, so a URL never outlives the page that would have shown it.
 */
export function requestDownloadLink(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<DownloadLink>> {
  return authorizedRequest({
    path: `${documentsPath(workspaceId, documentId)}/download`,
    schema: downloadLinkSchema,
  });
}

/** Forward an already-validated multipart upload to the API. */
export function uploadDocument(
  workspaceId: string,
  file: FormData,
): Promise<AuthorizedResult<Document>> {
  return authorizedRequest({
    body: file,
    method: "POST",
    path: documentsPath(workspaceId),
    schema: documentSchema,
  });
}

export function archiveDocument(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<Document>> {
  return authorizedRequest({
    method: "POST",
    path: `${documentsPath(workspaceId, documentId)}/archive`,
    schema: documentSchema,
  });
}

export function restoreDocument(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<Document>> {
  return authorizedRequest({
    method: "POST",
    path: `${documentsPath(workspaceId, documentId)}/restore`,
    schema: documentSchema,
  });
}

export function retryDocumentIngestion(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<DocumentProgress>> {
  return authorizedRequest({
    method: "POST",
    path: `${documentsPath(workspaceId, documentId)}/retry`,
    schema: documentProgressSchema,
  });
}

export function deleteDocument(
  workspaceId: string,
  documentId: string,
): Promise<AuthorizedResult<null>> {
  return authorizedRequest({
    method: "DELETE",
    path: documentsPath(workspaceId, documentId),
    schema: noContentSchema,
  });
}

export function fetchConversations(workspaceId: string): Promise<AuthorizedResult<Conversation[]>> {
  return authorizedRequest({
    path: conversationsPath(workspaceId),
    schema: conversationListSchema,
  });
}

export function createConversation(
  workspaceId: string,
  title: string | null,
): Promise<AuthorizedResult<Conversation>> {
  return authorizedRequest({
    body: { title },
    method: "POST",
    path: conversationsPath(workspaceId),
    schema: conversationSchema,
  });
}

/** One thread with all of its turns, citations, and claim verdicts. */
export function fetchConversation(
  workspaceId: string,
  conversationId: string,
): Promise<AuthorizedResult<ConversationDetail>> {
  return authorizedRequest({
    path: conversationsPath(workspaceId, conversationId),
    schema: conversationDetailSchema,
  });
}

export function deleteConversation(
  workspaceId: string,
  conversationId: string,
): Promise<AuthorizedResult<null>> {
  return authorizedRequest({
    method: "DELETE",
    path: conversationsPath(workspaceId, conversationId),
    schema: noContentSchema,
  });
}

/**
 * Prove a citation against stored provenance.
 *
 * The evidence panel never renders the quote the answer supplied; it renders
 * `supporting_text`, which the API reads back from stored content at validated
 * offsets. A citation that does not match its source fails here instead of
 * being displayed as if it did.
 */
export function resolveCitation(
  workspaceId: string,
  citation: {
    chunk_id: string;
    document_version_id: string;
    quote: string;
    quote_char_start: number;
    quote_char_end: number;
  },
): Promise<AuthorizedResult<ResolvedCitation>> {
  return authorizedRequest({
    body: citation,
    method: "POST",
    path: `/workspaces/${encodeURIComponent(workspaceId)}/citations/resolve`,
    schema: resolvedCitationSchema,
  });
}

export function submitFeedback(
  workspaceId: string,
  conversationId: string,
  messageId: string,
  body: { note: string | null; rating: FeedbackRating },
): Promise<AuthorizedResult<MessageFeedback>> {
  return authorizedRequest({
    body,
    method: "PUT",
    path: `${conversationsPath(workspaceId, conversationId)}/messages/${encodeURIComponent(messageId)}/feedback`,
    schema: messageFeedbackSchema,
  });
}

export function fetchFeedback(
  workspaceId: string,
  conversationId: string,
  messageId: string,
): Promise<AuthorizedResult<MessageFeedback[]>> {
  return authorizedRequest({
    path: `${conversationsPath(workspaceId, conversationId)}/messages/${encodeURIComponent(messageId)}/feedback`,
    schema: messageFeedbackListSchema,
  });
}
