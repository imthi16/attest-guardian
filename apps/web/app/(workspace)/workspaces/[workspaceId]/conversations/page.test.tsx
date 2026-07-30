import { render, screen } from "@testing-library/react";

import ConversationsPage from "./page";
import ConversationsLoading from "./loading";
import {
  fetchConversations,
  fetchCurrentUser,
  fetchWorkspace,
} from "../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../lib/session";
import type { MembershipRole } from "../../../../../lib/contracts";

vi.mock("../../../../../lib/attest-api", () => ({
  fetchConversations: vi.fn(),
  fetchCurrentUser: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../../auth-actions", () => ({ logoutAction: vi.fn() }));
vi.mock("../../../../conversation-actions", () => ({ startConversationAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const mockedConversations = vi.mocked(fetchConversations);
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

function workspaceAs(role: MembershipRole) {
  return {
    ok: true as const,
    data: {
      id: WORKSPACE_ID,
      name: "Compliance",
      slug: "compliance",
      created_at: "2026-01-01T00:00:00Z",
      role,
    },
  };
}

const thread = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Invoice terms",
  created_at: "2026-07-30T09:00:00Z",
  updated_at: "2026-07-30T09:30:00Z",
};

async function renderPage(role: MembershipRole, searchParams: Record<string, string> = {}) {
  mockedWorkspace.mockResolvedValue(workspaceAs(role));
  render(
    await ConversationsPage({
      params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedConversations.mockResolvedValue({ ok: true, data: [thread] });
});

describe("ConversationsPage", () => {
  it("lists threads and offers to start one for a member", async () => {
    await renderPage("member");

    expect(screen.getByRole("heading", { name: /Questions about Compliance/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Invoice terms" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/conversations/${thread.id}`,
    );
    expect(screen.getByRole("button", { name: "Start a thread" })).toBeInTheDocument();
  });

  it("explains to a viewer why they cannot ask", async () => {
    // `query` lets a viewer ask without persisting; writing a thread does not.
    await renderPage("viewer");

    expect(screen.queryByRole("button", { name: "Start a thread" })).not.toBeInTheDocument();
    const notice = screen.getByRole("alert");
    expect(notice).toHaveTextContent("only members, admins, and owners can ask new ones");
    expect(notice).toHaveTextContent("Reference: insufficient_role");
  });

  it("labels an untitled thread rather than rendering nothing", async () => {
    mockedConversations.mockResolvedValue({ ok: true, data: [{ ...thread, title: null }] });

    await renderPage("member");

    expect(screen.getByRole("link", { name: "Untitled thread" })).toBeInTheDocument();
  });

  it("says the documents were not touched after a deletion", async () => {
    await renderPage("owner", { deleted: "1" });

    expect(screen.getByRole("status")).toHaveTextContent("documents they cited were not touched");
  });

  it("shows an empty state when nothing has been asked", async () => {
    mockedConversations.mockResolvedValue({ ok: true, data: [] });

    await renderPage("member");

    expect(screen.getByText("No conversations yet")).toBeInTheDocument();
  });

  it("reports a failure to load the threads without blaming the reader", async () => {
    mockedConversations.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable.",
      status: 503,
    });

    await renderPage("member");

    expect(screen.getByText("The threads could not be loaded")).toBeInTheDocument();
  });

  it("shows an access notice instead of the page for a non-member", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "workspace_not_found",
      message: "The workspace does not exist.",
      status: 404,
    });

    render(
      await ConversationsPage({
        params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
        searchParams: Promise.resolve({}),
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Reference: workspace_not_found");
  });

  it("sends an expired session back to sign in, keeping the destination", async () => {
    mockedConversations.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));

    await expect(
      ConversationsPage({
        params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
        searchParams: Promise.resolve({}),
      }),
    ).rejects.toThrow(
      `NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}/conversations`,
    );
  });
});

describe("ConversationsLoading", () => {
  it("announces the load politely", () => {
    render(<ConversationsLoading />);

    expect(screen.getByText("Loading conversations")).toBeInTheDocument();
  });
});
