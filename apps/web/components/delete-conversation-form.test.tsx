import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DeleteConversationForm } from "./delete-conversation-form";
import { deleteConversationAction } from "../app/conversation-actions";

vi.mock("../app/conversation-actions", () => ({ deleteConversationAction: vi.fn() }));

const mockedDelete = vi.mocked(deleteConversationAction);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION_ID = "22222222-2222-4222-8222-222222222222";

beforeEach(() => {
  vi.clearAllMocks();
  mockedDelete.mockResolvedValue({ status: "idle" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderForm() {
  render(<DeleteConversationForm conversationId={CONVERSATION_ID} workspaceId={WORKSPACE_ID} />);
}

describe("DeleteConversationForm", () => {
  it("does nothing when the confirmation is declined", async () => {
    // The whole point of the prompt: a mis-click must not destroy answer history.
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: /Delete this thread/ }));

    expect(mockedDelete).not.toHaveBeenCalled();
  });

  it("says what is and is not destroyed before asking", async () => {
    const confirm = vi.fn().mockReturnValue(true);
    vi.stubGlobal("confirm", confirm);
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: /Delete this thread/ }));

    const prompt = String(confirm.mock.calls[0][0]);
    expect(prompt).toContain("permanently");
    // "Delete" next to evidence-backed answers is alarming enough that the
    // scope has to be explicit.
    expect(prompt).toContain("documents they cited are not affected");
  });

  it("submits the thread and workspace when confirmed", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: /Delete this thread/ }));

    expect(mockedDelete).toHaveBeenCalled();
    const submitted = mockedDelete.mock.calls[0][1];
    expect(submitted.get("conversationId")).toBe(CONVERSATION_ID);
    expect(submitted.get("workspaceId")).toBe(WORKSPACE_ID);
  });

  it("relays a refusal with its stable code", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    mockedDelete.mockResolvedValue({
      code: "insufficient_role",
      message: "Only the author or an admin can delete this thread.",
      status: "error",
    });
    renderForm();

    await userEvent.click(screen.getByRole("button", { name: /Delete this thread/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Only the author or an admin");
    expect(alert).toHaveTextContent("Reference: insufficient_role");
  });
});
