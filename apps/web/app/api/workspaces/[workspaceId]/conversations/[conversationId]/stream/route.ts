/**
 * Streaming relay so the browser can watch an answer being built.
 *
 * A server action returns once and cannot stream, so asking a question with
 * live progress has to go through a route handler. This is a relay, not a second
 * authorization point: the session cookie is exchanged for a bearer token server
 * side (the browser never holds one) and the API decides whether the caller may
 * ask, which evidence they may see, and what the answer is.
 *
 * `Origin` is verified for the same reason as the upload relay: `SameSite=Lax`
 * scopes the session cookie by *site*, not by origin, so a script on a sibling
 * origin could otherwise post here credentialed and spend the workspace's
 * answering budget. Next.js applies the equivalent check to server actions
 * itself; a route handler has to make it explicitly.
 *
 * The *response* body is piped through untouched. Buffering it would defeat the
 * point, and re-encoding events would risk this relay disagreeing with the API
 * about what the answer was. The *request* body is the opposite case: it is
 * bounded before it is read, because reading it is what allocates it.
 */
import { NextResponse, type NextRequest } from "next/server";

import { clientErrorCodes } from "../../../../../../../lib/contracts";
import { SESSION_EXPIRED, authorizedStream } from "../../../../../../../lib/session";

type RouteContext = Readonly<{
  params: Promise<Readonly<{ conversationId: string; workspaceId: string }>>;
}>;

/** A question long enough to be abusive is refused before it is relayed. */
const MAX_QUESTION_LENGTH = 2000;

/**
 * The largest JSON envelope a legitimate question can arrive in.
 *
 * `request.json()` buffers the whole body before anything in it can be
 * inspected, so the length checks below are useless as a memory bound — by the
 * time they run the bytes are already in the process. Generous enough for a
 * maximum-length question escaped character by character plus its surrounding
 * object.
 */
const MAX_BODY_BYTES = 64 * 1024;

function failure(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ detail: { code, message } }, { status });
}

/**
 * Read the body, stopping the moment it exceeds `MAX_BODY_BYTES`.
 *
 * Counted while reading rather than taken from `Content-Length`, because that
 * header is optional: a proxy forwarding over HTTP/2, or with chunked transfer
 * encoding, delimits the body without it, and this route is explicitly meant to
 * work behind a proxy. Refusing a headerless request would reject every question
 * in such a deployment; trusting the header instead would let a caller declare
 * one size and send another. The declared length is still honoured as a cheap
 * pre-filter, so an obviously oversized request costs nothing to reject.
 *
 * Returns `null` when the body is too large — the stream is cancelled at that
 * point, so the rest is never allocated.
 */
async function readBoundedBody(request: NextRequest): Promise<string | null> {
  if (Number(request.headers.get("content-length")) > MAX_BODY_BYTES) {
    return null;
  }
  const body = request.body;
  if (body === null) {
    return "";
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}

/**
 * Whether the request came from this application's own origin.
 *
 * Compared against `Host` (or the proxy's `X-Forwarded-Host`) rather than a
 * configured URL, so it keeps working behind a reverse proxy without a second
 * piece of deployment configuration to get wrong. A browser always sends
 * `Origin` on a cross-origin POST, so a missing header is rejected rather than
 * assumed same-origin.
 */
function isSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin === null) {
    return false;
  }
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (host === null) {
    return false;
  }
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  const { conversationId, workspaceId } = await context.params;

  if (!isSameOrigin(request)) {
    return failure(403, clientErrorCodes.forbidden, "This request did not come from the app.");
  }

  // Bounded as it is read: an unauthenticated caller that forges the `Origin`
  // header reaches this line, and `request.json()` would otherwise pull an
  // arbitrarily large object into the Next.js process before `authorizedStream`
  // ever checks the session.
  const raw = await readBoundedBody(request);
  if (raw === null) {
    return failure(413, clientErrorCodes.validation, "That question is too long.");
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return failure(400, clientErrorCodes.validation, "The question could not be read.");
  }
  const question = (payload as { question?: unknown } | null)?.question;
  if (typeof question !== "string" || question.trim() === "") {
    return failure(422, clientErrorCodes.validation, "Type a question first.");
  }
  if (question.length > MAX_QUESTION_LENGTH) {
    return failure(422, clientErrorCodes.validation, "That question is too long.");
  }
  const documentId = (payload as { documentId?: unknown } | null)?.documentId;

  const opened = await authorizedStream({
    body: {
      document_id: typeof documentId === "string" && documentId !== "" ? documentId : null,
      question,
    },
    path: `/workspaces/${encodeURIComponent(workspaceId)}/conversations/${encodeURIComponent(conversationId)}/messages/stream`,
  });
  if (!opened.ok) {
    const status = opened.code === SESSION_EXPIRED ? 401 : opened.status;
    return failure(status, opened.code, opened.message);
  }

  return new Response(opened.response.body, {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/event-stream",
      // Answers are tenant content; an intermediary that buffered them would
      // both leak them into a cache and defeat the streaming.
      "X-Accel-Buffering": "no",
    },
    status: 200,
  });
}
