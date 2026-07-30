import { POST } from "./route";
import { fetchUploadPolicy, uploadDocument } from "../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../lib/session";
import { DEFAULT_MAX_UPLOAD_BYTES } from "../../../../../lib/upload-rules";
import type { NextRequest } from "next/server";

vi.mock("../../../../../lib/attest-api", () => ({
  fetchUploadPolicy: vi.fn(),
  uploadDocument: vi.fn(),
}));

const mockedUpload = vi.mocked(uploadDocument);
const mockedPolicy = vi.mocked(fetchUploadPolicy);

const APP_HOST = "attest.example";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

const accepted = {
  id: "44444444-4444-4444-8444-444444444444",
  title: "lease.pdf",
  source_filename: "lease.pdf",
  mime_type: "application/pdf",
  size_bytes: 12,
  sha256: "a".repeat(64),
  status: "pending" as const,
  created_at: "2026-07-29T10:00:00Z",
  archived_at: null,
  retryable: false,
};

/**
 * A same-origin multipart POST. `Origin`/`Host` and `Content-Length` are set
 * because the relay checks both before it parses anything.
 */
function fileRequest(
  entries: Array<[string, FormDataEntryValue]>,
  overrides: Readonly<{
    contentLength?: string | null;
    host?: string;
    origin?: string | null;
  }> = {},
): NextRequest {
  const form = new FormData();
  for (const [key, value] of entries) {
    form.set(key, value);
  }
  const declared =
    overrides.contentLength === undefined
      ? String(
          entries.reduce(
            (total, [, value]) => total + (value instanceof File ? value.size : 0),
            1024,
          ),
        )
      : overrides.contentLength;
  const headers = new Map<string, string>();
  const origin = overrides.origin === undefined ? `https://${APP_HOST}` : overrides.origin;
  if (origin !== null) {
    headers.set("origin", origin);
  }
  headers.set("host", overrides.host ?? APP_HOST);
  if (declared !== null) {
    headers.set("content-length", declared);
  }
  return {
    formData: async () => form,
    headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
  } as unknown as NextRequest;
}

function pdf(size = 12): File {
  const file = new File(["%PDF-1.7 xx"], "lease.pdf", { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

const context = { params: Promise.resolve({ workspaceId: WORKSPACE_ID }) };

beforeEach(() => {
  vi.clearAllMocks();
  mockedPolicy.mockResolvedValue({
    ok: true,
    data: {
      max_upload_bytes: DEFAULT_MAX_UPLOAD_BYTES,
      max_filename_length: 255,
      accepted_extensions: [".pdf", ".txt"],
    },
  });
});

describe("POST /api/workspaces/[workspaceId]/documents", () => {
  it("relays only the file, so no client metadata rides along", async () => {
    mockedUpload.mockResolvedValue({ ok: true, data: accepted });

    const response = await POST(
      fileRequest([
        ["file", pdf()],
        // A client-chosen title would end up as tenant content the API never
        // validated, so the relay drops anything but the file itself.
        ["title", "attacker-chosen title"],
      ]),
      context,
    );

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(accepted);
    const [workspaceId, forwarded] = mockedUpload.mock.calls[0];
    expect(workspaceId).toBe(WORKSPACE_ID);
    expect(forwarded.get("title")).toBeNull();
    expect(forwarded.get("file")).toBeInstanceOf(File);
  });

  it("rejects an oversized body before relaying it", async () => {
    const response = await POST(
      fileRequest([["file", pdf(DEFAULT_MAX_UPLOAD_BYTES + 1)]], {
        // Under the header bound, so this is the post-parse size check.
        contentLength: String(DEFAULT_MAX_UPLOAD_BYTES + 1),
      }),
      context,
    );

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({
      detail: { code: "file_too_large", message: expect.stringContaining("upload limit") },
    });
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("rejects an oversized body without parsing it at all", async () => {
    // The point of the header check: formData() would materialize the whole
    // body in memory, so a declared-oversize request must never reach it.
    const parse = vi.fn();
    const request = fileRequest([["file", pdf()]], {
      contentLength: String(DEFAULT_MAX_UPLOAD_BYTES * 10),
    });
    (request as unknown as { formData: unknown }).formData = parse;

    const response = await POST(request, context);

    expect(response.status).toBe(413);
    expect(parse).not.toHaveBeenCalled();
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("refuses a body that declares no length", async () => {
    const response = await POST(fileRequest([["file", pdf()]], { contentLength: null }), context);

    expect(response.status).toBe(411);
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("refuses a cross-origin upload even with a valid session cookie", async () => {
    // SameSite=Lax scopes the cookie to the site, not the origin, so a sibling
    // origin can post here credentialed. Server actions get this check for
    // free; a route handler has to make it.
    const response = await POST(
      fileRequest([["file", pdf()]], { origin: "https://evil.attest.example" }),
      context,
    );

    expect(response.status).toBe(403);
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("refuses an upload that sends no Origin at all", async () => {
    const response = await POST(fileRequest([["file", pdf()]], { origin: null }), context);

    expect(response.status).toBe(403);
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("accepts the proxy's forwarded host as the app origin", async () => {
    mockedUpload.mockResolvedValue({ ok: true, data: accepted });
    const request = fileRequest([["file", pdf()]], { origin: "https://public.example" });
    const headers = new Map([
      ["origin", "https://public.example"],
      ["host", "internal:3000"],
      ["x-forwarded-host", "public.example"],
      ["content-length", "2048"],
    ]);
    (request as unknown as { headers: unknown }).headers = {
      get: (name: string) => headers.get(name.toLowerCase()) ?? null,
    };

    const response = await POST(request, context);

    expect(response.status).toBe(201);
  });

  it("uses the deployment's raised limit rather than the compiled default", async () => {
    mockedUpload.mockResolvedValue({ ok: true, data: accepted });
    mockedPolicy.mockResolvedValue({
      ok: true,
      data: {
        max_upload_bytes: DEFAULT_MAX_UPLOAD_BYTES * 4,
        max_filename_length: 255,
        accepted_extensions: [".pdf"],
      },
    });

    const oversizeForDefault = DEFAULT_MAX_UPLOAD_BYTES + 1;
    const response = await POST(
      fileRequest([["file", pdf(oversizeForDefault)]], {
        contentLength: String(oversizeForDefault),
      }),
      context,
    );

    expect(response.status).toBe(201);
  });

  it("rejects a request with no file", async () => {
    const response = await POST(fileRequest([["title", "no file here"]]), context);

    expect(response.status).toBe(422);
    expect((await response.json()).detail.code).toBe("invalid_input");
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("rejects a body that is not multipart form data", async () => {
    const broken = fileRequest([["file", pdf()]]);
    (broken as unknown as { formData: unknown }).formData = async () => {
      throw new TypeError("not multipart");
    };

    const response = await POST(broken, context);

    expect(response.status).toBe(400);
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("passes the API's refusal through with its stable code", async () => {
    mockedUpload.mockResolvedValue({
      ok: false,
      code: "content_mismatch",
      message: "The file's contents are not a PDF.",
      status: 422,
    });

    const response = await POST(fileRequest([["file", pdf()]]), context);

    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({
      detail: { code: "content_mismatch", message: "The file's contents are not a PDF." },
    });
  });

  it("reports an expired session as 401 so the browser can restart sign-in", async () => {
    mockedUpload.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired. Please sign in again.",
      status: 401,
    });

    const response = await POST(fileRequest([["file", pdf()]]), context);

    expect(response.status).toBe(401);
  });

  it("refuses an upload the API says the role cannot make", async () => {
    // The relay is not an authorization point; this pins that it never softens
    // the API's decision.
    mockedUpload.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: 403,
    });

    const response = await POST(fileRequest([["file", pdf()]]), context);

    expect(response.status).toBe(403);
    expect((await response.json()).detail.code).toBe("insufficient_role");
  });
});
