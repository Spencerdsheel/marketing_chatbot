/**
 * Scheduling calls to `GET /public/schedule/slots` + `POST /public/schedule/book`
 * (S14.4 decision 2, scope item 1).
 *
 * `fetchSlots` / `bookSlot` each perform one attempt and Zod-validate the
 * response at the trust boundary, mirroring `lead.ts`'s `submitLead` /
 * `turn.ts`'s `sendTurn` pattern exactly. Never throw — every failure path
 * (network error, non-2xx error envelope, a response that fails Zod
 * validation, or no held visitor session) returns a typed `ScheduleError`.
 * The React layer (`ScheduleCta`) never touches `fetch`/Zod directly. One
 * attempt each, no retry loop (S14.6 owns retry/backoff UX).
 *
 * Load-bearing (S14.4 constraints 1/2/3): `fetchSlots` preserves the raw UTC
 * `starts_at`/`ends_at` strings VERBATIM (never re-derived/reformatted) —
 * the server matches `bookSlot`'s `starts_at` by exact string equality
 * against its recomputed open slots, so any client-side mutation of the
 * instant would break the match. Neither call ever sends a `tenant_id` (it
 * is established server-side, only from the signed visitor session carried
 * in the Bearer token) — the response bodies are leak-free by construction.
 */
import { z } from "zod";

import { authHeader } from "./session";
import type { WidgetConfig } from "./config";

/**
 * Consent copy baked into the bundle for now (S14.4 decision 5, sharing
 * S14.3's client-constants pattern) — there is no per-tenant consent-copy
 * source of truth delivered to the widget at runtime today. `ScheduleCta`'s
 * checkbox label and the submitted `consent` object both reference these
 * constants so what's shown == what's stored. The text names the
 * appointment + reminder side effect specifically (CLAUDE.md §3 "consent
 * before ... scheduling reminders").
 */
export const SCHEDULE_CONSENT_PURPOSE = "appointment_booking";
export const SCHEDULE_CONSENT_TEXT =
  "I agree to book this appointment and consent to my details being stored and to receiving reminders for it.";

// Raw ISO datetime strings, preserved verbatim from the wire — never
// re-parsed into a Date and reformatted, so the exact server string can be
// echoed back to /book untouched.
const SlotResponseSchema = z.object({
  starts_at: z.string().min(1),
  ends_at: z.string().min(1),
});

const SlotsArraySchema = z.array(SlotResponseSchema);

const BookingResponseSchema = z.object({
  event_id: z.string().min(1),
  starts_at: z.string().min(1),
  ends_at: z.string().min(1),
  status: z.string().min(1),
});

export interface Slot {
  /** Raw UTC ISO-8601 string exactly as returned by the server — echo verbatim on booking. */
  startsAt: string;
  endsAt: string;
}

export interface Booking {
  eventId: string;
  startsAt: string;
  endsAt: string;
  status: string;
}

/** The typed shape of the backend's central error envelope, mirroring TurnError/LeadError. */
export interface ScheduleError {
  readonly type: "SCHEDULE_ERROR";
  /** Backend `error_code` (e.g. SLOT_UNAVAILABLE, CONSENT_REQUIRED, CALENDAR_SYNC_FAILED) or a local code for network/parse/auth failures. */
  readonly errorCode: string;
  readonly message: string;
  /** Present when the backend returned a well-formed error envelope. */
  readonly correlationId: string | null;
  /** HTTP status, when a response was received at all. */
  readonly status: number | null;
  /**
   * Best-effort `Retry-After` (seconds), parsed from the response when the
   * browser exposes it (S14.6 decision 3). `null` when unreadable/absent —
   * never a fabricated value.
   */
  readonly retryAfterSeconds: number | null;
}

export type FetchSlotsResult = { ok: true; slots: Slot[] } | { ok: false; error: ScheduleError };
export type BookSlotResult = { ok: true; booking: Booking } | { ok: false; error: ScheduleError };

export interface FetchSlotsInput {
  /** Optional ISO date (YYYY-MM-DD) window bounds; omitted -> server default window. */
  dateFrom?: string;
  dateTo?: string;
}

export interface BookSlotConsent {
  granted: true;
  purpose: string;
  text: string;
}

export interface BookSlotInput {
  /** The exact raw UTC starts_at string returned by fetchSlots — never re-derived. */
  startsAt: string;
  /** The visitor's resolved IANA timezone. */
  timezone: string;
  consent: BookSlotConsent;
  /** Optional linkage to a lead captured earlier in this in-memory page session (decision 6). */
  leadId?: string;
}

interface BackendErrorEnvelope {
  error_code?: unknown;
  message?: unknown;
  correlation_id?: unknown;
}

function parseErrorEnvelope(
  body: unknown,
  fallbackMessage: string,
): { errorCode: string; message: string; correlationId: string | null } {
  if (body && typeof body === "object") {
    const envelope = body as BackendErrorEnvelope;
    const errorCode = typeof envelope.error_code === "string" ? envelope.error_code : "UNKNOWN_ERROR";
    const message = typeof envelope.message === "string" ? envelope.message : fallbackMessage;
    const correlationId = typeof envelope.correlation_id === "string" ? envelope.correlation_id : null;
    return { errorCode, message, correlationId };
  }
  return { errorCode: "UNKNOWN_ERROR", message: fallbackMessage, correlationId: null };
}

function noSessionError(action: string): ScheduleError {
  return {
    type: "SCHEDULE_ERROR",
    errorCode: "NO_SESSION",
    message: `No visitor session is held; cannot ${action}.`,
    correlationId: null,
    status: null,
    retryAfterSeconds: null,
  };
}

function networkError(err: unknown): ScheduleError {
  return {
    type: "SCHEDULE_ERROR",
    errorCode: "NETWORK_ERROR",
    message: err instanceof Error ? err.message : "Network request failed.",
    correlationId: null,
    status: null,
    retryAfterSeconds: null,
  };
}

/** Best-effort `Retry-After` parse (S14.6 decision 3) — see session.ts's twin. */
function parseRetryAfterSeconds(response: Response | null): number | null {
  if (!response) return null;
  const raw = response.headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds;
}

/**
 * Perform the single slot-fetch attempt:
 * `GET {apiBase}/public/schedule/slots[?date_from=...&date_to=...]` — Bearer
 * auth, `credentials:'omit'`, no `tenant_id` (established server-side from
 * the session). A `200 []` (no availability configured) is a valid, non-error
 * result — never treated as a failure. Never throws; every failure path
 * returns a typed ScheduleError. If no visitor session is held
 * (`authHeader()` returns null), returns a typed error and issues no fetch.
 */
export async function fetchSlots(config: WidgetConfig, input: FetchSlotsInput = {}): Promise<FetchSlotsResult> {
  const auth = authHeader();
  if (!auth) {
    return { ok: false, error: noSessionError("fetch open slots") };
  }

  const params = new URLSearchParams();
  if (input.dateFrom) params.set("date_from", input.dateFrom);
  if (input.dateTo) params.set("date_to", input.dateTo);
  const query = params.toString();
  const url = `${config.apiBase}/public/schedule/slots${query ? `?${query}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { ...auth },
      credentials: "omit",
    });
  } catch (err) {
    return { ok: false, error: networkError(err) };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const { errorCode, message, correlationId } = parseErrorEnvelope(body, "Failed to fetch open slots.");
    return {
      ok: false,
      error: {
        type: "SCHEDULE_ERROR",
        errorCode: response.status === 429 ? "RATE_LIMITED" : errorCode,
        message,
        correlationId,
        status: response.status,
        retryAfterSeconds: parseRetryAfterSeconds(response),
      },
    };
  }

  const parsed = SlotsArraySchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: {
        type: "SCHEDULE_ERROR",
        errorCode: "INVALID_RESPONSE_SHAPE",
        message: "Open slots response failed validation.",
        correlationId: null,
        status: response.status,
        retryAfterSeconds: null,
      },
    };
  }

  return {
    ok: true,
    slots: parsed.data.map((s) => ({ startsAt: s.starts_at, endsAt: s.ends_at })),
  };
}

/**
 * Perform the single booking attempt:
 * `POST {apiBase}/public/schedule/book` with
 * `{ starts_at, timezone, consent, lead_id? }` — Bearer auth,
 * `credentials:'omit'`, **never** a `tenant_id`. `starts_at` must be the
 * exact raw string a prior `fetchSlots` call returned (this function does
 * not re-derive or reformat it). Never throws; every failure path (network,
 * non-2xx envelope incl. `SLOT_UNAVAILABLE`/`CONSENT_REQUIRED`/
 * `CALENDAR_SYNC_FAILED`, Zod-mismatch, no session) returns a typed
 * ScheduleError — never a fabricated booking. One attempt, no retry loop
 * (S14.6 owns retry/backoff UX).
 */
export async function bookSlot(config: WidgetConfig, input: BookSlotInput): Promise<BookSlotResult> {
  const auth = authHeader();
  if (!auth) {
    return { ok: false, error: noSessionError("book this slot") };
  }

  let response: Response;
  try {
    response = await fetch(`${config.apiBase}/public/schedule/book`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      credentials: "omit",
      body: JSON.stringify({
        starts_at: input.startsAt,
        timezone: input.timezone,
        consent: input.consent,
        ...(input.leadId ? { lead_id: input.leadId } : {}),
      }),
    });
  } catch (err) {
    return { ok: false, error: networkError(err) };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const { errorCode, message, correlationId } = parseErrorEnvelope(body, "Booking failed.");
    return {
      ok: false,
      error: {
        type: "SCHEDULE_ERROR",
        errorCode: response.status === 429 ? "RATE_LIMITED" : errorCode,
        message,
        correlationId,
        status: response.status,
        retryAfterSeconds: parseRetryAfterSeconds(response),
      },
    };
  }

  const parsed = BookingResponseSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: {
        type: "SCHEDULE_ERROR",
        errorCode: "INVALID_RESPONSE_SHAPE",
        message: "Booking response failed validation.",
        correlationId: null,
        status: response.status,
        retryAfterSeconds: null,
      },
    };
  }

  return {
    ok: true,
    booking: {
      eventId: parsed.data.event_id,
      startsAt: parsed.data.starts_at,
      endsAt: parsed.data.ends_at,
      status: parsed.data.status,
    },
  };
}
