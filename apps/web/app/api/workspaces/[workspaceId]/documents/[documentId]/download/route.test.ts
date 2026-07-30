import { GET } from "./route";
import { requestDownloadLink } from "../../../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../../../lib/session";
import type { NextRequest } from "next/server";

vi.mock("../../../../../../../lib/attest-api", () => ({ requestDownloadLink: vi.fn() }));

const mockedLink = vi.mocked(requestDownloadLink);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "44444444-4444-4444-8444-444444444444";
const PRESIGNED = "http://127.0.0.1:9000/attest-documents/key?X-Amz-Signature=abc";

const request = {
  nextUrl: new URL("http://localhost:3000/api/download"),
} as unknown as NextRequest;

const context = {
  params: Promise.resolve({ documentId: DOCUMENT_ID, workspaceId: WORKSPACE_ID }),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET .../documents/[documentId]/download", () => {
  it("redirects to a freshly minted presigned URL and forbids caching it", async () => {
    mockedLink.mockResolvedValue({ ok: true, data: { url: PRESIGNED, expires_in_seconds: 300 } });

    const response = await GET(request, context);

    expect(mockedLink).toHaveBeenCalledWith(WORKSPACE_ID, DOCUMENT_ID);
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(PRESIGNED);
    // The target expires, so a cached redirect would break the next download.
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("relays a refusal with its stable code instead of a broken redirect", async () => {
    mockedLink.mockResolvedValue({
      ok: false,
      code: "document_not_found",
      message: "The document does not exist in this workspace.",
      status: 404,
    });

    const response = await GET(request, context);

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      detail: {
        code: "document_not_found",
        message: "The document does not exist in this workspace.",
      },
    });
  });

  it("sends an expired session to sign in, keeping the destination", async () => {
    mockedLink.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });

    const response = await GET(request, context);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      `http://localhost:3000/login?expired=1&next=/workspaces/${WORKSPACE_ID}/documents/${DOCUMENT_ID}`,
    );
  });
});
