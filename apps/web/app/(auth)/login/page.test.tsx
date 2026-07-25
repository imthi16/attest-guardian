import { render, screen } from "@testing-library/react";

import LoginPage from "./page";
import { readSession } from "../../../lib/session";

vi.mock("../../auth-actions", () => ({ loginAction: vi.fn() }));
vi.mock("../../../lib/session", () => ({ readSession: vi.fn() }));

class RedirectError extends Error {
  constructor(public readonly destination: string) {
    super(`NEXT_REDIRECT:${destination}`);
  }
}

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new RedirectError(destination);
  },
}));

const mockedReadSession = vi.mocked(readSession);

async function renderPage(
  searchParams: Readonly<{ expired?: string; next?: string; registered?: string }> = {},
) {
  const element = await LoginPage({ searchParams: Promise.resolve(searchParams) });
  return render(element);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedReadSession.mockResolvedValue(null);
});

describe("LoginPage", () => {
  it("renders Tamil copy with a ta language tag", async () => {
    await renderPage();

    const tamil = screen.getByText("உங்கள் பணியிடத்தில் நுழையுங்கள்.");
    expect(tamil).toHaveAttribute("lang", "ta");
    // Guards against mojibake: the copy must survive as Tamil code points.
    expect(tamil.textContent).toMatch(/^[\u0B80-\u0BFF\s.]+$/u);
  });

  it("offers the sign-in form and a route to registration", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/register");
  });

  it("confirms a completed registration", async () => {
    await renderPage({ registered: "1" });

    expect(screen.getByRole("status")).toHaveTextContent("Account created.");
  });

  it("explains an expired session rather than failing silently", async () => {
    await renderPage({ expired: "1" });

    expect(screen.getByRole("status")).toHaveTextContent("Your session expired.");
    expect(screen.getByRole("status")).toHaveTextContent("Reference: session_expired");
  });

  it("sends an already signed-in visitor onward without asking for credentials", async () => {
    mockedReadSession.mockResolvedValue({ accessToken: "access", refreshToken: "refresh" });

    await expect(renderPage({ next: "/workspaces/abc" })).rejects.toThrow(
      "NEXT_REDIRECT:/workspaces/abc",
    );
  });

  it("refuses an off-site next parameter", async () => {
    mockedReadSession.mockResolvedValue({ accessToken: "access", refreshToken: "refresh" });

    await expect(renderPage({ next: "https://evil.example.com" })).rejects.toThrow(
      "NEXT_REDIRECT:/workspaces",
    );
  });
});
