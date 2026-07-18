/**
 * Visitor session admission (S14.1 decision 3/4, scope item 3).
 *
 * `mintVisitorSession` performs the one `POST /widget/session` handshake and
 * Zod-validates the response at the trust boundary. The minted token is
 * held in a module-scoped variable ONLY (decision 4) — never
 * sessionStorage/localStorage/cookie — and exposed via `authHeader()`, a
 * clean seam for the S14.2 turn caller. No turn call is wired here.
 */
import { z } from "zod";

import type { WidgetConfig } from "./config";

const SessionResponseSchema = z.object({
  visitor_token: z.string().min(1),
  expires_at: z.string().min(1),
});

export interface VisitorSession {
  visitorToken: string;
  expiresAt: string;
}

/** The typed shape of the backend's central error envelope. */
export interface AdmissionError {
  readonly type: "ADMISSION_ERROR";
  /** Backend `error_code` (e.g. INVALID_CLIENT_KEY, ORIGIN_NOT_ALLOWED, TENANT_DISABLED) or a local code for network/parse failures. */
  readonly errorCode: string;
  readonly message: string;
  /** Present when the backend returned a well-formed error envelope. */
  readonly correlationId: string | null;
  /** HTTP status, when a response was received at all. */
  readonly status: number | null;
  /**
   * Best-effort `Retry-After` (seconds), parsed from the response when the
   * browser exposes it (S14.6 decision 3). `null` when there was no
   * response, the header was absent, or it was unreadable (a real
   * possibility cross-origin today — see the S14.6 Investigation: the
   * gateway does not yet send `Access-Control-Expose-Headers: Retry-After`).
   * Never a fabricated/guessed value.
   */
  readonly retryAfterSeconds: number | null;
}

export type AdmissionResult =
  | { ok: true; session: VisitorSession }
  | { ok: false; error: AdmissionError };

// Module-scoped, in-memory only (decision 4) — gone on page unload, never
// written to sessionStorage/localStorage/cookie, and inaccessible to any
// other script on the host page.
let currentSession: VisitorSession | null = null;

/** The in-memory visitor token, if a session has been minted successfully. */
export function getVisitorSession(): VisitorSession | null {
  return currentSession;
}

/**
 * Clean seam for later sprints (S14.2's turn caller): the Bearer header to
 * attach to authenticated calls. Returns null if no session is held.
 */
export function authHeader(): { Authorization: string } | null {
  if (!currentSession) return null;
  return { Authorization: `Bearer ${currentSession.visitorToken}` };
}

interface BackendErrorEnvelope {
  error_code?: unknown;
  message?: unknown;
  correlation_id?: unknown;
}

function parseErrorEnvelope(body: unknown): { errorCode: string; message: string; correlationId: string | null } {
  if (body && typeof body === "object") {
    const envelope = body as BackendErrorEnvelope;
    const errorCode = typeof envelope.error_code === "string" ? envelope.error_code : "UNKNOWN_ERROR";
    const message = typeof envelope.message === "string" ? envelope.message : "Admission failed.";
    const correlationId = typeof envelope.correlation_id === "string" ? envelope.correlation_id : null;
    return { errorCode, message, correlationId };
  }
  return { errorCode: "UNKNOWN_ERROR", message: "Admission failed.", correlationId: null };
}

/**
 * Best-effort `Retry-After` parse (S14.6 decision 3). Returns `null` when
 * there is no response, the header is absent, or it fails to parse as a
 * non-negative integer — including the real cross-origin case where the
 * browser hides the header because the gateway does not (yet) send
 * `Access-Control-Expose-Headers: Retry-After`. Never guesses a value.
 */
function parseRetryAfterSeconds(response: Response | null): number | null {
  if (!response) return null;
  const raw = response.headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds;
}

/**
 * Perform the single admission attempt: `POST {apiBase}/widget/session`
 * with `{ client_key }` only — no `tenant_id`, `credentials: 'omit'`
 * (Bearer model; the backend sets no Access-Control-Allow-Credentials, so
 * cookies are not usable cross-origin regardless).
 *
 * A single attempt, no retry loop (decision 3 step 5 / S14.6 owns retry
 * UX). Never throws — every failure path returns a typed AdmissionError.
 */
export async function mintVisitorSession(config: WidgetConfig): Promise<AdmissionResult> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBase}/widget/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "omit",
      body: JSON.stringify({ client_key: config.clientKey }),
    });
  } catch (err) {
    return {
      ok: false,
      error: {
        type: "ADMISSION_ERROR",
        errorCode: "NETWORK_ERROR",
        message: err instanceof Error ? err.message : "Network request failed.",
        correlationId: null,
        status: null,
        retryAfterSeconds: null,
      },
    };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const { errorCode, message, correlationId } = parseErrorEnvelope(body);
    return {
      ok: false,
      error: {
        type: "ADMISSION_ERROR",
        errorCode: response.status === 429 ? "RATE_LIMITED" : errorCode,
        message,
        correlationId,
        status: response.status,
        retryAfterSeconds: parseRetryAfterSeconds(response),
      },
    };
  }

  const parsed = SessionResponseSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: {
        type: "ADMISSION_ERROR",
        errorCode: "INVALID_RESPONSE_SHAPE",
        message: "Widget session response failed validation.",
        correlationId: null,
        status: response.status,
        retryAfterSeconds: null,
      },
    };
  }

  currentSession = {
    visitorToken: parsed.data.visitor_token,
    expiresAt: parsed.data.expires_at,
  };
  return { ok: true, session: currentSession };
}
