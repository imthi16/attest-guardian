import { POST } from "./route";
import { SESSION_EXPIRED, authorizedStream } from "../../../../../../../lib/session";
import type { NextRequest } from "next/server";

vi.mock("../../../../../../../lib/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../../../../../lib/session")>();
  return { ...actual, authorizedStream: vi.fn() };
});

const mockedStream = vi.mocked(authorizedStream);

const APP_HOST = "attest.example";
const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";

const context = {
  params: Promise.resolve({ conversationId: CONVERSATION_ID, workspaceId: WORKSPACE_ID }),
};

/** A body delivered as one or more chunks, like a real request stream. */
function streamOf(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

function request(
  body: unknown,
  overrides: Readonly<{
    /** Omitted entirely by a proxy using chunked transfer or HTTP/2 framing. */
    contentLength?: string | null;
    chunks?: readonly string[];
    host?: string;
    origin?: string | null;
  }> = {},
): NextRequest {
  const headers = new Map<string, string>();
  const origin = overrides.origin === undefined ? `https://${APP_HOST}` : overrides.origin;
  if (origin !== null) {
    headers.set("origin", origin);
  }
  headers.set("host", overrides.host ?? APP_HOST);
  // `body === undefined` stands for a body that is not JSON at all.
  const chunks = overrides.chunks ?? [body === undefined ? "not json" : JSON.stringify(body)];
  const length =
    overrides.contentLength === undefined
      ? String(chunks.join("").length)
      : overrides.contentLength;
  if (length !== null) {
    headers.set("content-length", length);
  }
  return {
    body: streamOf(chunks),
    headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
  } as unknown as NextRequest;
}

function sseResponse(): Response {
  return new Response('event: stage\ndata: {"stage":"retrieve"}\n\n', { status: 200 });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST .../conversations/[conversationId]/stream", () => {
  it("relays the question and streams the API's own events back", async () => {
    mockedStream.mockResolvedValue({ ok: true, response: sseResponse() });

    const response = await POST(request({ question: "When is payment due?" }), context);

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    // Answers are tenant content: never cached, never proxy-buffered.
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toContain('"stage":"retrieve"');
    expect(mockedStream).toHaveBeenCalledWith({
      body: { document_id: null, question: "When is payment due?" },
      path: `/workspaces/${WORKSPACE_ID}/conversations/${CONVERSATION_ID}/messages/stream`,
    });
  });

  it("forwards a document filter when one is given", async () => {
    mockedStream.mockResolvedValue({ ok: true, response: sseResponse() });

    await POST(request({ documentId: "doc-1", question: "anything" }), context);

    expect(mockedStream.mock.calls[0][0].body).toEqual({
      document_id: "doc-1",
      question: "anything",
    });
  });

  it("refuses a cross-origin request even with a valid session cookie", async () => {
    // SameSite=Lax scopes the cookie to the site, not the origin, so a sibling
    // origin could otherwise spend this workspace's answering budget.
    const response = await POST(
      request({ question: "anything" }, { origin: "https://evil.attest.example" }),
      context,
    );

    expect(response.status).toBe(403);
    expect(mockedStream).not.toHaveBeenCalled();
  });

  it("refuses a request that sends no Origin at all", async () => {
    const response = await POST(request({ question: "anything" }, { origin: null }), context);

    expect(response.status).toBe(403);
    expect(mockedStream).not.toHaveBeenCalled();
  });

  it("accepts the proxy's forwarded host as the app origin", async () => {
    mockedStream.mockResolvedValue({ ok: true, response: sseResponse() });
    const headers = new Map([
      ["origin", "https://public.example"],
      ["host", "internal:3000"],
      ["x-forwarded-host", "public.example"],
      ["content-length", "32"],
    ]);
    const proxied = {
      body: streamOf(['{"question":"anything"}']),
      headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
    } as unknown as NextRequest;

    expect((await POST(proxied, context)).status).toBe(200);
  });

  it("rejects an empty or over-long question before relaying it", async () => {
    expect((await POST(request({ question: "   " }), context)).status).toBe(422);
    expect((await POST(request({}), context)).status).toBe(422);
    expect((await POST(request({ question: "x".repeat(2001) }), context)).status).toBe(422);
    expect(mockedStream).not.toHaveBeenCalled();
  });

  it("rejects a body that is not JSON", async () => {
    expect((await POST(request(undefined), context)).status).toBe(400);
  });

  it("refuses an oversized body on its declared length alone", async () => {
    // The length checks above run only after the whole body is in the process,
    // so the bound has to come first: a forged Origin is enough to reach this
    // line without a session.
    const response = await POST(
      request({ question: "anything" }, { contentLength: String(1024 * 1024) }),
      context,
    );

    expect(response.status).toBe(413);
    expect(mockedStream).not.toHaveBeenCalled();
  });

  it("stops reading a body that lies about its length", async () => {
    // A declared length is a claim, not a fact. The bytes are counted as they
    // arrive and the rest of the stream is cancelled rather than allocated.
    const cancelled = vi.fn();
    const encoder = new TextEncoder();
    // Never ends on its own: only the byte count can stop it.
    const body = new ReadableStream<Uint8Array>({
      cancel: cancelled,
      pull(controller) {
        controller.enqueue(encoder.encode("x".repeat(32 * 1024)));
      },
    });
    const lying = {
      body,
      headers: {
        get: (name: string) =>
          ({ "content-length": "12", host: APP_HOST, origin: `https://${APP_HOST}` })[
            name.toLowerCase()
          ] ?? null,
      },
    } as unknown as NextRequest;

    expect((await POST(lying, context)).status).toBe(413);
    expect(mockedStream).not.toHaveBeenCalled();
    // Cancelled rather than drained: this body never ends by itself, so the
    // request returning at all is the proof, and the rest is never allocated.
    expect(cancelled).toHaveBeenCalled();
  });

  it("accepts a proxied body that declares no length at all", async () => {
    // HTTP/2 framing and chunked transfer encoding both delimit a body without
    // `Content-Length`, and this route is explicitly meant to work behind a
    // proxy — refusing them would reject every question in such a deployment.
    mockedStream.mockResolvedValue({ ok: true, response: sseResponse() });

    const response = await POST(
      request({ question: "anything" }, { contentLength: null }),
      context,
    );

    expect(response.status).toBe(200);
    expect(mockedStream.mock.calls[0][0].body).toEqual({
      document_id: null,
      question: "anything",
    });
  });

  it("reassembles a body split across chunks", async () => {
    mockedStream.mockResolvedValue({ ok: true, response: sseResponse() });

    await POST(request(null, { chunks: ['{"question":"When is ', 'payment due?"}'] }), context);

    expect(mockedStream.mock.calls[0][0].body).toEqual({
      document_id: null,
      question: "When is payment due?",
    });
  });

  it("passes the API's refusal through with its stable code", async () => {
    mockedStream.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: 403,
    });

    const response = await POST(request({ question: "anything" }), context);

    expect(response.status).toBe(403);
    expect((await response.json()).detail.code).toBe("insufficient_role");
  });

  it("reports an expired session as 401 so the browser can restart sign-in", async () => {
    mockedStream.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired. Please sign in again.",
      status: 401,
    });

    expect((await POST(request({ question: "anything" }), context)).status).toBe(401);
  });
});
