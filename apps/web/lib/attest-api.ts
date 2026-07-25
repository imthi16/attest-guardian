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
  memberListSchema,
  memberSchema,
  tokenPairSchema,
  userSchema,
  workspaceListSchema,
  workspaceWithRoleSchema,
  type Member,
  type MembershipRole,
  type TokenPair,
  type User,
  type WorkspaceWithRole,
} from "./contracts";
import { authorizedRequest, type AuthorizedResult } from "./session";

/** 204 responses carry no body; `null` is the only valid payload. */
const noContentSchema = z.null();

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
