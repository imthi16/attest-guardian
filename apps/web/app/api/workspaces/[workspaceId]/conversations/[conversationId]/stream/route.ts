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
 * The body is piped through untouched. Buffering it would defeat the point, and
 * re-encoding events would risk this relay disagreeing with the API about what
 * the answer was.
 */
import { NextResponse, type NextRequest } from "next/server";

import { clientErrorCodes } from "../../../../../../../lib/contracts";
import { SESSION_EXPIRED, authorizedStream } from "../../../../../../../lib/session";

type RouteContext = Readonly<{
  params: Promise<Readonly<{ conversationId: string; workspaceId: string }>>;
}>;

/** A question long enough to be abusive is refused before it is relayed. */
const MAX_QUESTION_LENGTH = 2000;

function failure(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ detail: { code, message } }, { status });
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

  let payload: unknown;
  try {
    payload = await request.json();
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
