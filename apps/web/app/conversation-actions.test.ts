import {
  deleteConversationAction,
  resolveCitationAction,
  startConversationAction,
  submitFeedbackAction,
} from "./conversation-actions";
import {
  createConversation,
  deleteConversation,
  resolveCitation,
  submitFeedback,
} from "../lib/attest-api";
import { SESSION_EXPIRED } from "../lib/session";

vi.mock("../lib/attest-api", () => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  resolveCitation: vi.fn(),
  submitFeedback: vi.fn(),
}));

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

class RedirectError extends Error {
  constructor(public readonly destination: string) {
    super(`NEXT_REDIRECT:${destination}`);
  }
}

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new RedirectError(destination);
  },
}));

const mockedCreate = vi.mocked(createConversation);
const mockedDelete = vi.mocked(deleteConversation);
const mockedResolve = vi.mocked(resolveCitation);
const mockedFeedback = vi.mocked(submitFeedback);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";
const MESSAGE_ID = "33333333-3333-4333-8333-333333333333";
const idle = { status: "idle" } as const;

const conversation = {
  id: CONVERSATION_ID,
  title: "Invoice terms",
  created_at: "2026-07-30T09:00:00Z",
  updated_at: "2026-07-30T09:00:00Z",
};

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function expectRedirect(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof RedirectError) {
      return error.destination;
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("startConversationAction", () => {
  it("starts a thread and goes to it", async () => {
    mockedCreate.mockResolvedValue({ ok: true, data: conversation });

    const destination = await expectRedirect(
      startConversationAction(
        idle,
        formData({ title: "Invoice terms", workspaceId: WORKSPACE_ID }),
      ),
    );

    expect(mockedCreate).toHaveBeenCalledWith(WORKSPACE_ID, "Invoice terms");
    expect(destination).toBe(`/workspaces/${WORKSPACE_ID}/conversations/${CONVERSATION_ID}`);
  });

  it("treats an omitted title as untitled rather than an empty string", async () => {
    mockedCreate.mockResolvedValue({ ok: true, data: { ...conversation, title: null } });

    await expectRedirect(startConversationAction(idle, formData({ workspaceId: WORKSPACE_ID })));

    expect(mockedCreate).toHaveBeenCalledWith(WORKSPACE_ID, null);
  });

  it("relays a refusal with its stable code", async () => {
    mockedCreate.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: 403,
    });

    const state = await startConversationAction(idle, formData({ workspaceId: WORKSPACE_ID }));

    expect(state.code).toBe("insufficient_role");
    expect(state.status).toBe("error");
  });

  it("rejects a malformed workspace id before calling the API", async () => {
    const state = await startConversationAction(idle, formData({ workspaceId: "nope" }));

    expect(state.fieldErrors?.workspaceId).toBe("Select a valid workspace.");
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("restarts sign-in when the session has expired", async () => {
    mockedCreate.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });

    expect(
      await expectRedirect(startConversationAction(idle, formData({ workspaceId: WORKSPACE_ID }))),
    ).toBe("/login?expired=1");
  });
});

describe("deleteConversationAction", () => {
  it("returns to the list with an explicit confirmation", async () => {
    mockedDelete.mockResolvedValue({ ok: true, data: null });

    const destination = await expectRedirect(
      deleteConversationAction(
        idle,
        formData({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
      ),
    );

    expect(destination).toBe(`/workspaces/${WORKSPACE_ID}/conversations?deleted=1`);
  });

  it("stays put and explains when the API refuses", async () => {
    mockedDelete.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Only the author or an admin can delete this thread.",
      status: 403,
    });

    const state = await deleteConversationAction(
      idle,
      formData({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
    );

    expect(state.code).toBe("insufficient_role");
  });
});

describe("submitFeedbackAction", () => {
  const feedback = {
    id: "44444444-4444-4444-8444-444444444444",
    message_id: MESSAGE_ID,
    rating: "helpful" as const,
    note: null,
    created_at: "2026-07-30T09:00:00Z",
    updated_at: "2026-07-30T09:00:00Z",
  };

  it("records a verdict with its note", async () => {
    mockedFeedback.mockResolvedValue({ ok: true, data: feedback });

    const state = await submitFeedbackAction(
      idle,
      formData({
        conversationId: CONVERSATION_ID,
        messageId: MESSAGE_ID,
        note: "Missed the renewal clause.",
        rating: "incorrect",
        workspaceId: WORKSPACE_ID,
      }),
    );

    expect(mockedFeedback).toHaveBeenCalledWith(WORKSPACE_ID, CONVERSATION_ID, MESSAGE_ID, {
      note: "Missed the renewal clause.",
      rating: "incorrect",
    });
    expect(state.status).toBe("success");
    expect(state.message).toContain("recorded");
  });

  it("sends no note when none was written", async () => {
    mockedFeedback.mockResolvedValue({ ok: true, data: feedback });

    await submitFeedbackAction(
      idle,
      formData({
        conversationId: CONVERSATION_ID,
        messageId: MESSAGE_ID,
        note: "",
        rating: "helpful",
        workspaceId: WORKSPACE_ID,
      }),
    );

    expect(mockedFeedback).toHaveBeenCalledWith(WORKSPACE_ID, CONVERSATION_ID, MESSAGE_ID, {
      note: null,
      rating: "helpful",
    });
  });

  it("rejects a rating the API does not define", async () => {
    const state = await submitFeedbackAction(
      idle,
      formData({
        conversationId: CONVERSATION_ID,
        messageId: MESSAGE_ID,
        rating: "excellent",
        workspaceId: WORKSPACE_ID,
      }),
    );

    expect(state.status).toBe("error");
    expect(mockedFeedback).not.toHaveBeenCalled();
  });

  it("surfaces the API refusing feedback on a question", async () => {
    mockedFeedback.mockResolvedValue({
      ok: false,
      code: "feedback_requires_answer",
      message: "Feedback can only be recorded for an answer.",
      status: 409,
    });

    const state = await submitFeedbackAction(
      idle,
      formData({
        conversationId: CONVERSATION_ID,
        messageId: MESSAGE_ID,
        rating: "helpful",
        workspaceId: WORKSPACE_ID,
      }),
    );

    expect(state.code).toBe("feedback_requires_answer");
  });
});

describe("resolveCitationAction", () => {
  const reference = {
    chunk_id: MESSAGE_ID,
    document_version_id: CONVERSATION_ID,
    quote: "due within thirty days",
    quote_char_end: 45,
    quote_char_start: 23,
  };

  it("returns the proven citation", async () => {
    mockedResolve.mockResolvedValue({
      ok: true,
      data: { supporting_text: "…" } as never,
    });

    const resolution = await resolveCitationAction(WORKSPACE_ID, reference);

    expect(resolution.ok).toBe(true);
    expect(mockedResolve).toHaveBeenCalledWith(WORKSPACE_ID, reference);
  });

  it("relays a citation that does not match its source", async () => {
    mockedResolve.mockResolvedValue({
      ok: false,
      code: "citation_out_of_range",
      message: "The quoted span is outside the cited chunk.",
      status: 422,
    });

    const resolution = await resolveCitationAction(WORKSPACE_ID, reference);

    expect(resolution).toEqual({
      code: "citation_out_of_range",
      message: "The quoted span is outside the cited chunk.",
      ok: false,
    });
  });

  it("restarts sign-in when the session has expired", async () => {
    mockedResolve.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });

    expect(await expectRedirect(resolveCitationAction(WORKSPACE_ID, reference))).toBe(
      "/login?expired=1",
    );
  });
});
