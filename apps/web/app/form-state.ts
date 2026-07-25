/**
 * Shared form-state shape for server actions and the client forms that call
 * them. Kept out of the `"use server"` modules because those may only export
 * async server functions.
 */
import type { z } from "zod";

import { clientErrorCodes } from "../lib/contracts";

export type FormState = Readonly<{
  code?: string;
  fieldErrors?: Readonly<Record<string, string>>;
  message?: string;
  status: "error" | "idle" | "success";
}>;

export const idleState: FormState = { status: "idle" };

/** Reduce a Zod error to one message per field, in field order. */
export function fieldErrorsFrom(error: z.ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues) {
    const field = issue.path[0];
    if (typeof field === "string" && errors[field] === undefined) {
      errors[field] = issue.message;
    }
  }
  return errors;
}

export function invalidInput(fieldErrors: Record<string, string>): FormState {
  return {
    code: clientErrorCodes.validation,
    fieldErrors,
    message: "Please correct the highlighted fields.",
    status: "error",
  };
}

/**
 * Only relative, single-slash paths are honoured after login, so a crafted
 * `next` parameter cannot bounce the visitor to an external origin.
 */
export function safeRedirectTarget(candidate: string | null | undefined): string {
  if (typeof candidate !== "string" || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/workspaces";
  }
  return candidate;
}
