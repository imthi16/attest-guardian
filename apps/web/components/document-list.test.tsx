import { render, screen, within } from "@testing-library/react";

import { DocumentList } from "./document-list";
import type { Document } from "../lib/contracts";

vi.mock("../app/document-actions", () => ({
  archiveDocumentAction: vi.fn(),
  deleteDocumentAction: vi.fn(),
  restoreDocumentAction: vi.fn(),
  retryDocumentAction: vi.fn(),
}));

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

function documentWith(overrides: Partial<Document>): Document {
  return {
    id: "44444444-4444-4444-8444-444444444444",
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

const ready = documentWith({});
const archived = documentWith({
  id: "55555555-5555-4555-8555-555555555555",
  title: "Superseded policy",
  source_filename: "policy-v1.pdf",
  archived_at: "2026-07-20T12:00:00Z",
});

function rowFor(title: string): HTMLElement {
  const row = screen.getByText(title).closest("tr");
  if (row === null) {
    throw new Error(`no row for ${title}`);
  }
  return row;
}

describe("DocumentList", () => {
  it("states each document's processing state and links to its detail page", () => {
    render(
      <DocumentList
        capabilities={{ canManage: true, canUpload: true }}
        documents={[ready, archived]}
        workspaceId={WORKSPACE_ID}
      />,
    );

    expect(within(rowFor("Lease agreement")).getByText("Ready")).toBeInTheDocument();
    expect(within(rowFor("Lease agreement")).getByText("lease.pdf")).toBeInTheDocument();
    expect(within(rowFor("Lease agreement")).getByText("200 KB")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Lease agreement" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/documents/${ready.id}`,
    );

    // An archived document is still listed, but it never reads as citable.
    expect(within(rowFor("Superseded policy")).getByText("Archived")).toBeInTheDocument();
    expect(rowFor("Superseded policy")).toHaveAttribute("data-archived", "true");
    expect(rowFor("Lease agreement")).toHaveAttribute("data-archived", "false");
  });

  it("renders a hostile filename as text, never as markup", () => {
    // Filenames come from uploads. A stored name that a browser interpreted as
    // HTML would turn the library page into a delivery mechanism.
    const hostile = documentWith({
      id: "66666666-6666-4666-8666-666666666666",
      title: '<script>alert("x")</script>',
      source_filename: '<img src=x onerror="alert(1)">.pdf',
    });
    const { container } = render(
      <DocumentList
        capabilities={{ canManage: false, canUpload: false }}
        documents={[hostile]}
        workspaceId={WORKSPACE_ID}
      />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText('<script>alert("x")</script>')).toBeInTheDocument();
  });

  it("keeps the library usable at 375px", () => {
    // At phone widths the table collapses into labelled cards, which only works
    // if every data cell carries the header text it stands in for.
    render(
      <DocumentList
        capabilities={{ canManage: true, canUpload: true }}
        documents={[ready]}
        workspaceId={WORKSPACE_ID}
      />,
    );

    for (const label of ["Document", "State", "Size", "Actions"]) {
      expect(rowFor("Lease agreement").querySelector(`[data-label="${label}"]`)).not.toBeNull();
    }
    expect(screen.getByRole("table")).toHaveAccessibleName(
      "Documents in this workspace, their processing state, and available actions",
    );
  });
});
