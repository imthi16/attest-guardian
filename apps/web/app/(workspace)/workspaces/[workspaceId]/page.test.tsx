import { render, screen } from "@testing-library/react";

import WorkspaceOverviewPage from "./page";
import { fetchCurrentUser, fetchWorkspace } from "../../../../lib/attest-api";
import { ALL_ROLES } from "../../../../lib/permissions";
import type { MembershipRole } from "../../../../lib/contracts";

vi.mock("../../../../lib/attest-api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../auth-actions", () => ({ logoutAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
}));

const mockedUser = vi.mocked(fetchCurrentUser);
const mockedWorkspace = vi.mocked(fetchWorkspace);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

const user = {
  ok: true as const,
  data: {
    id: "user-1",
    email: "ravi@example.com",
    full_name: "Ravi Kumar",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
};

const workspaceAs = (role: MembershipRole) => ({
  ok: true as const,
  data: {
    id: WORKSPACE_ID,
    name: "Compliance",
    slug: "compliance-a1b2c3",
    created_at: "2026-01-01T00:00:00Z",
    role,
  },
});

const renderPage = async () =>
  render(await WorkspaceOverviewPage({ params: Promise.resolve({ workspaceId: WORKSPACE_ID }) }));

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
});

describe("WorkspaceOverviewPage", () => {
  it("renders Tamil copy with a ta language tag", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));

    await renderPage();

    const tamil = screen.getByText(/ஆதாரத்துடன் பதில்/);
    expect(tamil).toHaveAttribute("lang", "ta");
    expect(tamil.textContent).toMatch(/^[\u0B80-\u0BFF\s.]+$/u);
  });

  it("states the caller's role and what it permits", async () => {
    for (const role of ALL_ROLES) {
      mockedWorkspace.mockResolvedValue(workspaceAs(role));
      const { unmount } = await renderPage();

      const manageMembers = screen.getByText("Manage workspace members");
      const expected = role === "owner" || role === "admin" ? "true" : "false";
      expect(manageMembers).toHaveAttribute("data-allowed", expected);
      expect(screen.getByText("Upload documents for ingestion")).toHaveAttribute(
        "data-allowed",
        role === "viewer" ? "false" : "true",
      );
      unmount();
    }
  });

  it("renders access denied for insufficient_role", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: 403,
    });

    await renderPage();

    expect(screen.getByRole("heading", { name: "Access denied" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
  });

  it("still renders when the current user cannot be resolved", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("member"));
    mockedUser.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable.",
      status: 503,
    });

    await renderPage();

    expect(screen.getByText("Signed in")).toBeInTheDocument();
  });

  it("sends an expired session back to login with a return path", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "session_expired",
      message: "Your session expired.",
      status: 401,
    });

    await expect(
      WorkspaceOverviewPage({ params: Promise.resolve({ workspaceId: WORKSPACE_ID }) }),
    ).rejects.toThrow(`NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}`);
  });
});
