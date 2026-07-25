import { render, screen } from "@testing-library/react";

import RegisterPage from "./page";
import { readSession } from "../../../lib/session";

vi.mock("../../auth-actions", () => ({ registerAction: vi.fn() }));
vi.mock("../../../lib/session", () => ({ readSession: vi.fn() }));

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new Error(`NEXT_REDIRECT:${destination}`);
  },
}));

const mockedReadSession = vi.mocked(readSession);

beforeEach(() => {
  vi.clearAllMocks();
  mockedReadSession.mockResolvedValue(null);
});

describe("RegisterPage", () => {
  it("collects a name, email, and password", async () => {
    render(await RegisterPage());

    expect(
      screen.getByRole("heading", { level: 1, name: "Create your account" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("explains that workspace access is granted, not self-served", async () => {
    render(await RegisterPage());

    expect(screen.getByText(/added to workspaces by their owners or admins/i)).toBeInTheDocument();
  });

  it("sends a signed-in visitor to their workspaces", async () => {
    mockedReadSession.mockResolvedValue({ accessToken: "access", refreshToken: "refresh" });

    await expect(RegisterPage()).rejects.toThrow("NEXT_REDIRECT:/workspaces");
  });
});
