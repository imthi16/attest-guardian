import { render, screen } from "@testing-library/react";

import WorkspacesPage from "./page";
import WorkspacesLoading from "./loading";
import { fetchCurrentUser, fetchWorkspaces } from "../../../lib/attest-api";
import { readActiveWorkspaceId } from "../../../lib/session";

vi.mock("../../../lib/attest-api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchWorkspaces: vi.fn(),
}));

vi.mock("../../../lib/session", async () => {
  const actual =
    await vi.importActual<typeof import("../../../lib/session")>("../../../lib/session");
  return { SESSION_EXPIRED: actual.SESSION_EXPIRED, readActiveWorkspaceId: vi.fn() };
});

vi.mock("../../workspace-actions", () => ({
  createWorkspaceAction: vi.fn(),
  selectWorkspaceAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
}));

const mockedUser = vi.mocked(fetchCurrentUser);
const mockedWorkspaces = vi.mocked(fetchWorkspaces);
const mockedActive = vi.mocked(readActiveWorkspaceId);

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

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedActive.mockResolvedValue(null);
});

describe("WorkspacesPage", () => {
  it("lists the workspaces", async () => {
    mockedWorkspaces.mockResolvedValue({
      ok: true,
      data: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          name: "Compliance",
          slug: "compliance-a1b2c3",
          created_at: "2026-01-01T00:00:00Z",
          role: "owner",
        },
      ],
    });

    render(await WorkspacesPage());

    expect(screen.getByRole("heading", { name: "Choose a workspace" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Compliance" })).toBeInTheDocument();
    expect(screen.getByText("Signed in as ravi@example.com")).toBeInTheDocument();
  });

  it("renders the empty state", async () => {
    mockedWorkspaces.mockResolvedValue({ ok: true, data: [] });

    render(await WorkspacesPage());

    expect(screen.getByText("No workspaces available")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create a workspace" })).toBeInTheDocument();
  });

  it("renders the error state", async () => {
    mockedWorkspaces.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable. Please try again shortly.",
      status: 503,
    });

    render(await WorkspacesPage());

    expect(screen.getByRole("alert")).toHaveTextContent("The service is unavailable.");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: api_unreachable");
  });

  it("renders the loading state", () => {
    render(<WorkspacesLoading />);

    const region = screen.getByRole("article");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Loading workspaces")).toBeInTheDocument();
  });

  it("sends an expired session back to login with a return path", async () => {
    mockedWorkspaces.mockResolvedValue({
      ok: false,
      code: "session_expired",
      message: "Your session expired.",
      status: 401,
    });

    await expect(WorkspacesPage()).rejects.toThrow(
      "NEXT_REDIRECT:/login?expired=1&next=/workspaces",
    );
  });
});
