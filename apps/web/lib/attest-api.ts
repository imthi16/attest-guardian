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
  documentListSchema,
  documentProgressSchema,
  documentSchema,
  downloadLinkSchema,
  memberListSchema,
  memberSchema,
  tokenPairSchema,
  userSchema,
  workspaceListSchema,
  workspaceWithRoleSchema,
  type Document,
  type DocumentProgress,
  type DownloadLink,
  type Member,
  type MembershipRole,
  type TokenPair,
  type User,
  type WorkspaceWithRole,
} from "./contracts";
import { authorizedRequest, type AuthorizedResult } from "./session";

/** 204 responses carry no body; `null` is the only valid payload. */
const noContentSchema = z.null();

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
