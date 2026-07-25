import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CredentialForm } from "./credential-form";
import type { FormState } from "../app/form-state";

/**
 * Accessibility is a hard requirement for these forms: a submission that fails
 * silently is indistinguishable from a broken product, so the tests assert
 * label association, `aria-describedby` wiring, and that the error banner is
 * announced and focused.
 */
describe("CredentialForm", () => {
  it("labels every field and announces errors", async () => {
    const state: FormState = {
      code: "invalid_input",
      fieldErrors: {
        email: "Enter a valid email address.",
        password: "Use at least 8 characters.",
      },
      message: "Please correct the highlighted fields.",
      status: "error",
    };
    const action = vi.fn<(state: FormState, data: FormData) => Promise<FormState>>(
      async () => state,
    );

    render(<CredentialForm action={action} mode="register" />);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Please correct the highlighted fields.");
    expect(alert).toHaveTextContent("Reference: invalid_input");
    expect(alert).toHaveFocus();

    const email = screen.getByLabelText("Email address");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("Enter a valid email address.");

    const password = screen.getByLabelText("Password");
    expect(password).toHaveAccessibleDescription(
      "At least 8 characters. Use at least 8 characters.",
    );
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
  });

  it("submits the credentials and the sanitized next path", async () => {
    const submitted: FormData[] = [];
    const action = vi.fn(async (_state: FormState, data: FormData): Promise<FormState> => {
      submitted.push(data);
      return { status: "idle" };
    });

    render(<CredentialForm action={action} mode="login" nextPath="/workspaces/abc" />);
    await userEvent.type(screen.getByLabelText("Email address"), "ravi@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(submitted).toHaveLength(1);
    expect(submitted[0].get("email")).toBe("ravi@example.com");
    expect(submitted[0].get("next")).toBe("/workspaces/abc");
  });

  it("omits the name field when signing in", () => {
    const action = vi.fn(async (): Promise<FormState> => ({ status: "idle" }));

    render(<CredentialForm action={action} mode="login" />);

    expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });
});
