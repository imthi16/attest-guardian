import { z } from "zod";

import { apiRequest, apiOrigin } from "./api-client";
import { memberListSchema, userSchema, workspaceListSchema } from "./contracts";

const originalOrigin = process.env.API_INTERNAL_ORIGIN;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

describe("apiRequest", () => {
  beforeEach(() => {
    delete process.env.API_INTERNAL_ORIGIN;
    vi.restoreAllMocks();
  });

  afterAll(() => {
    if (originalOrigin === undefined) {
      delete process.env.API_INTERNAL_ORIGIN;
    } else {
      process.env.API_INTERNAL_ORIGIN = originalOrigin;
    }
  });

  it("defaults to the local FastAPI origin and honours configuration", () => {
    expect(apiOrigin()).toBe("http://127.0.0.1:8000");
    process.env.API_INTERNAL_ORIGIN = "http://api:8000";
    expect(apiOrigin()).toBe("http://api:8000");
  });

  it("validates and returns a successful payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, [
        {
          id: "11111111-1111-4111-8111-111111111111",
          name: "Compliance",
          slug: "compliance-a1b2c3",
          created_at: "2026-01-01T00:00:00Z",
          role: "owner",
        },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiRequest({
      accessToken: "access-token",
      path: "/workspaces",
      schema: workspaceListSchema,
    });

    expect(result.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/api/v1/workspaces");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer access-token");
    expect(init.cache).toBe("no-store");
  });

  it("rejects a malformed API payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, [{ id: 12, unexpected: true }])),
    );

    const result = await apiRequest({ path: "/workspaces/x/members", schema: memberListSchema });

    expect(result).toMatchObject({ code: "invalid_api_response", ok: false, status: 502 });
  });

  it("surfaces the stable error code from the API envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, {
          detail: {
            code: "insufficient_role",
            message: "Your workspace role does not allow this.",
          },
        }),
      ),
    );

    const result = await apiRequest({ path: "/workspaces/x/members", schema: memberListSchema });

    expect(result).toMatchObject({
      code: "insufficient_role",
      message: "Your workspace role does not allow this.",
      ok: false,
      status: 403,
    });
  });

  it("falls back to a stable code when the error envelope is unrecognised", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(422, { detail: [{ loc: ["body"], msg: "bad" }] })),
    );

    const result = await apiRequest({ path: "/auth/login", schema: userSchema });

    expect(result).toMatchObject({ code: "http_422", ok: false, status: 422 });
  });

  it("reports an unreachable backend without leaking the transport error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED 127.0.0.1:8000")));

    const result = await apiRequest({ path: "/auth/me", schema: userSchema });

    expect(result).toMatchObject({ code: "api_unreachable", ok: false, status: 503 });
    if (!result.ok) {
      expect(result.message).not.toContain("ECONNREFUSED");
    }
  });

  it("accepts an empty 204 response for void endpoints", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    const result = await apiRequest({
      body: { refresh_token: "token" },
      method: "POST",
      path: "/auth/logout",
      schema: z.null(),
    });

    expect(result).toEqual({ data: null, ok: true });
  });

  it("rejects a 204 response where a body was required", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));

    const result = await apiRequest({ path: "/auth/me", schema: userSchema });

    expect(result).toMatchObject({ code: "invalid_api_response", ok: false });
  });

  it("treats an unparsable success body as an invalid response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));

    const result = await apiRequest({ path: "/auth/me", schema: userSchema });

    expect(result).toMatchObject({ code: "invalid_api_response", ok: false });
  });
});
