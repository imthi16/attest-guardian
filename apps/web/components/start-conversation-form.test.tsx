import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { StartConversationForm } from "./start-conversation-form";
import { startConversationAction } from "../app/conversation-actions";

vi.mock("../app/conversation-actions", () => ({ startConversationAction: vi.fn() }));

const mockedStart = vi.mocked(startConversationAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

beforeEach(() => {
  vi.clearAllMocks();
  mockedStart.mockResolvedValue({ status: "idle" });
});

describe("StartConversationForm", () => {
  it("submits with the workspace and an optional title", async () => {
    render(<StartConversationForm workspaceId={WORKSPACE_ID} />);

    await userEvent.type(screen.getByLabelText(/Thread title/), "Invoice terms");
    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));

    const submitted = mockedStart.mock.calls[0][1];
    expect(submitted.get("title")).toBe("Invoice terms");
    expect(submitted.get("workspaceId")).toBe(WORKSPACE_ID);
  });

  it("allows an untitled thread", async () => {
    // Naming a thread before knowing the question is friction for no benefit.
    render(<StartConversationForm workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));

    expect(mockedStart).toHaveBeenCalled();
    expect(mockedStart.mock.calls[0][1].get("title")).toBe("");
  });

  it("shows a field error against the title", async () => {
    mockedStart.mockResolvedValue({
      code: "invalid_input",
      fieldErrors: { title: "Keep the title under 500 characters." },
      message: "Please correct the highlighted fields.",
      status: "error",
    });
    render(<StartConversationForm workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));

    expect(await screen.findByText("Keep the title under 500 characters.")).toBeInTheDocument();
  });

  it("relays a refusal with its stable code", async () => {
    mockedStart.mockResolvedValue({
      code: "insufficient_role",
      message: "Your workspace role does not allow this action.",
      status: "error",
    });
    render(<StartConversationForm workspaceId={WORKSPACE_ID} />);

    await userEvent.click(screen.getByRole("button", { name: "Start a thread" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Reference: insufficient_role");
  });
});
