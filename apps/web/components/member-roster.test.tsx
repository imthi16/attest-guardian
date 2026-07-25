import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MemberRoster } from "./member-roster";
import { changeMemberRoleAction, removeMemberAction } from "../app/workspace-actions";
import type { Member, MembershipRole } from "../lib/contracts";

vi.mock("../app/workspace-actions", () => ({
  changeMemberRoleAction: vi.fn(),
  removeMemberAction: vi.fn(),
}));

const mockedChangeRole = vi.mocked(changeMemberRoleAction);
const mockedRemove = vi.mocked(removeMemberAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const OWNER_ID = "22222222-2222-4222-8222-222222222222";
const MEMBER_ID = "33333333-3333-4333-8333-333333333333";

const owner: Member = {
  user_id: OWNER_ID,
  email: "ravi@example.com",
  full_name: "Ravi Kumar",
  role: "owner",
  joined_at: "2026-01-01T00:00:00Z",
};

const teamMember: Member = {
  user_id: MEMBER_ID,
  email: "priya@example.com",
  full_name: "Priya S",
  role: "member",
  joined_at: "2026-02-01T00:00:00Z",
};

function renderRoster(actorRole: MembershipRole, currentUserId = OWNER_ID) {
  return render(
    <MemberRoster
      actorRole={actorRole}
      currentUserId={currentUserId}
      members={[owner, teamMember]}
      workspaceId={WORKSPACE_ID}
    />,
  );
}

function rowFor(name: string): HTMLElement {
  const cell = screen.getByText(name);
  const row = cell.closest("tr");
  if (row === null) {
    throw new Error(`no row for ${name}`);
  }
  return row;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedChangeRole.mockResolvedValue({ status: "success" });
  mockedRemove.mockResolvedValue({ status: "success" });
});

describe("MemberRoster", () => {
  it("changes a member role", async () => {
    renderRoster("owner");

    const row = rowFor("Priya S");
    await userEvent.selectOptions(within(row).getByLabelText("Role for Priya S"), "admin");
    await userEvent.click(within(row).getByRole("button", { name: "Update" }));

    expect(mockedChangeRole).toHaveBeenCalledTimes(1);
    const submitted = mockedChangeRole.mock.calls[0][1];
    expect(submitted.get("role")).toBe("admin");
    expect(submitted.get("userId")).toBe(MEMBER_ID);
    expect(submitted.get("workspaceId")).toBe(WORKSPACE_ID);
  });

  it("surfaces last_owner", async () => {
    mockedChangeRole.mockResolvedValue({
      code: "last_owner",
      message: "A workspace must keep at least one owner.",
      status: "error",
    });
    renderRoster("owner", MEMBER_ID);

    const row = rowFor("Ravi Kumar");
    await userEvent.click(within(row).getByRole("button", { name: "Update" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A workspace must keep at least one owner.");
    expect(alert).toHaveTextContent("Reference: last_owner");
  });

  it("removes a member after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderRoster("owner");

    const row = rowFor("Priya S");
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Remove Priya S"));
    expect(mockedRemove).toHaveBeenCalledTimes(1);
    expect(mockedRemove.mock.calls[0][1].get("userId")).toBe(MEMBER_ID);
  });

  it("does not remove a member when confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderRoster("owner");

    await userEvent.click(within(rowFor("Priya S")).getByRole("button", { name: "Remove" }));

    expect(mockedRemove).not.toHaveBeenCalled();
  });

  it("never offers self-removal, so a workspace cannot be abandoned by accident", () => {
    renderRoster("owner");

    expect(within(rowFor("Ravi Kumar")).getByText("This is you")).toBeInTheDocument();
    expect(
      within(rowFor("Ravi Kumar")).queryByRole("button", { name: "Remove" }),
    ).not.toBeInTheDocument();
  });

  it("shows member management to owners and admins", () => {
    const ownerView = renderRoster("owner");
    expect(within(rowFor("Priya S")).getByLabelText("Role for Priya S")).toBeInTheDocument();
    expect(within(rowFor("Priya S")).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    ownerView.unmount();

    // An admin manages unprivileged members but cannot touch an owner, which
    // mirrors the API rule that keeps admins from locking owners out.
    renderRoster("admin", MEMBER_ID);
    expect(within(rowFor("Priya S")).getByLabelText("Role for Priya S")).toBeInTheDocument();
    expect(within(rowFor("Ravi Kumar")).getByText("Owner")).toBeInTheDocument();
    expect(
      within(rowFor("Ravi Kumar")).queryByLabelText("Role for Ravi Kumar"),
    ).not.toBeInTheDocument();
    expect(within(rowFor("Ravi Kumar")).getByText("Not manageable")).toBeInTheDocument();
  });

  it("hides member management from members and viewers", () => {
    for (const role of ["member", "viewer"] as const) {
      const { unmount } = renderRoster(role, MEMBER_ID);
      expect(screen.queryByRole("button", { name: "Update" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
      expect(screen.getByText("Owner")).toBeInTheDocument();
      unmount();
    }
  });

  it("keeps the member roster usable at 375px", () => {
    // At phone widths the table collapses into labelled cards, which only works
    // if every data cell carries the header text it stands in for.
    renderRoster("owner");

    for (const label of ["Member", "Role", "Actions"]) {
      expect(rowFor("Priya S").querySelector(`[data-label="${label}"]`)).not.toBeNull();
    }
    expect(screen.getByRole("table")).toHaveAccessibleName(
      "Workspace members, their roles, and available actions",
    );
  });
});
