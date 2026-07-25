import { readFileSync } from "node:fs";
import { join } from "node:path";

import { allows, ALL_ROLES, canManageRole, grantableRoles, ROLE_LABELS } from "./permissions";
import { membershipRoleSchema } from "./contracts";

/**
 * The UI role mirror is advisory, but a mirror that drifts from the API is
 * worse than none: it either hides work the user may do, or offers actions
 * that always fail. These tests read the Python matrix and assert the two
 * agree, so a backend role change breaks the build instead of the product.
 */
const permissionsSource = readFileSync(
  join(process.cwd(), "..", "api", "app", "auth", "permissions.py"),
  "utf8",
);

const enumsSource = readFileSync(
  join(process.cwd(), "..", "api", "app", "db", "models", "enums.py"),
  "utf8",
);

describe("workspace role mirror", () => {
  it("covers exactly the roles the API defines", () => {
    const apiRoles = [...enumsSource.matchAll(/^ {4}(OWNER|ADMIN|MEMBER|VIEWER) = "(\w+)"$/gm)].map(
      (match) => match[2],
    );

    expect(apiRoles.sort()).toEqual([...ALL_ROLES].sort());
    expect(membershipRoleSchema.options.sort()).toEqual(apiRoles.sort());
    expect(Object.keys(ROLE_LABELS).sort()).toEqual(apiRoles.sort());
  });

  it("matches the API capability matrix", () => {
    // Owners and admins hold every action; members lose member management;
    // viewers additionally lose uploads. Asserted against the source so a
    // change to `_ROLE_ACTIONS` cannot pass unnoticed.
    expect(permissionsSource).toContain("MembershipRole.OWNER: frozenset(WorkspaceAction)");
    expect(permissionsSource).toContain("MembershipRole.ADMIN: frozenset(WorkspaceAction)");
    expect(permissionsSource).toMatch(
      /MembershipRole\.MEMBER: frozenset\(\s*\{WorkspaceAction\.VIEW, WorkspaceAction\.QUERY, WorkspaceAction\.UPLOAD_DOCUMENTS\}\s*\)/,
    );
    expect(permissionsSource).toContain(
      "MembershipRole.VIEWER: frozenset({WorkspaceAction.VIEW, WorkspaceAction.QUERY})",
    );

    for (const role of ALL_ROLES) {
      expect(allows(role, "view")).toBe(true);
      expect(allows(role, "query")).toBe(true);
    }
    expect(allows("member", "uploadDocuments")).toBe(true);
    expect(allows("viewer", "uploadDocuments")).toBe(false);
    expect(allows("owner", "manageMembers")).toBe(true);
    expect(allows("admin", "manageMembers")).toBe(true);
    expect(allows("member", "manageMembers")).toBe(false);
    expect(allows("viewer", "manageMembers")).toBe(false);
  });

  it("matches the API role-management matrix", () => {
    expect(permissionsSource).toContain("MembershipRole.OWNER: frozenset(MembershipRole)");
    expect(permissionsSource).toContain(
      "MembershipRole.ADMIN: frozenset({MembershipRole.MEMBER, MembershipRole.VIEWER})",
    );
    expect(permissionsSource).toContain("MembershipRole.MEMBER: frozenset()");
    expect(permissionsSource).toContain("MembershipRole.VIEWER: frozenset()");

    // An owner manages every role; an admin manages only unprivileged ones,
    // so an admin can never lock owners out or escalate themselves.
    for (const role of ALL_ROLES) {
      expect(canManageRole("owner", role)).toBe(true);
    }
    expect(canManageRole("admin", "owner")).toBe(false);
    expect(canManageRole("admin", "admin")).toBe(false);
    expect(canManageRole("admin", "member")).toBe(true);
    expect(canManageRole("admin", "viewer")).toBe(true);
    expect(grantableRoles("member")).toHaveLength(0);
    expect(grantableRoles("viewer")).toHaveLength(0);
    expect(grantableRoles("admin")).toEqual(["member", "viewer"]);
  });
});
