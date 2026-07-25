/**
 * Server-side session handling.
 *
 * Tokens live only in httpOnly, SameSite=Lax cookies that server code reads;
 * no access or refresh token is ever exposed to client JavaScript, so an XSS
 * foothold cannot exfiltrate a session. Access tokens are short lived, so
 * `authorizedRequest` transparently spends the refresh token once when the
 * API rejects an expired access token, and clears the session when that
 * refresh also fails. UI role checks are advisory only: every request still
 * carries the bearer token and the API re-authorizes it.
 */
import { cookies } from "next/headers";
import type { z } from "zod";

import { apiRequest, type ApiResult } from "./api-client";
import { tokenPairSchema } from "./contracts";
import {
  ACCESS_COOKIE,
  ACTIVE_WORKSPACE_COOKIE,
  REFRESH_COOKIE,
  SESSION_COOKIES,
} from "./session-cookies";

/** Refresh cookie lifetime; mirrors the API's default refresh-token TTL. */
const REFRESH_MAX_AGE_SECONDS = 14 * 24 * 60 * 60;

type CookieStore = Awaited<ReturnType<typeof cookies>>;

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    maxAge,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  } as const;
}

export type SessionTokens = Readonly<{ accessToken: string; refreshToken: string }>;

/**
 * Persist tokens when the caller may write cookies.
 *
 * Next.js only allows cookie mutation inside a Server Action or Route Handler;
 * during a page render the store is read-only and `set` throws. A rotation
 * triggered by a page render must therefore still be usable, so the write is
 * best-effort and the caller proceeds with the token it was given. The cookie
 * is then refreshed on the next action or route-handler request, and until then
 * the stale access cookie simply triggers another rotation. Returning `false`
 * lets callers distinguish "not persisted" from "failed".
 */
async function tryWriteCookies(mutate: (store: CookieStore) => void): Promise<boolean> {
  try {
    mutate(await cookies());
    return true;
  } catch {
    return false;
  }
}

function setTokens(store: CookieStore, tokens: SessionTokens, expiresInSeconds: number): void {
  store.set(ACCESS_COOKIE, tokens.accessToken, cookieOptions(expiresInSeconds));
  store.set(REFRESH_COOKIE, tokens.refreshToken, cookieOptions(REFRESH_MAX_AGE_SECONDS));
}

function deleteTokens(store: CookieStore): void {
  for (const name of SESSION_COOKIES) {
    store.set(name, "", cookieOptions(0));
  }
}

/** Persist a freshly issued token pair in httpOnly cookies. */
export async function writeSession(tokens: SessionTokens, expiresInSeconds: number): Promise<void> {
  setTokens(await cookies(), tokens, expiresInSeconds);
}

/** Remove every session cookie, including the remembered workspace. */
export async function clearSession(): Promise<void> {
  await tryWriteCookies(deleteTokens);
}

export async function readSession(): Promise<SessionTokens | null> {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_COOKIE)?.value;
  if (refreshToken === undefined || refreshToken === "") {
    return null;
  }
  return { accessToken: store.get(ACCESS_COOKIE)?.value ?? "", refreshToken };
}

export async function readActiveWorkspaceId(): Promise<string | null> {
  const store = await cookies();
  return store.get(ACTIVE_WORKSPACE_COOKIE)?.value ?? null;
}

export async function writeActiveWorkspaceId(workspaceId: string): Promise<void> {
  const store = await cookies();
  store.set(ACTIVE_WORKSPACE_COOKIE, workspaceId, cookieOptions(REFRESH_MAX_AGE_SECONDS));
}

/** Exchange the refresh token for a new pair, or clear the session on failure. */
async function rotateTokens(refreshToken: string): Promise<string | null> {
  const refreshed = await apiRequest({
    body: { refresh_token: refreshToken },
    method: "POST",
    path: "/auth/refresh",
    schema: tokenPairSchema,
  });
  if (!refreshed.ok) {
    await tryWriteCookies(deleteTokens);
    return null;
  }
  await tryWriteCookies((store) =>
    setTokens(
      store,
      { accessToken: refreshed.data.access_token, refreshToken: refreshed.data.refresh_token },
      refreshed.data.expires_in,
    ),
  );
  return refreshed.data.access_token;
}

/** Signals that the caller must send the visitor back to the login page. */
export const SESSION_EXPIRED = "session_expired";

export type AuthorizedFailure = Readonly<{
  ok: false;
  code: string;
  message: string;
  status: number;
}>;

export type AuthorizedResult<T> = Readonly<{ ok: true; data: T }> | AuthorizedFailure;

function expired(message: string): AuthorizedFailure {
  return { ok: false, code: SESSION_EXPIRED, message, status: 401 };
}

/**
 * Call the API with the session's access token, refreshing once if it expired.
 *
 * A `SESSION_EXPIRED` code means the session cookies have already been
 * cleared and the visitor must sign in again.
 */
export async function authorizedRequest<T>(request: {
  body?: unknown;
  method?: "DELETE" | "GET" | "PATCH" | "POST";
  path: string;
  schema: z.ZodType<T>;
}): Promise<AuthorizedResult<T>> {
  const session = await readSession();
  if (session === null) {
    return expired("Please sign in to continue.");
  }

  const attempt = (accessToken: string): Promise<ApiResult<T>> =>
    apiRequest({ ...request, accessToken });

  let result = await attempt(session.accessToken);
  if (!result.ok && result.status === 401) {
    const accessToken = await rotateTokens(session.refreshToken);
    if (accessToken === null) {
      return expired("Your session expired. Please sign in again.");
    }
    result = await attempt(accessToken);
    if (!result.ok && result.status === 401) {
      await clearSession();
      return expired("Your session expired. Please sign in again.");
    }
  }

  return result.ok
    ? { ok: true, data: result.data }
    : { ok: false, code: result.code, message: result.message, status: result.status };
}
