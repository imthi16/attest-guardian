/**
 * Server-only HTTP client for the FastAPI backend.
 *
 * All calls run inside Next.js server code, so the browser never holds a
 * bearer token. Every response is validated against a contract schema and
 * converted into a discriminated `ApiResult`, which makes the caller handle
 * failure explicitly rather than trusting an optimistic shape. Failures carry
 * the API's stable `code` so the UI can distinguish "not a member" from "role
 * too low" from "backend unreachable" without parsing prose.
 */
import type { z } from "zod";

import { apiErrorDetailSchema, clientErrorCodes } from "./contracts";

export type ApiFailure = Readonly<{
  ok: false;
  status: number;
  code: string;
  message: string;
}>;

export type ApiResult<T> = Readonly<{ ok: true; data: T }> | ApiFailure;

/** Origin of the FastAPI service as reachable from the Next.js server. */
export function apiOrigin(): string {
  return process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:8000";
}

const genericMessages: Record<number, string> = {
  400: "The request could not be processed.",
  401: "Your session is no longer valid.",
  403: "You do not have permission to do this.",
  404: "The requested resource does not exist.",
  409: "The request conflicts with the current state.",
  422: "Some of the submitted values are not valid.",
  429: "Too many attempts. Please wait and try again.",
};

function failure(status: number, code: string, message: string): ApiFailure {
  return { ok: false, status, code, message };
}

/**
 * FastAPI returns `{"detail": {...}}` for our own errors and `{"detail": [...]}`
 * for request-validation errors; both are reduced to a stable code here.
 */
function describeError(status: number, payload: unknown): ApiFailure {
  const parsed = apiErrorDetailSchema.safeParse(payload);
  if (parsed.success) {
    return failure(status, parsed.data.detail.code, parsed.data.detail.message);
  }
  const fallback = genericMessages[status] ?? "The request failed.";
  return failure(status, `http_${status}`, fallback);
}

export type ApiRequest<T> = Readonly<{
  accessToken?: string;
  body?: unknown;
  method?: "DELETE" | "GET" | "PATCH" | "POST";
  path: string;
  schema: z.ZodType<T>;
}>;

/**
 * Perform one backend call and validate the result.
 *
 * `schema` describes the success payload; pass a void-like schema for 204
 * responses. Network and parse failures are reported as client-side codes so
 * they are never mistaken for backend decisions.
 */
export async function apiRequest<T>({
  accessToken,
  body,
  method = "GET",
  path,
  schema,
}: ApiRequest<T>): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken !== undefined) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${apiOrigin()}/api/v1${path}`, {
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      headers,
      method,
    });
  } catch {
    return failure(
      503,
      clientErrorCodes.network,
      "The service is unavailable. Please try again shortly.",
    );
  }

  if (response.status === 204) {
    const empty = schema.safeParse(null);
    return empty.success
      ? { ok: true, data: empty.data }
      : failure(
          502,
          clientErrorCodes.invalidResponse,
          "The service returned an unexpected response.",
        );
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    return describeError(response.status, payload);
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    return failure(
      502,
      clientErrorCodes.invalidResponse,
      "The service returned an unexpected response.",
    );
  }
  return { ok: true, data: parsed.data };
}
