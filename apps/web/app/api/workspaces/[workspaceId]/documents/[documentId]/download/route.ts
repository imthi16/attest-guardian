/**
 * Download redirect: mints a presigned URL at click time and forwards to it.
 *
 * A link navigation is used rather than a server action so the redirect is not
 * a form target — the CSP's `form-action 'self'` would refuse that — and so the
 * download still works without client JavaScript. The presigned URL is never
 * rendered into a page, so it cannot be scraped from HTML or survive in a
 * cached document; the API authorizes the caller and audits every link it
 * issues. Responses are marked no-store because the redirect target expires.
 */
import { NextResponse, type NextRequest } from "next/server";

import { requestDownloadLink } from "../../../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../../../lib/session";

type RouteContext = Readonly<{
  params: Promise<Readonly<{ documentId: string; workspaceId: string }>>;
}>;

export async function GET(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { documentId, workspaceId } = await context.params;
  const link = await requestDownloadLink(workspaceId, documentId);

  if (!link.ok) {
    if (link.code === SESSION_EXPIRED) {
      return NextResponse.redirect(
        new URL(
          `/login?expired=1&next=/workspaces/${workspaceId}/documents/${documentId}`,
          request.nextUrl.origin,
        ),
      );
    }
    return NextResponse.json(
      { detail: { code: link.code, message: link.message } },
      { headers: { "Cache-Control": "no-store" }, status: link.status },
    );
  }

  return NextResponse.redirect(link.data.url, {
    headers: { "Cache-Control": "no-store" },
    status: 303,
  });
}
