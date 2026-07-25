import { render, screen } from "@testing-library/react";

import { WorkspaceList } from "./workspace-list";
import type { WorkspaceWithRole } from "../lib/contracts";

vi.mock("../app/workspace-actions", () => ({ selectWorkspaceAction: vi.fn() }));

const workspace = (overrides: Partial<WorkspaceWithRole> = {}): WorkspaceWithRole => ({
  id: "11111111-1111-4111-8111-111111111111",
  name: "Compliance",
  slug: "compliance-a1b2c3",
  created_at: "2026-01-01T00:00:00Z",
  role: "owner",
  ...overrides,
});

describe("WorkspaceList", () => {
  it("lists the workspaces", () => {
    render(
      <WorkspaceList
        activeWorkspaceId={null}
        workspaces={[
          workspace(),
          workspace({
            id: "22222222-2222-4222-8222-222222222222",
            name: "Audit",
            role: "viewer",
            slug: "audit-d4e5f6",
          }),
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Compliance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Audit" })).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Viewer")).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("button", { name: /open compliance/i })).toBeInTheDocument();
  });

  it("renders the empty state", () => {
    render(<WorkspaceList activeWorkspaceId={null} workspaces={[]} />);

    expect(screen.getByText("No workspaces available")).toBeInTheDocument();
    expect(screen.getByText("No results")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("marks the remembered workspace so the visitor can continue where they were", () => {
    render(
      <WorkspaceList
        activeWorkspaceId="11111111-1111-4111-8111-111111111111"
        workspaces={[workspace()]}
      />,
    );

    expect(screen.getByRole("button", { name: /continue in compliance/i })).toBeInTheDocument();
  });
});
