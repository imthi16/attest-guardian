/**
 * Route protection for authenticated pages.
 *
 * The middleware performs a cheap cookie presence check so unauthenticated
 * visitors are redirected before a page renders, preserving where they were
 * heading. It is not the authorization boundary: a forged or stale cookie is
 * still rejected by the API on every request, and pages re-verify the session
 * server side before showing tenant content.
 */
import { NextResponse, type NextRequest } from "next/server";

import { REFRESH_COOKIE } from "./lib/session-cookies";

const PROTECTED_PREFIXES = ["/workspaces"];

export function middleware(request: NextRequest): NextResponse {
  const { nextUrl } = request;
  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => nextUrl.pathname === prefix || nextUrl.pathname.startsWith(`${prefix}/`),
  );
  if (!isProtected) {
    return NextResponse.next();
  }

  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (refreshToken !== undefined && refreshToken !== "") {
    return NextResponse.next();
  }

  const login = new URL("/login", nextUrl.origin);
  login.searchParams.set("next", `${nextUrl.pathname}${nextUrl.search}`);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/workspaces", "/workspaces/:path*"],
};
