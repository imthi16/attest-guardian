import { POST } from "./route";
import { uploadDocument } from "../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../lib/session";
import { MAX_UPLOAD_BYTES } from "../../../../../lib/upload-rules";
import type { NextRequest } from "next/server";

vi.mock("../../../../../lib/attest-api", () => ({ uploadDocument: vi.fn() }));

const mockedUpload = vi.mocked(uploadDocument);

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
};

function fileRequest(entries: Array<[string, FormDataEntryValue]>): NextRequest {
  const form = new FormData();
  for (const [key, value] of entries) {
    form.set(key, value);
  }
  return { formData: async () => form } as unknown as NextRequest;
}

function pdf(size = 12): File {
  const file = new File(["%PDF-1.7 xx"], "lease.pdf", { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

const context = { params: Promise.resolve({ workspaceId: WORKSPACE_ID }) };

beforeEach(() => {
  vi.clearAllMocks();
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
    const response = await POST(fileRequest([["file", pdf(MAX_UPLOAD_BYTES + 1)]]), context);

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({
      detail: { code: "file_too_large", message: expect.stringContaining("upload limit") },
    });
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("rejects a request with no file", async () => {
    const response = await POST(fileRequest([["title", "no file here"]]), context);

    expect(response.status).toBe(422);
    expect((await response.json()).detail.code).toBe("invalid_input");
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("rejects a body that is not multipart form data", async () => {
    const broken = {
      formData: async () => {
        throw new TypeError("not multipart");
      },
    } as unknown as NextRequest;

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
