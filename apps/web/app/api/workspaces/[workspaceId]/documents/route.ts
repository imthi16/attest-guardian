/**
 * Upload proxy so the browser can show real upload progress.
 *
 * A server action cannot report bytes sent, so the upload form posts here with
 * `XMLHttpRequest` and watches its progress events. The handler is a relay, not
 * a second authorization point: the session cookie is exchanged for the bearer
 * token server side (the browser never holds one) and the API decides whether
 * the caller may upload, whether the bytes are what they claim to be, and
 * whether a quota allows them.
 *
 * It does carry two protections a server action would have given for free.
 *
 * Origin is checked, because `SameSite=Lax` scopes cookies by *site*, not by
 * origin: a script on a sibling origin under the same registrable domain can
 * send a credentialed cross-origin POST here, and without this check it would
 * spend the victim's workspace quota. Next.js applies the equivalent check to
 * server actions itself; a route handler has to do it explicitly.
 *
 * The body is bounded before it is parsed, because `request.formData()`
 * materializes the whole request in memory — checking `file.size` afterwards is
 * far too late to stop concurrent oversized requests from exhausting the
 * process.
 */
import { NextResponse, type NextRequest } from "next/server";

import { clientErrorCodes } from "../../../../../lib/contracts";
import { fetchUploadPolicy, uploadDocument } from "../../../../../lib/attest-api";
import { formatBytes } from "../../../../../lib/upload-rules";
import { SESSION_EXPIRED } from "../../../../../lib/session";

type RouteContext = Readonly<{ params: Promise<Readonly<{ workspaceId: string }>> }>;

/**
 * Slack for multipart boundaries, the filename, and headers around the file.
 * Generous on purpose: this bound only has to stop unbounded buffering, and
 * under-allowing here would reject a file the API would have accepted.
 */
const MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024;

function failure(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ detail: { code, message } }, { status });
}

/**
 * Whether the request came from this application's own origin.
 *
 * Compared against `Host` (or the proxy's `X-Forwarded-Host`) rather than a
 * configured URL, so the check keeps working behind a reverse proxy without a
 * second piece of deployment configuration to get wrong. A browser always sends
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

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { workspaceId } = await context.params;

  if (!isSameOrigin(request)) {
    return failure(403, clientErrorCodes.forbidden, "This request did not come from the app.");
  }

  // The deployment's real limit, not a compiled-in copy of the default: an
  // operator may raise or lower MAX_UPLOAD_BYTES, and relaying against a stale
  // constant would reject files the API accepts (or buffer ones it will not).
  const policy = await fetchUploadPolicy(workspaceId);
  if (!policy.ok) {
    const status = policy.code === SESSION_EXPIRED ? 401 : policy.status;
    return failure(status, policy.code, policy.message);
  }
  const maxUploadBytes = policy.data.max_upload_bytes;

  // A multipart envelope is larger than the file it carries, so this bound is
  // deliberately loose — it exists to cap memory, while the API remains the
  // authority on the file's own size.
  const declaredLength = Number(request.headers.get("content-length"));
  if (!Number.isFinite(declaredLength) || declaredLength <= 0) {
    return failure(411, clientErrorCodes.validation, "The upload needs a Content-Length.");
  }
  if (declaredLength > maxUploadBytes + MULTIPART_OVERHEAD_ALLOWANCE) {
    return failure(
      413,
      "file_too_large",
      `The file exceeds the ${formatBytes(maxUploadBytes)} upload limit.`,
    );
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return failure(400, clientErrorCodes.validation, "The upload could not be read.");
  }

  const file = form.get("file");
  if (!(file instanceof File)) {
    return failure(422, clientErrorCodes.validation, "Choose a file to upload.");
  }
  // The API enforces this too, but rejecting here avoids relaying a body that
  // is already known to be over the cap.
  if (file.size > maxUploadBytes) {
    return failure(
      413,
      "file_too_large",
      `The file exceeds the ${formatBytes(maxUploadBytes)} upload limit.`,
    );
  }

  const forwarded = new FormData();
  // Only the file is forwarded: the API derives the title from the validated
  // filename, so no client-supplied metadata rides along.
  forwarded.append("file", file, file.name);

  const result = await uploadDocument(workspaceId, forwarded);
  if (!result.ok) {
    const status = result.code === SESSION_EXPIRED ? 401 : result.status;
    return failure(status, result.code, result.message);
  }
  return NextResponse.json(result.data, { status: 201 });
}
