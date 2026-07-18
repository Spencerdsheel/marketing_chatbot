import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WidgetConfig } from "./config";

const authHeaderMock = vi.fn<() => { Authorization: string } | null>();

vi.mock("./session", () => ({
  authHeader: () => authHeaderMock(),
}));

const baseConfig: WidgetConfig = {
  clientKey: "pk_test_123",
  apiBase: "http://localhost:8000",
  mountSelector: null,
  debug: false,
};

function jsonResponse(status: number, body: unknown, extraHeaders?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

describe("fetchSlots", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    authHeaderMock.mockReset();
    authHeaderMock.mockReturnValue({ Authorization: "Bearer jwt.abc.def" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a typed Slot[] preserving the raw UTC starts_at strings verbatim", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        { starts_at: "2026-07-20T09:00:00+00:00", ends_at: "2026-07-20T09:30:00+00:00" },
        { starts_at: "2026-07-20T10:00:00+00:00", ends_at: "2026-07-20T10:30:00+00:00" },
      ]),
    );
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok result");
    expect(result.slots).toEqual([
      { startsAt: "2026-07-20T09:00:00+00:00", endsAt: "2026-07-20T09:30:00+00:00" },
      { startsAt: "2026-07-20T10:00:00+00:00", endsAt: "2026-07-20T10:30:00+00:00" },
    ]);
  });

  it("returns an empty list (ok, not an error) on a mocked 200 []", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok result");
    expect(result.slots).toEqual([]);
  });

  it("sends Authorization: Bearer, credentials: omit, and no tenant_id", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    const { fetchSlots } = await import("./schedule");

    await fetchSlots(baseConfig, {});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/public/schedule/slots");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("omit");
    expect(init.headers).toMatchObject({ Authorization: "Bearer jwt.abc.def" });
    expect(JSON.stringify(init)).not.toContain("tenant_id");
  });

  it("appends date_from/date_to query params when provided", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    const { fetchSlots } = await import("./schedule");

    await fetchSlots(baseConfig, { dateFrom: "2026-07-20", dateTo: "2026-07-27" });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/public/schedule/slots?date_from=2026-07-20&date_to=2026-07-27");
  });

  it("returns a typed ScheduleError on a mocked 401 (no throw)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error_code: "AUTHENTICATION_ERROR", message: "Invalid token.", correlation_id: "corr-3" }),
    );
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("AUTHENTICATION_ERROR");
    expect(result.error.status).toBe(401);
  });

  it("returns a typed INVALID_RESPONSE_SHAPE error when the 200 body fails Zod validation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [{ starts_at: "2026-07-20T09:00:00+00:00" }]));
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("INVALID_RESPONSE_SHAPE");
  });

  it("returns a typed NETWORK_ERROR (no throw) when fetch rejects", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("NETWORK_ERROR");
    expect(result.error.status).toBeNull();
  });

  it("returns a typed NO_SESSION error and issues no fetch when authHeader() is null", async () => {
    authHeaderMock.mockReturnValue(null);
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("NO_SESSION");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a 429 with a readable Retry-After header yields errorCode RATE_LIMITED and the parsed retryAfterSeconds (S14.6 decision 3)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        429,
        { error_code: "RATE_LIMITED", message: "Too many requests.", correlation_id: "corr-9" },
        { "Retry-After": "5" },
      ),
    );
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("RATE_LIMITED");
    expect(result.error.retryAfterSeconds).toBe(5);
  });

  it("a 429 WITHOUT a readable Retry-After header yields retryAfterSeconds:null", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, { error_code: "RATE_LIMITED", message: "Too many requests.", correlation_id: "corr-10" }),
    );
    const { fetchSlots } = await import("./schedule");

    const result = await fetchSlots(baseConfig, {});

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.retryAfterSeconds).toBeNull();
  });
});

describe("bookSlot", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    authHeaderMock.mockReset();
    authHeaderMock.mockReturnValue({ Authorization: "Bearer jwt.abc.def" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("issues one POST echoing the exact starts_at, a valid timezone, truthful consent, and no tenant_id", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        event_id: "evt-1",
        starts_at: "2026-07-20T09:00:00+00:00",
        ends_at: "2026-07-20T09:30:00+00:00",
        status: "booked",
      }),
    );
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "America/New_York",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok result");
    expect(result.booking).toEqual({
      eventId: "evt-1",
      startsAt: "2026-07-20T09:00:00+00:00",
      endsAt: "2026-07-20T09:30:00+00:00",
      status: "booked",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/public/schedule/book");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer jwt.abc.def",
    });

    const parsedBody = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(parsedBody.starts_at).toBe("2026-07-20T09:00:00+00:00");
    expect(parsedBody.timezone).toBe("America/New_York");
    expect(parsedBody.consent).toEqual({
      granted: true,
      purpose: SCHEDULE_CONSENT_PURPOSE,
      text: SCHEDULE_CONSENT_TEXT,
    });
    expect((parsedBody.consent as { text: string }).text).toBe(SCHEDULE_CONSENT_TEXT);
    expect(parsedBody).not.toHaveProperty("tenant_id");
    expect(parsedBody).not.toHaveProperty("lead_id");
  });

  it("includes lead_id when provided", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        event_id: "evt-1",
        starts_at: "2026-07-20T09:00:00+00:00",
        ends_at: "2026-07-20T09:30:00+00:00",
        status: "booked",
      }),
    );
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
      leadId: "lead-42",
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsedBody = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(parsedBody.lead_id).toBe("lead-42");
  });

  it.each(["SLOT_UNAVAILABLE", "CONSENT_REQUIRED", "CALENDAR_SYNC_FAILED"])(
    "returns a typed ScheduleError on a mocked 422 %s (no throw, no fabricated booking)",
    async (errorCode) => {
      fetchMock.mockResolvedValueOnce(
        jsonResponse(422, {
          error_code: errorCode,
          message: "Failed.",
          correlation_id: "corr-1",
        }),
      );
      const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

      const result = await bookSlot(baseConfig, {
        startsAt: "2026-07-20T09:00:00+00:00",
        timezone: "UTC",
        consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
      });

      expect(result.ok).toBe(false);
      if (result.ok) throw new Error("expected error result");
      expect(result.error.errorCode).toBe(errorCode);
      expect(result.error.correlationId).toBe("corr-1");
      expect(result.error.status).toBe(422);
    },
  );

  it("returns a typed ScheduleError on a mocked 401", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error_code: "AUTHENTICATION_ERROR", message: "Invalid token.", correlation_id: "corr-3" }),
    );
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("AUTHENTICATION_ERROR");
    expect(result.error.status).toBe(401);
  });

  it("returns a typed INVALID_RESPONSE_SHAPE error when the 201 body fails Zod validation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(201, { status: "booked" }));
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("INVALID_RESPONSE_SHAPE");
  });

  it("returns a typed NETWORK_ERROR (no throw) when fetch rejects", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("NETWORK_ERROR");
    expect(result.error.status).toBeNull();
  });

  it("returns a typed NO_SESSION error and issues no fetch when authHeader() is null", async () => {
    authHeaderMock.mockReturnValue(null);
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("NO_SESSION");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a 429 with a readable Retry-After header yields errorCode RATE_LIMITED and the parsed retryAfterSeconds (S14.6 decision 3)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        429,
        { error_code: "RATE_LIMITED", message: "Too many requests.", correlation_id: "corr-11" },
        { "Retry-After": "9" },
      ),
    );
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.errorCode).toBe("RATE_LIMITED");
    expect(result.error.retryAfterSeconds).toBe(9);
  });

  it("a 429 WITHOUT a readable Retry-After header yields retryAfterSeconds:null", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(429, { error_code: "RATE_LIMITED", message: "Too many requests.", correlation_id: "corr-12" }),
    );
    const { bookSlot, SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT } = await import("./schedule");

    const result = await bookSlot(baseConfig, {
      startsAt: "2026-07-20T09:00:00+00:00",
      timezone: "UTC",
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected error result");
    expect(result.error.retryAfterSeconds).toBeNull();
  });
});
