import { render, screen } from "@testing-library/react";

import MembersPage from "./page";
import MembersLoading from "./loading";
import { fetchCurrentUser, fetchMembers, fetchWorkspace } from "../../../../../lib/attest-api";
import type { MembershipRole } from "../../../../../lib/contracts";

vi.mock("../../../../../lib/attest-api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchMembers: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../../../app/workspace-actions", () => ({
  addMemberAction: vi.fn(),
  changeMemberRoleAction: vi.fn(),
  removeMemberAction: vi.fn(),
}));

vi.mock("../../../../auth-actions", () => ({ logoutAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
}));

const mockedUser = vi.mocked(fetchCurrentUser);
const mockedMembers = vi.mocked(fetchMembers);
const mockedWorkspace = vi.mocked(fetchWorkspace);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const USER_ID = "22222222-2222-4222-8222-222222222222";

const user = {
  ok: true as const,
  data: {
    id: USER_ID,
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

const roster = {
  ok: true as const,
  data: [
    {
      user_id: USER_ID,
      email: "ravi@example.com",
      full_name: "Ravi Kumar",
      role: "owner" as const,
      joined_at: "2026-01-01T00:00:00Z",
    },
    {
      user_id: "33333333-3333-4333-8333-333333333333",
      email: "priya@example.com",
      full_name: "Priya S",
      role: "member" as const,
      joined_at: "2026-02-01T00:00:00Z",
    },
  ],
};

const renderPage = async () =>
  render(await MembersPage({ params: Promise.resolve({ workspaceId: WORKSPACE_ID }) }));

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedMembers.mockResolvedValue(roster);
});

describe("MembersPage", () => {
  it("shows member management to owners and admins", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));

    await renderPage();

    expect(screen.getByRole("heading", { name: "Compliance members" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Add a member" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hides member management from members and viewers", async () => {
    for (const role of ["member", "viewer"] as const) {
      mockedWorkspace.mockResolvedValue(workspaceAs(role));
      const { unmount } = await renderPage();

      // The roster stays visible, but the invite form and an explicit refusal
      // replace the controls the API would reject anyway.
      expect(screen.getByRole("table")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Add a member" })).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent("Reference: insufficient_role");
      unmount();
    }
  });

  it("renders not found for workspace_not_found", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "workspace_not_found",
      message: "The workspace does not exist or you are not a member.",
      status: 404,
    });

    await renderPage();

    expect(screen.getByRole("heading", { name: "Workspace not found" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders the error state", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));
    mockedMembers.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable. Please try again shortly.",
      status: 503,
    });

    await renderPage();

    expect(screen.getByText("The member list could not be loaded")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders the empty state", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));
    mockedMembers.mockResolvedValue({ ok: true, data: [] });

    await renderPage();

    expect(screen.getByText("No members to show")).toBeInTheDocument();
  });

  it("renders the loading state", () => {
    render(<MembersLoading />);

    expect(screen.getByRole("article")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Loading members")).toBeInTheDocument();
  });

  it("sends an expired session back to login with a return path", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "session_expired",
      message: "Your session expired.",
      status: 401,
    });

    await expect(
      MembersPage({ params: Promise.resolve({ workspaceId: WORKSPACE_ID }) }),
    ).rejects.toThrow(`NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}/members`);
  });
});
