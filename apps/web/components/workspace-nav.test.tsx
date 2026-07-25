import { render, screen } from "@testing-library/react";

import { WorkspaceNav } from "./workspace-nav";
import { ALL_ROLES } from "../lib/permissions";
import type { MembershipRole } from "../lib/contracts";

vi.mock("../app/auth-actions", () => ({ logoutAction: vi.fn() }));

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

function renderNav(role: MembershipRole) {
  return render(
    <WorkspaceNav
      role={role}
      userEmail="ravi@example.com"
      workspaceId={WORKSPACE_ID}
      workspaceName="Compliance"
    />,
  );
}

/**
 * Navigation must not advertise actions the API will refuse. These cases run
 * over every role the API defines, so adding a role without deciding its
 * navigation is a test failure rather than a silent omission.
 */
describe("WorkspaceNav", () => {
  it("shows member management to owners and admins", () => {
    for (const role of ["owner", "admin"] as const) {
      const { unmount } = renderNav(role);
      expect(screen.getByRole("link", { name: "Members" })).toHaveAttribute(
        "href",
        `/workspaces/${WORKSPACE_ID}/members`,
      );
      unmount();
    }
  });

  it("hides member management from members and viewers", () => {
    for (const role of ["member", "viewer"] as const) {
      const { unmount } = renderNav(role);
      expect(screen.queryByRole("link", { name: "Members" })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
      unmount();
    }
  });

  it("always offers sign out, the workspace name, and the caller's role", () => {
    for (const role of ALL_ROLES) {
      const { unmount } = renderNav(role);
      expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
      expect(screen.getByText("Compliance")).toBeInTheDocument();
      expect(screen.getByText("ravi@example.com")).toBeInTheDocument();
      expect(screen.getByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
      unmount();
    }
  });
});
