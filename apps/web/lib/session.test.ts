import { z } from "zod";

import { authorizedRequest, readSession, writeSession, clearSession } from "./session";
import { ACCESS_COOKIE, ACTIVE_WORKSPACE_COOKIE, REFRESH_COOKIE } from "./session-cookies";

/**
 * Minimal stand-in for the Next.js cookie store, so the session module can be
 * exercised without a request context. It records the options each cookie was
 * written with, which is how the httpOnly guarantee is asserted.
 */
type Recorded = { value: string; options: Record<string, unknown> };

const store = new Map<string, Recorded>();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      const entry = store.get(name);
      return entry === undefined ? undefined : { name, value: entry.value };
    },
    set: (name: string, value: string, options: Record<string, unknown>) => {
      store.set(name, { options, value });
    },
  }),
}));

function seedSession(): void {
  store.set(ACCESS_COOKIE, { options: {}, value: "expired-access" });
  store.set(REFRESH_COOKIE, { options: {}, value: "valid-refresh" });
  store.set(ACTIVE_WORKSPACE_COOKIE, { options: {}, value: "workspace-1" });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

const unauthorized = () =>
  jsonResponse(401, {
    detail: { code: "not_authenticated", message: "A valid bearer access token is required." },
  });

const payloadSchema = z.object({ id: z.string() });

describe("session cookies", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("stores tokens as httpOnly cookies that scripts cannot read", async () => {
    await writeSession({ accessToken: "access", refreshToken: "refresh" }, 900);

    for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) {
      expect(store.get(name)?.options).toMatchObject({
        httpOnly: true,
        path: "/",
        sameSite: "lax",
      });
    }
    expect(store.get(ACCESS_COOKIE)?.options.maxAge).toBe(900);
  });

  it("treats a session without a refresh token as absent", async () => {
    store.set(ACCESS_COOKIE, { options: {}, value: "orphan-access" });

    expect(await readSession()).toBeNull();
  });

  it("clears every session cookie including the remembered workspace", async () => {
    seedSession();

    await clearSession();

    for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, ACTIVE_WORKSPACE_COOKIE]) {
      expect(store.get(name)).toEqual({
        options: expect.objectContaining({ maxAge: 0 }),
        value: "",
      });
    }
  });
});

describe("authorizedRequest", () => {
  beforeEach(() => {
    store.clear();
    vi.restoreAllMocks();
  });

  it("refreshes an expired access token once and retries", async () => {
    seedSession();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "fresh-access",
          refresh_token: "rotated-refresh",
          token_type: "bearer",
          expires_in: 900,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { id: "workspace-1" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await authorizedRequest({ path: "/workspaces/1", schema: payloadSchema });

    expect(result).toEqual({ data: { id: "workspace-1" }, ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(store.get(ACCESS_COOKIE)?.value).toBe("fresh-access");
    expect(store.get(REFRESH_COOKIE)?.value).toBe("rotated-refresh");
    const retryInit = fetchMock.mock.calls[2][1] as RequestInit;
    expect((retryInit.headers as Record<string, string>).Authorization).toBe("Bearer fresh-access");
  });

  it("clears the session when refresh fails", async () => {
    seedSession();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(unauthorized())
        .mockResolvedValueOnce(
          jsonResponse(401, {
            detail: { code: "invalid_refresh_token", message: "The refresh token is invalid." },
          }),
        ),
    );

    const result = await authorizedRequest({ path: "/workspaces/1", schema: payloadSchema });

    expect(result).toMatchObject({ code: "session_expired", ok: false, status: 401 });
    expect(store.get(REFRESH_COOKIE)?.value).toBe("");
  });

  it("stops after one refresh when the retry is still rejected", async () => {
    seedSession();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "fresh-access",
          refresh_token: "rotated-refresh",
          token_type: "bearer",
          expires_in: 900,
        }),
      )
      .mockResolvedValueOnce(unauthorized());
    vi.stubGlobal("fetch", fetchMock);

    const result = await authorizedRequest({ path: "/workspaces/1", schema: payloadSchema });

    expect(result).toMatchObject({ code: "session_expired", ok: false });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("reports an expired session when no cookie is present", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await authorizedRequest({ path: "/workspaces", schema: payloadSchema });

    expect(result).toMatchObject({ code: "session_expired", ok: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes a non-authentication failure through with its stable code", async () => {
    seedSession();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, {
          detail: { code: "insufficient_role", message: "Your role does not allow this." },
        }),
      ),
    );

    const result = await authorizedRequest({
      path: "/workspaces/1/members",
      schema: payloadSchema,
    });

    expect(result).toMatchObject({ code: "insufficient_role", ok: false, status: 403 });
  });
});
