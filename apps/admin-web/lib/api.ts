/**
 * Server-only helper for calling admin-api from Next.js server components /
 * server actions. Centralizes the auth-bridge cookie forwarding (decision 1
 * of S13.1): server-to-server `fetch` calls do NOT ride the browser's
 * cookie jar, so the caller's own `access_token` cookie must be attached
 * manually as a `Cookie` header on every outgoing request.
 */
import "server-only";

import { cookies } from "next/headers";
import { env } from "@/lib/env";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth";

/**
 * Shape of admin-api's error envelope (services/api/src/api/app.py
 * `_error_response`): `{error_code, message, correlation_id}`.
 */
export interface AdminApiErrorBody {
  error_code: string;
  message: string;
  correlation_id: string;
}

/**
 * Typed error thrown by `adminApiFetch` on any non-2xx response. Carries
 * the backend's error envelope verbatim so callers can render
 * `error_code`/`correlation_id` (e.g. in support-facing error states) per
 * the S13.1 spec.
 */
export class AdminApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly correlationId: string;

  constructor(status: number, body: AdminApiErrorBody) {
    super(body.message);
    this.name = "AdminApiError";
    this.status = status;
    this.errorCode = body.error_code;
    this.correlationId = body.correlation_id;
  }
}

/**
 * Call `admin-api` from the server, forwarding the caller's own
 * `access_token` cookie (if present) as a `Cookie` header. Throws
 * `AdminApiError` on any non-2xx response.
 *
 * `path` is relative to `ADMIN_API_BASE_URL`, e.g. `/auth/me`.
 */
export async function adminApiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const cookieStore = await cookies();
  const token = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;

  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Cookie", `${ACCESS_TOKEN_COOKIE}=${token}`);
  }

  const url = `${env.adminApiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;

  const response = await fetch(url, {
    ...init,
    headers,
    // Server-to-server call; never cache auth-sensitive admin data.
    cache: "no-store",
  });

  if (!response.ok) {
    let body: AdminApiErrorBody;
    try {
      body = (await response.json()) as AdminApiErrorBody;
    } catch {
      body = {
        error_code: "UNKNOWN_ERROR",
        message: `admin-api request failed with status ${response.status}.`,
        correlation_id: "",
      };
    }
    throw new AdminApiError(response.status, body);
  }

  return response;
}
