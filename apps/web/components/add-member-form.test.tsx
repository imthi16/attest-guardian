import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AddMemberForm } from "./add-member-form";
import { addMemberAction } from "../app/workspace-actions";

vi.mock("../app/workspace-actions", () => ({ addMemberAction: vi.fn() }));

const mockedAddMember = vi.mocked(addMemberAction);
const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

beforeEach(() => {
  vi.clearAllMocks();
  mockedAddMember.mockResolvedValue({ status: "idle" });
});

describe("AddMemberForm", () => {
  it("adds a member", async () => {
    mockedAddMember.mockResolvedValue({
      message: "priya@example.com was added.",
      status: "success",
    });

    render(<AddMemberForm actorRole="owner" workspaceId={WORKSPACE_ID} />);
    await userEvent.type(screen.getByLabelText("Member email address"), "priya@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "admin");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    const submitted = mockedAddMember.mock.calls[0][1];
    expect(submitted.get("email")).toBe("priya@example.com");
    expect(submitted.get("role")).toBe("admin");
    expect(submitted.get("workspaceId")).toBe(WORKSPACE_ID);
    expect(await screen.findByRole("status")).toHaveTextContent("priya@example.com was added.");
  });

  it("surfaces user_not_found", async () => {
    mockedAddMember.mockResolvedValue({
      code: "user_not_found",
      message: "No account exists for this email.",
      status: "error",
    });

    render(<AddMemberForm actorRole="admin" workspaceId={WORKSPACE_ID} />);
    await userEvent.type(screen.getByLabelText("Member email address"), "absent@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No account exists for this email.");
    expect(alert).toHaveTextContent("Reference: user_not_found");
  });

  it("surfaces cannot_manage_role", async () => {
    mockedAddMember.mockResolvedValue({
      code: "cannot_manage_role",
      message: "Your workspace role cannot grant the requested role.",
      status: "error",
    });

    render(<AddMemberForm actorRole="admin" workspaceId={WORKSPACE_ID} />);
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Reference: cannot_manage_role");
  });

  it("surfaces member_already_exists", async () => {
    mockedAddMember.mockResolvedValue({
      code: "member_already_exists",
      message: "This user is already a member of the workspace.",
      status: "error",
    });

    render(<AddMemberForm actorRole="owner" workspaceId={WORKSPACE_ID} />);
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Reference: member_already_exists");
  });

  it("offers an admin only the roles they may grant", () => {
    render(<AddMemberForm actorRole="admin" workspaceId={WORKSPACE_ID} />);

    const options = screen
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(options).toEqual(["member", "viewer"]);
  });

  it("offers an owner every role", () => {
    render(<AddMemberForm actorRole="owner" workspaceId={WORKSPACE_ID} />);

    const options = screen
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(options).toEqual(["owner", "admin", "member", "viewer"]);
  });

  it("shows field-level validation without contacting the API", async () => {
    mockedAddMember.mockResolvedValue({
      code: "invalid_input",
      fieldErrors: { email: "Enter a valid email address." },
      message: "Please correct the highlighted fields.",
      status: "error",
    });

    render(<AddMemberForm actorRole="owner" workspaceId={WORKSPACE_ID} />);
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByLabelText("Member email address")).toHaveAttribute("aria-invalid", "true");
  });
});
