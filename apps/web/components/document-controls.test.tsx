import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DocumentControls, type DocumentCapabilities } from "./document-controls";
import {
  archiveDocumentAction,
  deleteDocumentAction,
  restoreDocumentAction,
  retryDocumentAction,
} from "../app/document-actions";
import type { Document, DocumentStatus } from "../lib/contracts";

vi.mock("../app/document-actions", () => ({
  archiveDocumentAction: vi.fn(),
  deleteDocumentAction: vi.fn(),
  restoreDocumentAction: vi.fn(),
  retryDocumentAction: vi.fn(),
}));

const mockedArchive = vi.mocked(archiveDocumentAction);
const mockedDelete = vi.mocked(deleteDocumentAction);
const mockedRestore = vi.mocked(restoreDocumentAction);
const mockedRetry = vi.mocked(retryDocumentAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "44444444-4444-4444-8444-444444444444";

const OWNER: DocumentCapabilities = { canManage: true, canUpload: true };
const MEMBER: DocumentCapabilities = { canManage: false, canUpload: true };
const VIEWER: DocumentCapabilities = { canManage: false, canUpload: false };

function documentWith(overrides: Partial<Document> = {}): Document {
  return {
    id: DOCUMENT_ID,
    title: "Lease agreement",
    source_filename: "lease.pdf",
    mime_type: "application/pdf",
    size_bytes: 204800,
    sha256: "a".repeat(64),
    status: "ready",
    created_at: "2026-07-01T09:00:00Z",
    archived_at: null,
    ...overrides,
  };
}

function renderControls(
  capabilities: DocumentCapabilities,
  overrides: Partial<Document> = {},
): ReturnType<typeof render> {
  return render(
    <DocumentControls
      capabilities={capabilities}
      entry={documentWith(overrides)}
      workspaceId={WORKSPACE_ID}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const action of [mockedArchive, mockedDelete, mockedRestore, mockedRetry]) {
    action.mockResolvedValue({ status: "success" });
  }
});

describe("DocumentControls", () => {
  it("downloads through a link, so no presigned URL is rendered into the page", () => {
    renderControls(OWNER);

    // The href points at this app's own route handler; the storage URL is
    // minted server side at click time and never appears in the HTML.
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      `/api/workspaces/${WORKSPACE_ID}/documents/${DOCUMENT_ID}/download`,
    );
  });

  it("archives after confirmation and passes both ids", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderControls(OWNER);

    await userEvent.click(screen.getByRole("button", { name: "Archive" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Archive Lease agreement"));
    expect(mockedArchive).toHaveBeenCalledTimes(1);
    const submitted = mockedArchive.mock.calls[0][1];
    expect(submitted.get("documentId")).toBe(DOCUMENT_ID);
    expect(submitted.get("workspaceId")).toBe(WORKSPACE_ID);
  });

  it("does not archive when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderControls(OWNER);

    await userEvent.click(screen.getByRole("button", { name: "Archive" }));

    expect(mockedArchive).not.toHaveBeenCalled();
  });

  it("offers restore and permanent deletion only once archived", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    // Permanent deletion is deliberately unreachable for a document still in
    // use as evidence: archiving is the reversible step that precedes it.
    const active = renderControls(OWNER);
    expect(screen.queryByRole("button", { name: "Delete permanently" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
    active.unmount();

    renderControls(OWNER, { archived_at: "2026-07-20T12:00:00Z" });
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(mockedRestore).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be recovered"));
    expect(mockedDelete).toHaveBeenCalledTimes(1);
  });

  it("offers reprocessing only for a failed, unarchived document", async () => {
    const cases: ReadonlyArray<readonly [DocumentStatus, boolean]> = [
      ["pending", false],
      ["processing", false],
      ["ready", false],
      ["quarantined", false],
      ["failed", true],
    ];
    for (const [status, offered] of cases) {
      const view = renderControls(MEMBER, { status });
      const button = screen.queryByRole("button", { name: "Process again" });
      expect(button === null).toBe(!offered);
      view.unmount();
    }

    // A quarantine verdict is terminal and an archived document must be
    // restored first, so neither offers reprocessing.
    const archived = renderControls(MEMBER, {
      status: "failed",
      archived_at: "2026-07-20T12:00:00Z",
    });
    expect(screen.queryByRole("button", { name: "Process again" })).not.toBeInTheDocument();
    archived.unmount();

    renderControls(MEMBER, { status: "failed" });
    await userEvent.click(screen.getByRole("button", { name: "Process again" }));
    expect(mockedRetry).toHaveBeenCalledTimes(1);
  });

  it("hides library management from members and viewers", () => {
    const memberView = renderControls(MEMBER, { archived_at: "2026-07-20T12:00:00Z" });
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete permanently" })).not.toBeInTheDocument();
    expect(screen.getByText("Owners and admins manage the library")).toBeInTheDocument();
    memberView.unmount();

    renderControls(VIEWER, { status: "failed" });
    expect(screen.queryByRole("button", { name: "Process again" })).not.toBeInTheDocument();
    // A viewer can still read the file itself.
    expect(screen.getByRole("link", { name: "Download" })).toBeInTheDocument();
  });

  it("surfaces the API's stable refusal code", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedDelete.mockResolvedValue({
      code: "document_delete_requires_archive",
      message: "Archive this document before deleting it permanently.",
      status: "error",
    });
    renderControls(OWNER, { archived_at: "2026-07-20T12:00:00Z" });

    await userEvent.click(screen.getByRole("button", { name: "Delete permanently" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Archive this document before deleting it permanently.");
    expect(alert).toHaveTextContent("Reference: document_delete_requires_archive");
  });

  it("confirms an action that succeeded", async () => {
    mockedRetry.mockResolvedValue({ message: "Processing was queued again.", status: "success" });
    renderControls(MEMBER, { status: "failed" });

    await userEvent.click(screen.getByRole("button", { name: "Process again" }));

    expect(await screen.findByText("Processing was queued again.")).toBeInTheDocument();
  });
});
