import { render, screen } from "@testing-library/react";

import ConversationPage from "./page";
import ConversationLoading from "./loading";
import {
  fetchConversation,
  fetchCurrentUser,
  fetchWorkspace,
} from "../../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../../lib/session";
import type { ConversationMessage, MembershipRole } from "../../../../../../lib/contracts";

vi.mock("../../../../../../lib/attest-api", () => ({
  fetchConversation: vi.fn(),
  fetchCurrentUser: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../../../auth-actions", () => ({ logoutAction: vi.fn() }));
vi.mock("../../../../../conversation-actions", () => ({
  deleteConversationAction: vi.fn(),
  resolveCitationAction: vi.fn(),
  submitFeedbackAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const mockedDetail = vi.mocked(fetchConversation);
const mockedUser = vi.mocked(fetchCurrentUser);
const mockedWorkspace = vi.mocked(fetchWorkspace);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";

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

const askedTurn: ConversationMessage = {
  id: "q1",
  role: "user",
  content: "When is payment due?",
  language: "eng",
  normalized_content: "when is payment due",
  transliterated_content: "when is payment due",
  answer_status: null,
  decision: null,
  decision_reason: null,
  confidence: null,
  abstention_reason: null,
  created_at: "2026-07-30T09:00:00Z",
  citations: [],
  claims: [],
};

function detailWith(messages: readonly ConversationMessage[]) {
  return {
    ok: true as const,
    data: {
      conversation: {
        id: CONVERSATION_ID,
        title: "Invoice terms",
        created_at: "2026-07-30T09:00:00Z",
        updated_at: "2026-07-30T09:30:00Z",
      },
      messages: [...messages],
    },
  };
}

async function renderPage(role: MembershipRole) {
  mockedWorkspace.mockResolvedValue(workspaceAs(role));
  render(
    await ConversationPage({
      params: Promise.resolve({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedDetail.mockResolvedValue(detailWith([askedTurn]));
});

describe("ConversationPage", () => {
  it("renders the thread and a composer for a member", async () => {
    await renderPage("member");

    expect(screen.getByRole("heading", { name: "Invoice terms" })).toBeInTheDocument();
    expect(screen.getByText("When is payment due?")).toBeInTheDocument();
    expect(screen.getByLabelText(/Ask a question/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All threads" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/conversations`,
    );
  });

  it("says the input understands Tamil and Tanglish", async () => {
    await renderPage("member");

    expect(screen.getByText(/Tamil, Tanglish, and English/)).toBeInTheDocument();
  });

  it("gives a viewer the thread but no composer or delete control", async () => {
    await renderPage("viewer");

    expect(screen.queryByLabelText(/Ask a question/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete this thread/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("only members, admins, and owners");
  });

  it("prompts for a first question on an empty thread", async () => {
    mockedDetail.mockResolvedValue(detailWith([]));

    await renderPage("member");

    expect(screen.getByText("Nothing asked yet")).toBeInTheDocument();
  });

  it("labels an untitled thread", async () => {
    mockedDetail.mockResolvedValue({
      ok: true,
      data: {
        ...detailWith([]).data,
        conversation: { ...detailWith([]).data.conversation, title: null },
      },
    });

    await renderPage("member");

    expect(screen.getByRole("heading", { name: "Untitled thread" })).toBeInTheDocument();
  });

  it("shows an access notice for a thread that is not there", async () => {
    mockedDetail.mockResolvedValue({
      ok: false,
      code: "conversation_not_found",
      message: "The conversation does not exist in this workspace.",
      status: 404,
    });

    await renderPage("member");

    expect(screen.getByRole("alert")).toHaveTextContent("Reference: conversation_not_found");
  });

  it("shows an access notice instead of the page for a non-member", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "workspace_not_found",
      message: "The workspace does not exist.",
      status: 404,
    });

    render(
      await ConversationPage({
        params: Promise.resolve({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Reference: workspace_not_found");
  });

  it("sends an expired session back to sign in, keeping the destination", async () => {
    mockedDetail.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));

    await expect(
      ConversationPage({
        params: Promise.resolve({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
      }),
    ).rejects.toThrow(
      `NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}/conversations/${CONVERSATION_ID}`,
    );
  });
});

describe("ConversationLoading", () => {
  it("announces the load politely", () => {
    render(<ConversationLoading />);

    expect(screen.getByText("Loading conversation")).toBeInTheDocument();
  });
});
