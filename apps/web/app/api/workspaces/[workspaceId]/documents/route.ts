/**
 * Upload proxy so the browser can show real upload progress.
 *
 * A server action cannot report bytes sent, so the upload form posts here with
 * `XMLHttpRequest` and watches its progress events. The handler is a relay, not
 * a second authorization point: the session cookie is exchanged for the bearer
 * token server side (the browser never holds one) and the API decides whether
 * the caller may upload, whether the bytes are what they claim to be, and
 * whether a quota allows them. Only same-origin requests carry the SameSite=Lax
 * session cookie, which is what keeps a cross-site page from posting here.
 */
import { NextResponse, type NextRequest } from "next/server";

import { clientErrorCodes } from "../../../../../lib/contracts";
import { uploadDocument } from "../../../../../lib/attest-api";
import { MAX_UPLOAD_BYTES, formatBytes } from "../../../../../lib/upload-rules";
import { SESSION_EXPIRED } from "../../../../../lib/session";

type RouteContext = Readonly<{ params: Promise<Readonly<{ workspaceId: string }>> }>;

function failure(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ detail: { code, message } }, { status });
}

export async function POST(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { workspaceId } = await context.params;

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
  if (file.size > MAX_UPLOAD_BYTES) {
    return failure(
      413,
      "file_too_large",
      `The file exceeds the ${formatBytes(MAX_UPLOAD_BYTES)} upload limit.`,
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
