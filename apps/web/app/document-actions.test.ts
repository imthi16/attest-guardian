import {
  archiveDocumentAction,
  deleteDocumentAction,
  restoreDocumentAction,
  retryDocumentAction,
} from "./document-actions";
import {
  archiveDocument,
  deleteDocument,
  restoreDocument,
  retryDocumentIngestion,
} from "../lib/attest-api";
import { SESSION_EXPIRED } from "../lib/session";
import type { Document, DocumentProgress } from "../lib/contracts";

vi.mock("../lib/attest-api", () => ({
  archiveDocument: vi.fn(),
  deleteDocument: vi.fn(),
  restoreDocument: vi.fn(),
  retryDocumentIngestion: vi.fn(),
}));

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

class RedirectError extends Error {
  constructor(public readonly destination: string) {
    super(`NEXT_REDIRECT:${destination}`);
  }
}

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new RedirectError(destination);
  },
}));

const mockedArchive = vi.mocked(archiveDocument);
const mockedDelete = vi.mocked(deleteDocument);
const mockedRestore = vi.mocked(restoreDocument);
const mockedRetry = vi.mocked(retryDocumentIngestion);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "44444444-4444-4444-8444-444444444444";
const idle = { status: "idle" } as const;

const document: Document = {
  id: DOCUMENT_ID,
  title: "Lease agreement",
  source_filename: "lease.pdf",
  mime_type: "application/pdf",
  size_bytes: 2048,
  sha256: "a".repeat(64),
  status: "ready",
  created_at: "2026-07-01T09:00:00Z",
  archived_at: null,
};

const progress: DocumentProgress = {
  document_id: DOCUMENT_ID,
  status: "pending",
  job_status: "queued",
  stage: "uploaded",
  attempts: 0,
  error: null,
  updated_at: "2026-07-29T10:00:00Z",
  archived: false,
  retryable: false,
};

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

function target(): FormData {
  return formData({ documentId: DOCUMENT_ID, workspaceId: WORKSPACE_ID });
}

async function expectRedirect(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof RedirectError) {
      return error.destination;
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("archiveDocumentAction", () => {
  it("archives and explains that the document is no longer evidence", async () => {
    mockedArchive.mockResolvedValue({ ok: true, data: { ...document, archived_at: "now" } });

    const state = await archiveDocumentAction(idle, target());

    expect(mockedArchive).toHaveBeenCalledWith(WORKSPACE_ID, DOCUMENT_ID);
    expect(state.status).toBe("success");
    expect(state.message).toContain("no longer be used as evidence");
  });

  it("relays a refusal with its stable code", async () => {
    mockedArchive.mockResolvedValue({
      ok: false,
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: 403,
    });

    const state = await archiveDocumentAction(idle, target());

    expect(state).toEqual({
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: "error",
    });
  });

  it("restarts sign-in when the session has expired", async () => {
    mockedArchive.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });

    expect(await expectRedirect(archiveDocumentAction(idle, target()))).toBe("/login?expired=1");
  });

  it("rejects ids that are not workspace or document ids", async () => {
    // A malformed id never reaches the API: it cannot identify anything, and
    // sending it would only produce a confusing backend error.
    const state = await archiveDocumentAction(
      idle,
      formData({ documentId: "not-a-uuid", workspaceId: WORKSPACE_ID }),
    );

    expect(state.status).toBe("error");
    expect(state.fieldErrors?.documentId).toBe("Select a valid document.");
    expect(mockedArchive).not.toHaveBeenCalled();
  });
});

describe("restoreDocumentAction", () => {
  it("restores a document to evidence", async () => {
    mockedRestore.mockResolvedValue({ ok: true, data: document });

    const state = await restoreDocumentAction(idle, target());

    expect(mockedRestore).toHaveBeenCalledWith(WORKSPACE_ID, DOCUMENT_ID);
    expect(state.message).toContain("available as evidence again");
  });

  it("does not claim a document that never finished processing is evidence", async () => {
    // Restoring only clears `archived_at`. A failed or quarantined document is
    // still excluded by `evidence_eligible()`, so saying it is usable again
    // would be wrong exactly where it matters most.
    for (const status of ["pending", "processing", "failed", "quarantined"] as const) {
      mockedRestore.mockResolvedValue({ ok: true, data: { ...document, status } });

      const state = await restoreDocumentAction(idle, target());

      expect(state.status).toBe("success");
      expect(state.message).not.toContain("available as evidence again");
      expect(state.message).toContain("not evidence yet");
    }
  });

  it("relays a refusal", async () => {
    mockedRestore.mockResolvedValue({
      ok: false,
      code: "document_not_found",
      message: "The document does not exist in this workspace.",
      status: 404,
    });

    expect((await restoreDocumentAction(idle, target())).code).toBe("document_not_found");
  });
});

describe("retryDocumentAction", () => {
  it("queues another ingestion run", async () => {
    mockedRetry.mockResolvedValue({ ok: true, data: progress });

    const state = await retryDocumentAction(idle, target());

    expect(mockedRetry).toHaveBeenCalledWith(WORKSPACE_ID, DOCUMENT_ID);
    expect(state.message).toBe("Processing was queued again.");
  });

  it("surfaces the API's refusal to reprocess a quarantined document", async () => {
    mockedRetry.mockResolvedValue({
      ok: false,
      code: "document_not_retryable",
      message: "Only a failed document can be processed again.",
      status: 409,
    });

    const state = await retryDocumentAction(idle, target());

    expect(state.code).toBe("document_not_retryable");
    expect(state.status).toBe("error");
  });
});

describe("deleteDocumentAction", () => {
  it("returns to the library with an explicit confirmation", async () => {
    mockedDelete.mockResolvedValue({ ok: true, data: null });

    const destination = await expectRedirect(deleteDocumentAction(idle, target()));

    expect(mockedDelete).toHaveBeenCalledWith(WORKSPACE_ID, DOCUMENT_ID);
    expect(destination).toBe(`/workspaces/${WORKSPACE_ID}/documents?deleted=1`);
  });

  it("stays put and explains when the API requires archiving first", async () => {
    mockedDelete.mockResolvedValue({
      ok: false,
      code: "document_delete_requires_archive",
      message: "Archive this document before deleting it permanently.",
      status: 409,
    });

    const state = await deleteDocumentAction(idle, target());

    expect(state.code).toBe("document_delete_requires_archive");
    expect(state.status).toBe("error");
  });

  it("rejects a malformed target before calling the API", async () => {
    const state = await deleteDocumentAction(
      idle,
      formData({ documentId: DOCUMENT_ID, workspaceId: "" }),
    );

    expect(state.status).toBe("error");
    expect(mockedDelete).not.toHaveBeenCalled();
  });
});
