import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { QuestionComposer, parseFrames } from "./question-composer";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";

/** An SSE body delivered as one or more chunks, like a real stream. */
function streamOf(chunks: readonly string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": "text/event-stream" }, status: 200 });
}

function frame(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function renderComposer() {
  render(<QuestionComposer conversationId={CONVERSATION_ID} workspaceId={WORKSPACE_ID} />);
}

async function ask(question: string): Promise<void> {
  await userEvent.type(screen.getByLabelText(/Ask a question/), question);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseFrames", () => {
  it("returns whole frames and keeps a partial one buffered", () => {
    const { events, rest } = parseFrames(
      `${frame("stage", { stage: "retrieve" })}event: stage\ndata: {"stage":"gen`,
    );

    expect(events).toEqual([{ data: '{"stage":"retrieve"}', name: "stage" }]);
    // A frame still arriving must not be parsed as if it were complete.
    expect(rest).toBe('event: stage\ndata: {"stage":"gen');
  });

  it("ignores frames with no event name", () => {
    expect(parseFrames(": keep-alive\n\n").events).toEqual([]);
  });
});

describe("QuestionComposer", () => {
  it("reports each real stage and then refreshes to the stored thread", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        streamOf([
          frame("stage", { stage: "authorize" }),
          frame("stage", { stage: "retrieve" }),
          frame("stage", { stage: "verify" }),
          frame("answer", { message_id: "m1", outcome: "answered" }),
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);
    renderComposer();

    await ask("When is payment due?");

    // The answer is not painted from local state: the server-rendered thread is
    // the authority on what was actually stored.
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(
      `/api/workspaces/${WORKSPACE_ID}/conversations/${CONVERSATION_ID}/stream`,
    );
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      question: "When is payment due?",
    });
  });

  it("shows a progress message drawn from the pipeline's own stage", async () => {
    const release: { current: (() => void) | null } = { current: null };
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame("stage", { stage: "retrieve" })));
        release.current = () => controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    renderComposer();

    await ask("anything");

    expect(await screen.findByText("Searching your documents…")).toBeInTheDocument();
    release.current?.();
  });

  it("refuses an empty question without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderComposer();

    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Type a question first.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces a pipeline failure sent as an error event", async () => {
    // The status is already 200 by then, so the failure has to arrive in-band.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamOf([
          frame("stage", { stage: "retrieve" }),
          frame("error", {
            code: "answer_failed",
            message: "The answer could not be completed.",
          }),
        ]),
      ),
    );
    renderComposer();

    await ask("anything");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The answer could not be completed.");
    expect(alert).toHaveTextContent("Reference: answer_failed");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("relays a refusal made before streaming started", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: "insufficient_role", message: "Your role does not allow this." },
          }),
          { status: 403 },
        ),
      ),
    );
    renderComposer();

    await ask("anything");

    expect(await screen.findByRole("alert")).toHaveTextContent("Reference: insufficient_role");
  });

  it("sends an expired session back to sign in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 401 })),
    );
    renderComposer();

    await ask("anything");

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        `/login?expired=1&next=/workspaces/${WORKSPACE_ID}/conversations`,
      );
    });
  });

  it("cancelling stops the request and reports nothing", async () => {
    // The API persists an answer only from a terminal result, so an abandoned
    // question must not leave an error on screen either.
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frame("stage", { stage: "retrieve" })));
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    renderComposer();

    await ask("anything");
    await screen.findByText("Searching your documents…");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  });

  it("reports an unreachable service", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderComposer();

    await ask("anything");

    expect(await screen.findByRole("alert")).toHaveTextContent("The service is unreachable");
  });
});
