import { render, screen } from "@testing-library/react";

import DocumentDetailPage from "./page";
import DocumentDetailLoading from "./loading";
import {
  fetchCurrentUser,
  fetchDocument,
  fetchDocumentProgress,
  fetchWorkspace,
} from "../../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../../lib/session";
import type { Document, DocumentProgress, MembershipRole } from "../../../../../../lib/contracts";

vi.mock("../../../../../../lib/attest-api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchDocument: vi.fn(),
  fetchDocumentProgress: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../../../auth-actions", () => ({ logoutAction: vi.fn() }));

vi.mock("../../../../../document-actions", () => ({
  archiveDocumentAction: vi.fn(),
  deleteDocumentAction: vi.fn(),
  restoreDocumentAction: vi.fn(),
  retryDocumentAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
}));

const mockedUser = vi.mocked(fetchCurrentUser);
const mockedDocument = vi.mocked(fetchDocument);
const mockedProgress = vi.mocked(fetchDocumentProgress);
const mockedWorkspace = vi.mocked(fetchWorkspace);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_ID = "44444444-4444-4444-8444-444444444444";

const user = {
  ok: true as const,
  data: {
    id: "user-1",
    email: "ravi@example.com",
    full_name: "Ravi Kumar",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
  },
};

const workspaceAs = (role: MembershipRole) => ({
  ok: true as const,
  data: {
    id: WORKSPACE_ID,
    name: "Compliance",
    slug: "compliance-a1b2c3",
    created_at: "2026-01-01T00:00:00Z",
    role,
  },
});

const document: Document = {
  id: DOCUMENT_ID,
  title: "Lease agreement",
  source_filename: "lease.pdf",
  mime_type: "application/pdf",
  size_bytes: 204800,
  sha256: "b".repeat(64),
  status: "ready",
  created_at: "2026-07-01T09:00:00Z",
  archived_at: null,
};

const progress: DocumentProgress = {
  document_id: DOCUMENT_ID,
  status: "ready",
  job_status: "succeeded",
  stage: "ready",
  attempts: 1,
  error: null,
  updated_at: "2026-07-01T09:05:00Z",
  archived: false,
  retryable: false,
};

const renderPage = async (role: MembershipRole = "owner") => {
  mockedWorkspace.mockResolvedValue(workspaceAs(role));
  return render(
    await DocumentDetailPage({
      params: Promise.resolve({ documentId: DOCUMENT_ID, workspaceId: WORKSPACE_ID }),
    }),
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedDocument.mockResolvedValue({ ok: true, data: document });
  mockedProgress.mockResolvedValue({ ok: true, data: progress });
});

describe("DocumentDetailPage", () => {
  it("shows verifiable facts about the file and its processing state", async () => {
    await renderPage("owner");

    expect(screen.getByRole("heading", { name: "Lease agreement" })).toBeInTheDocument();
    expect(screen.getByText("lease.pdf")).toBeInTheDocument();
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
    expect(screen.getByText("200 KB")).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("never previews the document's own contents", async () => {
    // The file's text is untrusted input to the model; it reaches a reader only
    // as cited evidence, so this page must not render bytes from it at all.
    const { container } = await renderPage("owner");

    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("object")).toBeNull();
    expect(container.querySelector("embed")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("explains a quarantine and offers no reprocessing", async () => {
    mockedDocument.mockResolvedValue({ ok: true, data: { ...document, status: "quarantined" } });
    mockedProgress.mockResolvedValue({
      ok: true,
      data: {
        ...progress,
        status: "quarantined",
        job_status: "failed",
        stage: "scanning",
        error: "quarantined: eicar signature",
      },
    });

    await renderPage("owner");

    expect(screen.getByText("Quarantined")).toBeInTheDocument();
    expect(screen.getByText(/never used as evidence/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Process again" })).not.toBeInTheDocument();
  });

  it("offers reprocessing for a failed document", async () => {
    mockedDocument.mockResolvedValue({ ok: true, data: { ...document, status: "failed" } });
    mockedProgress.mockResolvedValue({
      ok: true,
      data: { ...progress, status: "failed", job_status: "failed", retryable: true },
    });

    await renderPage("member");

    expect(screen.getByRole("button", { name: "Process again" })).toBeInTheDocument();
  });

  it("keeps the state section honest when progress cannot be loaded", async () => {
    mockedProgress.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable. Please try again shortly.",
      status: 503,
    });

    await renderPage("owner");

    expect(
      screen.getByRole("heading", { name: "The processing state could not be loaded" }),
    ).toBeInTheDocument();
  });

  it("refuses a document from another workspace with its stable code", async () => {
    mockedDocument.mockResolvedValue({
      ok: false,
      code: "document_not_found",
      message: "The document does not exist in this workspace.",
      status: 404,
    });

    await renderPage("owner");

    // Navigation still renders, so the caller is not stranded.
    expect(screen.getByRole("link", { name: "Documents" })).toBeInTheDocument();
    expect(screen.getByText("Reference: document_not_found")).toBeInTheDocument();
  });

  it("shows a non-member the workspace notice instead of the document", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "workspace_not_found",
      message: "The workspace does not exist or you are not a member.",
      status: 404,
    });

    render(
      await DocumentDetailPage({
        params: Promise.resolve({ documentId: DOCUMENT_ID, workspaceId: WORKSPACE_ID }),
      }),
    );

    expect(screen.getByRole("heading", { name: "Workspace not found" })).toBeInTheDocument();
    expect(screen.queryByText("lease.pdf")).not.toBeInTheDocument();
  });

  it("sends an expired session back to sign in, keeping the destination", async () => {
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));
    mockedDocument.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });

    await expect(
      DocumentDetailPage({
        params: Promise.resolve({ documentId: DOCUMENT_ID, workspaceId: WORKSPACE_ID }),
      }),
    ).rejects.toThrow(
      `NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}/documents/${DOCUMENT_ID}`,
    );
  });
});

describe("DocumentDetailLoading", () => {
  it("announces that the document is being fetched", () => {
    render(<DocumentDetailLoading />);

    expect(screen.getByRole("heading", { name: "Loading document" })).toBeInTheDocument();
  });
});
