import { NextRequest } from "next/server";

import { middleware } from "./middleware";
import { REFRESH_COOKIE } from "./lib/session-cookies";

function request(path: string, refreshToken?: string): NextRequest {
  const nextRequest = new NextRequest(new URL(`http://localhost:3000${path}`));
  if (refreshToken !== undefined) {
    nextRequest.cookies.set(REFRESH_COOKIE, refreshToken);
  }
  return nextRequest;
}

describe("route protection middleware", () => {
  it("redirects unauthenticated visitors to login with a next parameter", () => {
    const response = middleware(request("/workspaces/abc/members?tab=roles"));

    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/workspaces/abc/members?tab=roles");
  });

  it("treats an empty refresh cookie as unauthenticated", () => {
    const response = middleware(request("/workspaces", ""));

    expect(response.headers.get("location")).toContain("/login");
  });

  it("lets a session through to the protected page", () => {
    const response = middleware(request("/workspaces", "refresh-token"));

    expect(response.headers.get("location")).toBeNull();
    expect(response.status).toBe(200);
  });

  it("leaves public routes untouched", () => {
    const response = middleware(request("/login"));

    expect(response.headers.get("location")).toBeNull();
  });

  it("does not protect paths that merely share a prefix", () => {
    const response = middleware(request("/workspaces-marketing"));

    expect(response.headers.get("location")).toBeNull();
  });
});
