/**
 * Runtime contracts for the FastAPI endpoints this client consumes.
 *
 * Every response crossing the network boundary is parsed before it reaches a
 * component, so an unexpected or malformed payload becomes a stable typed
 * failure instead of an undefined field rendered into the page. The shapes
 * mirror `apps/api/app/schemas/{auth,workspaces}.py`; the API remains the
 * authority on authorization, and these types only describe what it returns.
 */
import { z } from "zod";

export const membershipRoleSchema = z.enum(["owner", "admin", "member", "viewer"]);
export type MembershipRole = z.infer<typeof membershipRoleSchema>;

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;

export const tokenPairSchema = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
});
export type TokenPair = z.infer<typeof tokenPairSchema>;

export const workspaceWithRoleSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  created_at: z.string(),
  role: membershipRoleSchema,
});
export type WorkspaceWithRole = z.infer<typeof workspaceWithRoleSchema>;

export const workspaceListSchema = z.array(workspaceWithRoleSchema);

export const memberSchema = z.object({
  user_id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: membershipRoleSchema,
  joined_at: z.string(),
});
export type Member = z.infer<typeof memberSchema>;

export const memberListSchema = z.array(memberSchema);

/**
 * The API's stable error envelope: `{"detail": {"code", "message"}}`. Clients
 * branch on `code`; `message` is human wording and may change.
 */
export const apiErrorDetailSchema = z.object({
  detail: z.object({
    code: z.string(),
    message: z.string(),
  }),
});

/** Error codes the UI reacts to specifically. */
export const errorCodes = {
  cannotManageRole: "cannot_manage_role",
  emailAlreadyRegistered: "email_already_registered",
  insufficientRole: "insufficient_role",
  invalidCredentials: "invalid_credentials",
  invalidRefreshToken: "invalid_refresh_token",
  lastOwner: "last_owner",
  memberAlreadyExists: "member_already_exists",
  notAuthenticated: "not_authenticated",
  rateLimited: "rate_limited",
  slugAlreadyExists: "slug_already_exists",
  userNotFound: "user_not_found",
  workspaceNotFound: "workspace_not_found",
} as const;

/** Local codes for failures that never reach the API. */
export const clientErrorCodes = {
  invalidResponse: "invalid_api_response",
  network: "api_unreachable",
  validation: "invalid_input",
} as const;
