/**
 * A read-only mirror of the API's workspace role matrix.
 *
 * This exists purely so navigation and controls reflect what the caller can
 * actually do, avoiding buttons that are guaranteed to fail. It is not an
 * authorization boundary: `apps/api/app/auth/permissions.py` remains the only
 * enforcement point, and the API rejects any action this mirror gets wrong.
 * Keep the two in sync; the parity test asserts the shapes match.
 */
import type { MembershipRole } from "./contracts";

export type WorkspaceCapability =
  | "manageDocuments"
  | "manageMembers"
  | "query"
  | "uploadDocuments"
  | "view";

/** Every capability the API defines, for the parity test to check against. */
export const ALL_CAPABILITIES: readonly WorkspaceCapability[] = [
  "view",
  "query",
  "uploadDocuments",
  "manageDocuments",
  "manageMembers",
];

const ROLE_CAPABILITIES: Record<MembershipRole, readonly WorkspaceCapability[]> = {
  owner: ["view", "query", "uploadDocuments", "manageDocuments", "manageMembers"],
  admin: ["view", "query", "uploadDocuments", "manageDocuments", "manageMembers"],
  member: ["view", "query", "uploadDocuments"],
  viewer: ["view", "query"],
};

/** Roles an actor may grant, change, or remove. */
const MANAGEABLE_ROLES: Record<MembershipRole, readonly MembershipRole[]> = {
  owner: ["owner", "admin", "member", "viewer"],
  admin: ["member", "viewer"],
  member: [],
  viewer: [],
};

export const ROLE_LABELS: Record<MembershipRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTIONS: Record<MembershipRole, string> = {
  owner: "Full control, including owners and workspace settings.",
  admin: "Manages members and documents, but not owners.",
  member: "Uploads documents and asks evidence-grounded questions.",
  viewer: "Reads documents and asks questions; changes nothing.",
};

export const ALL_ROLES: readonly MembershipRole[] = ["owner", "admin", "member", "viewer"];

export function allows(role: MembershipRole, capability: WorkspaceCapability): boolean {
  return ROLE_CAPABILITIES[role].includes(capability);
}

export function canManageRole(actor: MembershipRole, target: MembershipRole): boolean {
  return MANAGEABLE_ROLES[actor].includes(target);
}

/** Roles the actor may choose when inviting or promoting someone. */
export function grantableRoles(actor: MembershipRole): readonly MembershipRole[] {
  return MANAGEABLE_ROLES[actor];
}
