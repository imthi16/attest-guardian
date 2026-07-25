import { registerAction, loginAction, logoutAction } from "./auth-actions";
import { safeRedirectTarget } from "./form-state";
import { registerAccount, requestTokenPair, revokeRefreshToken } from "../lib/attest-api";
import { clearSession, readSession, writeSession } from "../lib/session";

vi.mock("../lib/attest-api", () => ({
  registerAccount: vi.fn(),
  requestTokenPair: vi.fn(),
  revokeRefreshToken: vi.fn(),
}));

vi.mock("../lib/session", () => ({
  clearSession: vi.fn(),
  readSession: vi.fn(),
  writeSession: vi.fn(),
}));

/** `redirect` throws in Next.js; the tests assert on the thrown destination. */
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

const mockedRegister = vi.mocked(registerAccount);
const mockedLogin = vi.mocked(requestTokenPair);
const mockedRevoke = vi.mocked(revokeRefreshToken);
const mockedReadSession = vi.mocked(readSession);
const mockedWriteSession = vi.mocked(writeSession);
const mockedClearSession = vi.mocked(clearSession);

const idle = { status: "idle" } as const;

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function expectRedirect(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof RedirectError) {
      return error.destination;
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("registerAction", () => {
  it("registers a new account", async () => {
    mockedRegister.mockResolvedValue({
      ok: true,
      data: {
        id: "user-1",
        email: "ravi@example.com",
        full_name: "Ravi Kumar",
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
      },
    });

    const destination = await expectRedirect(
      registerAction(
        idle,
        formData({
          email: " ravi@example.com ",
          fullName: "Ravi Kumar",
          password: "correct-horse",
        }),
      ),
    );

    expect(destination).toBe("/login?registered=1");
    expect(mockedRegister).toHaveBeenCalledWith({
      email: "ravi@example.com",
      fullName: "Ravi Kumar",
      password: "correct-horse",
    });
  });

  it("surfaces email_already_registered", async () => {
    mockedRegister.mockResolvedValue({
      ok: false,
      code: "email_already_registered",
      message: "An account with this email already exists.",
      status: 409,
    });

    const state = await registerAction(
      idle,
      formData({ email: "ravi@example.com", fullName: "Ravi Kumar", password: "correct-horse" }),
    );

    expect(state).toEqual({
      code: "email_already_registered",
      message: "An account with this email already exists.",
      status: "error",
    });
  });

  it("rejects a short password before calling the API", async () => {
    const state = await registerAction(
      idle,
      formData({ email: "not-an-email", fullName: "", password: "short" }),
    );

    expect(state.status).toBe("error");
    expect(state.code).toBe("invalid_input");
    expect(state.fieldErrors).toEqual({
      email: "Enter a valid email address.",
      fullName: "Enter your name.",
      password: "Use at least 8 characters.",
    });
    expect(mockedRegister).not.toHaveBeenCalled();
  });
});

describe("loginAction", () => {
  it("establishes a session on login", async () => {
    mockedLogin.mockResolvedValue({
      ok: true,
      data: {
        access_token: "access",
        refresh_token: "refresh",
        token_type: "bearer",
        expires_in: 900,
      },
    });

    const destination = await expectRedirect(
      loginAction(
        idle,
        formData({
          email: "ravi@example.com",
          next: "/workspaces/abc/members",
          password: "correct-horse",
        }),
      ),
    );

    expect(destination).toBe("/workspaces/abc/members");
    expect(mockedWriteSession).toHaveBeenCalledWith(
      { accessToken: "access", refreshToken: "refresh" },
      900,
    );
  });

  it("surfaces invalid_credentials", async () => {
    mockedLogin.mockResolvedValue({
      ok: false,
      code: "invalid_credentials",
      message: "The email or password is incorrect.",
      status: 401,
    });

    const state = await loginAction(
      idle,
      formData({ email: "ravi@example.com", password: "wrong-password" }),
    );

    expect(state).toEqual({
      code: "invalid_credentials",
      message: "The email or password is incorrect.",
      status: "error",
    });
    expect(mockedWriteSession).not.toHaveBeenCalled();
  });

  it("never echoes the submitted password back to the client", async () => {
    mockedLogin.mockResolvedValue({
      ok: false,
      code: "invalid_credentials",
      message: "The email or password is incorrect.",
      status: 401,
    });

    const state = await loginAction(
      idle,
      formData({ email: "ravi@example.com", password: "super-secret-value" }),
    );

    expect(JSON.stringify(state)).not.toContain("super-secret-value");
  });

  it("rejects malformed credentials before calling the API", async () => {
    const state = await loginAction(idle, formData({ email: "nope", password: "" }));

    expect(state.fieldErrors).toEqual({
      email: "Enter a valid email address.",
      password: "Enter your password.",
    });
    expect(mockedLogin).not.toHaveBeenCalled();
  });
});

describe("logoutAction", () => {
  it("revokes the refresh token and clears the session cookie", async () => {
    mockedReadSession.mockResolvedValue({ accessToken: "access", refreshToken: "refresh" });
    mockedRevoke.mockResolvedValue({ ok: true, data: null });

    const destination = await expectRedirect(logoutAction());

    expect(destination).toBe("/login");
    expect(mockedRevoke).toHaveBeenCalledWith("refresh");
    expect(mockedClearSession).toHaveBeenCalled();
  });

  it("still clears cookies when no session is present", async () => {
    mockedReadSession.mockResolvedValue(null);

    const destination = await expectRedirect(logoutAction());

    expect(destination).toBe("/login");
    expect(mockedRevoke).not.toHaveBeenCalled();
    expect(mockedClearSession).toHaveBeenCalled();
  });
});

describe("safeRedirectTarget", () => {
  it("refuses to bounce the visitor to another origin", () => {
    expect(safeRedirectTarget("https://evil.example.com/steal")).toBe("/workspaces");
    expect(safeRedirectTarget("//evil.example.com")).toBe("/workspaces");
    expect(safeRedirectTarget("")).toBe("/workspaces");
    expect(safeRedirectTarget(null)).toBe("/workspaces");
    expect(safeRedirectTarget("/workspaces/abc")).toBe("/workspaces/abc");
  });
});
