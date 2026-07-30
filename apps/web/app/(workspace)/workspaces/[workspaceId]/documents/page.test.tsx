import { render, screen } from "@testing-library/react";

import DocumentsPage from "./page";
import DocumentsLoading from "./loading";
import {
  fetchCurrentUser,
  fetchDocuments,
  fetchUploadPolicy,
  fetchWorkspace,
} from "../../../../../lib/attest-api";
import { SESSION_EXPIRED } from "../../../../../lib/session";
import type { Document, MembershipRole } from "../../../../../lib/contracts";

vi.mock("../../../../../lib/attest-api", () => ({
  fetchCurrentUser: vi.fn(),
  fetchDocuments: vi.fn(),
  fetchUploadPolicy: vi.fn(),
  fetchWorkspace: vi.fn(),
}));

vi.mock("../../../../auth-actions", () => ({ logoutAction: vi.fn() }));

vi.mock("../../../../document-actions", () => ({
  archiveDocumentAction: vi.fn(),
  deleteDocumentAction: vi.fn(),
  restoreDocumentAction: vi.fn(),
  retryDocumentAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const mockedUser = vi.mocked(fetchCurrentUser);
const mockedDocuments = vi.mocked(fetchDocuments);
const mockedPolicy = vi.mocked(fetchUploadPolicy);
const mockedWorkspace = vi.mocked(fetchWorkspace);

const policy = {
  ok: true as const,
  data: {
    max_upload_bytes: 25 * 1024 * 1024,
    max_filename_length: 255,
    accepted_extensions: [".pdf", ".txt", ".md", ".markdown", ".docx"],
  },
};

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

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

const ready: Document = {
  id: "44444444-4444-4444-8444-444444444444",
  title: "Lease agreement",
  source_filename: "lease.pdf",
  mime_type: "application/pdf",
  size_bytes: 2048,
  sha256: "a".repeat(64),
  status: "ready",
  created_at: "2026-07-01T09:00:00Z",
  archived_at: null,
  retryable: false,
};

const renderPage = async (
  role: MembershipRole = "owner",
  searchParams: Record<string, string> = {},
) => {
  mockedWorkspace.mockResolvedValue(workspaceAs(role));
  return render(
    await DocumentsPage({
      params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
      searchParams: Promise.resolve(searchParams),
    }),
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedUser.mockResolvedValue(user);
  mockedDocuments.mockResolvedValue({ ok: true, data: [ready] });
  mockedPolicy.mockResolvedValue(policy);
});

describe("DocumentsPage", () => {
  it("lists documents and offers upload to a member", async () => {
    await renderPage("member");

    expect(screen.getByRole("heading", { name: "Compliance documents" })).toBeInTheDocument();
    expect(screen.getByText("Lease agreement")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload document" })).toBeInTheDocument();
    // Archived documents are withdrawn from evidence, so they are out of the
    // default view rather than mixed in with citable ones.
    expect(mockedDocuments).toHaveBeenCalledWith(WORKSPACE_ID, { includeArchived: false });
  });

  it("shows the deployment's own upload limit, not the compiled default", async () => {
    mockedPolicy.mockResolvedValue({
      ok: true,
      data: { ...policy.data, accepted_extensions: [".pdf"], max_upload_bytes: 100 * 1024 * 1024 },
    });

    await renderPage("member");

    expect(screen.getByText(/\.pdf up to 100 MB/)).toBeInTheDocument();
  });

  it("still offers upload when the policy cannot be read, without enforcing a guess", async () => {
    // The API remains the enforcement point, so a policy read that fails must
    // degrade rather than block uploading entirely — but it must not turn the
    // compiled-in default into a local limit either. On a deployment that raised
    // MAX_UPLOAD_BYTES that would refuse files the API accepts, so the hint says
    // "usually" and the size check is skipped until a real limit is known.
    mockedPolicy.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable.",
      status: 503,
    });

    await renderPage("member");

    expect(screen.getByRole("button", { name: "Upload document" })).toBeInTheDocument();
    expect(screen.getByText(/usually up to 25 MB/)).toBeInTheDocument();
  });

  it("explains to a viewer why there is no upload control", async () => {
    await renderPage("viewer");

    expect(screen.queryByRole("button", { name: "Upload document" })).not.toBeInTheDocument();
    const notice = screen.getByRole("alert");
    expect(notice).toHaveTextContent("only members, admins, and owners can add them");
    expect(notice).toHaveTextContent("Reference: insufficient_role");
  });

  it("shows archived documents when they are asked for", async () => {
    await renderPage("owner", { archived: "1" });

    expect(mockedDocuments).toHaveBeenCalledWith(WORKSPACE_ID, { includeArchived: true });
    expect(screen.getByRole("link", { name: "Hide archived" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/documents`,
    );
  });

  it("offers the archived view when it is hidden", async () => {
    await renderPage("owner");

    expect(screen.getByRole("link", { name: "Show archived" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/documents?archived=1`,
    );
  });

  it("distinguishes an empty library from a hidden one", async () => {
    mockedDocuments.mockResolvedValue({ ok: true, data: [] });
    const active = await renderPage("owner");
    expect(screen.getByText(/show archived documents if you expected/)).toBeInTheDocument();
    active.unmount();

    await renderPage("owner", { archived: "1" });
    expect(screen.getByText("This workspace has no documents at all yet.")).toBeInTheDocument();
  });

  it("confirms a permanent deletion the caller just made", async () => {
    await renderPage("owner", { deleted: "1" });

    expect(screen.getByText(/were permanently deleted/)).toBeInTheDocument();
  });

  it("says the list failed rather than showing an empty library", async () => {
    // An empty list and a failed request must never look the same: one means
    // "nothing here", the other means "we do not know".
    mockedDocuments.mockResolvedValue({
      ok: false,
      code: "api_unreachable",
      message: "The service is unavailable. Please try again shortly.",
      status: 503,
    });

    await renderPage("owner");

    expect(
      screen.getByRole("heading", { name: "The document list could not be loaded" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/The service is unavailable/)).toBeInTheDocument();
  });

  it("shows a non-member the same notice as for a missing workspace", async () => {
    mockedWorkspace.mockResolvedValue({
      ok: false,
      code: "workspace_not_found",
      message: "The workspace does not exist or you are not a member.",
      status: 404,
    });

    render(
      await DocumentsPage({
        params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
        searchParams: Promise.resolve({}),
      }),
    );

    expect(screen.getByRole("heading", { name: "Workspace not found" })).toBeInTheDocument();
    expect(screen.queryByText("Lease agreement")).not.toBeInTheDocument();
  });

  it("sends an expired session back to sign in, keeping the destination", async () => {
    mockedDocuments.mockResolvedValue({
      ok: false,
      code: SESSION_EXPIRED,
      message: "Your session expired.",
      status: 401,
    });
    mockedWorkspace.mockResolvedValue(workspaceAs("owner"));

    await expect(
      DocumentsPage({
        params: Promise.resolve({ workspaceId: WORKSPACE_ID }),
        searchParams: Promise.resolve({}),
      }),
    ).rejects.toThrow(`NEXT_REDIRECT:/login?expired=1&next=/workspaces/${WORKSPACE_ID}/documents`);
  });
});

describe("DocumentsLoading", () => {
  it("announces that the library is being fetched", () => {
    render(<DocumentsLoading />);

    expect(screen.getByRole("heading", { name: "Loading documents" })).toBeInTheDocument();
  });
});
