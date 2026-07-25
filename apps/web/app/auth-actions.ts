/**
 * Server actions for the authentication flows.
 *
 * Credentials are submitted to server code, exchanged for tokens against the
 * API, and stored in httpOnly cookies; the browser never receives a token.
 * Input is validated here as well as by the API, so obviously bad submissions
 * are rejected without spending a rate-limit slot. Returned state carries the
 * stable error code, never the submitted password.
 */
"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { registerAccount, requestTokenPair, revokeRefreshToken } from "../lib/attest-api";
import { clearSession, readSession, writeSession } from "../lib/session";
import { fieldErrorsFrom, invalidInput, safeRedirectTarget, type FormState } from "./form-state";

const registerSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  fullName: z.string().min(1, "Enter your name.").max(255, "Name is too long."),
  password: z.string().min(8, "Use at least 8 characters.").max(128, "Use at most 128 characters."),
});

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});

/** Create an account, then send the visitor to sign in. */
export async function registerAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const parsed = registerSchema.safeParse({
    email: String(formData.get("email") ?? "").trim(),
    fullName: String(formData.get("fullName") ?? "").trim(),
    password: String(formData.get("password") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const created = await registerAccount(parsed.data);
  if (!created.ok) {
    return { code: created.code, message: created.message, status: "error" };
  }
  redirect("/login?registered=1");
}

/** Exchange credentials for a session, then continue to the requested page. */
export async function loginAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const parsed = loginSchema.safeParse({
    email: String(formData.get("email") ?? "").trim(),
    password: String(formData.get("password") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const tokens = await requestTokenPair(parsed.data);
  if (!tokens.ok) {
    return { code: tokens.code, message: tokens.message, status: "error" };
  }
  await writeSession(
    { accessToken: tokens.data.access_token, refreshToken: tokens.data.refresh_token },
    tokens.data.expires_in,
  );
  redirect(safeRedirectTarget(String(formData.get("next") ?? "")));
}

/** Revoke the refresh token server side, then clear the session cookies. */
export async function logoutAction(): Promise<void> {
  const session = await readSession();
  if (session !== null) {
    await revokeRefreshToken(session.refreshToken);
  }
  await clearSession();
  redirect("/login");
}
