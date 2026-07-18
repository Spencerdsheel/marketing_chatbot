import { describe, expect, it, vi } from "vitest";

import { computeDelayMs, isRetryableError, withRetry, type RetryableError } from "./retry";

/** A minimal result shape matching every network module's `{ ok } | { ok:false; error }` contract. */
interface FakeResult {
  ok: boolean;
  error?: RetryableError;
  value?: string;
}

function err(partial: Partial<RetryableError> & { errorCode: string }): RetryableError {
  return { status: null, retryAfterSeconds: null, ...partial };
}

/** A deterministic, instant fake sleep that records every requested delay — tests never wait real time. */
function fakeClock() {
  const delays: number[] = [];
  const sleep = (ms: number) => {
    delays.push(ms);
    return Promise.resolve();
  };
  return { delays, sleep };
}

describe("isRetryableError", () => {
  it("classifies network errors (status null) as retryable", () => {
    expect(isRetryableError(err({ errorCode: "NETWORK_ERROR", status: null }))).toBe(true);
  });

  it("classifies 5xx as retryable", () => {
    expect(isRetryableError(err({ errorCode: "LLM_ERROR", status: 502 }))).toBe(true);
    expect(isRetryableError(err({ errorCode: "INTERNAL_ERROR", status: 500 }))).toBe(true);
  });

  it("classifies 429 as retryable", () => {
    expect(isRetryableError(err({ errorCode: "RATE_LIMITED", status: 429 }))).toBe(true);
  });

  it.each([
    "INVALID_CLIENT_KEY",
    "ORIGIN_NOT_ALLOWED",
    "TENANT_DISABLED",
    "CONSENT_REQUIRED",
    "SLOT_UNAVAILABLE",
    "VALIDATION_ERROR",
    "INVALID_RESPONSE_SHAPE",
    "NO_SESSION",
    "LLM_NOT_CONFIGURED",
    "RAG_EMBEDDING_NOT_CONFIGURED",
    "CALENDAR_SYNC_FAILED",
    "MISSING_CLIENT_KEY",
  ])("classifies %s as non-retryable regardless of status", (errorCode) => {
    expect(isRetryableError(err({ errorCode, status: 422 }))).toBe(false);
  });

  it("classifies an unrecognized 4xx as non-retryable", () => {
    expect(isRetryableError(err({ errorCode: "SOME_OTHER_4XX", status: 418 }))).toBe(false);
  });
});

describe("computeDelayMs", () => {
  it("grows exponentially with the attempt number (jitter fixed at 1 for determinism)", () => {
    const opts = { baseDelayMs: 500, maxDelayMs: 8000, random: () => 1 };
    const d1 = computeDelayMs(1, err({ errorCode: "NETWORK_ERROR" }), opts);
    const d2 = computeDelayMs(2, err({ errorCode: "NETWORK_ERROR" }), opts);
    const d3 = computeDelayMs(3, err({ errorCode: "NETWORK_ERROR" }), opts);
    expect(d1).toBe(500);
    expect(d2).toBe(1000);
    expect(d3).toBe(2000);
  });

  it("caps the exponential growth at maxDelayMs", () => {
    const opts = { baseDelayMs: 500, maxDelayMs: 1200, random: () => 1 };
    const d10 = computeDelayMs(10, err({ errorCode: "NETWORK_ERROR" }), opts);
    expect(d10).toBe(1200);
  });

  it("applies jitter: a lower random() yields a lower delay than a higher one, same attempt", () => {
    const low = computeDelayMs(3, err({ errorCode: "NETWORK_ERROR" }), {
      baseDelayMs: 500,
      maxDelayMs: 8000,
      random: () => 0.1,
    });
    const high = computeDelayMs(3, err({ errorCode: "NETWORK_ERROR" }), {
      baseDelayMs: 500,
      maxDelayMs: 8000,
      random: () => 0.9,
    });
    expect(low).toBeLessThan(high);
  });

  it("respects retryAfterSeconds as a floor: waits at least that long even if backoff schedule is shorter", () => {
    // attempt 1's raw exponential (with random()=0 -> jittered delay 0) would be far below 12s.
    const delay = computeDelayMs(1, err({ errorCode: "RATE_LIMITED", retryAfterSeconds: 12 }), {
      baseDelayMs: 500,
      maxDelayMs: 8000,
      random: () => 0,
    });
    expect(delay).toBe(12000);
  });

  it("never undercuts retryAfterSeconds even when the backoff schedule is nominally larger but jitter zeroes it", () => {
    const delay = computeDelayMs(4, err({ errorCode: "RATE_LIMITED", retryAfterSeconds: 3 }), {
      baseDelayMs: 500,
      maxDelayMs: 8000,
      random: () => 0,
    });
    expect(delay).toBeGreaterThanOrEqual(3000);
  });
});

describe("withRetry", () => {
  it("a function that fails with a network error then succeeds is retried and ultimately returns ok:true within the cap", async () => {
    const clock = fakeClock();
    const fn = vi
      .fn<() => Promise<FakeResult>>()
      .mockResolvedValueOnce({ ok: false, error: err({ errorCode: "NETWORK_ERROR" }) })
      .mockResolvedValueOnce({ ok: true, value: "done" });

    const result = await withRetry(fn, { sleep: clock.sleep, random: () => 0.5 });

    expect(result).toEqual({ ok: true, value: "done" });
    expect(fn).toHaveBeenCalledTimes(2);
    expect(clock.delays.length).toBe(1);
  });

  it("a function that always fails with a network/5xx/429 error is retried EXACTLY up to the cap, then returns the last typed error", async () => {
    const clock = fakeClock();
    const failure: FakeResult = { ok: false, error: err({ errorCode: "NETWORK_ERROR" }) };
    const fn = vi.fn<() => Promise<FakeResult>>().mockResolvedValue(failure);

    const result = await withRetry(fn, { maxAttempts: 4, sleep: clock.sleep, random: () => 0.5 });

    expect(result).toEqual(failure);
    // Exact attempt count assertion — no over-retrying, no infinite loop.
    expect(fn).toHaveBeenCalledTimes(4);
    // 3 waits between 4 attempts.
    expect(clock.delays.length).toBe(3);
  });

  it.each([
    "INVALID_CLIENT_KEY",
    "CONSENT_REQUIRED",
    "SLOT_UNAVAILABLE",
    "INVALID_RESPONSE_SHAPE",
    "NO_SESSION",
  ])("a non-retryable error (%s) is returned immediately with exactly one attempt, no retry", async (errorCode) => {
    const clock = fakeClock();
    const failure: FakeResult = { ok: false, error: err({ errorCode, status: 422 }) };
    const fn = vi.fn<() => Promise<FakeResult>>().mockResolvedValue(failure);

    const result = await withRetry(fn, { sleep: clock.sleep });

    expect(result).toEqual(failure);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(clock.delays.length).toBe(0);
  });

  it("backoff delays increase exponentially and include jitter, asserted against the injected clock", async () => {
    const clock = fakeClock();
    const failure: FakeResult = { ok: false, error: err({ errorCode: "NETWORK_ERROR" }) };
    const fn = vi.fn<() => Promise<FakeResult>>().mockResolvedValue(failure);

    await withRetry(fn, { maxAttempts: 4, baseDelayMs: 500, maxDelayMs: 8000, sleep: clock.sleep, random: () => 1 });

    // random()=1 -> jitter factor 1 -> exact exponential ceiling per attempt.
    expect(clock.delays).toEqual([500, 1000, 2000]);
  });

  it("when the error carries retryAfterSeconds, the wait is at least that value (max of header and schedule)", async () => {
    const clock = fakeClock();
    const fn = vi
      .fn<() => Promise<FakeResult>>()
      .mockResolvedValueOnce({
        ok: false,
        error: err({ errorCode: "RATE_LIMITED", status: 429, retryAfterSeconds: 12 }),
      })
      .mockResolvedValueOnce({ ok: true, value: "done" });

    await withRetry(fn, { sleep: clock.sleep, random: () => 0, baseDelayMs: 500, maxDelayMs: 8000 });

    expect(clock.delays[0]).toBeGreaterThanOrEqual(12000);
  });

  it("only one attempt is ever in flight at a time (fn is not called again until the prior call's promise settles)", async () => {
    const clock = fakeClock();
    let inFlight = 0;
    let maxConcurrent = 0;
    const fn = vi.fn<() => Promise<FakeResult>>().mockImplementation(async () => {
      inFlight += 1;
      maxConcurrent = Math.max(maxConcurrent, inFlight);
      await Promise.resolve();
      inFlight -= 1;
      return { ok: false, error: err({ errorCode: "NETWORK_ERROR" }) };
    });

    await withRetry(fn, { maxAttempts: 3, sleep: clock.sleep, random: () => 0.1 });

    expect(maxConcurrent).toBe(1);
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("calls onRetry before each wait with the attempt number and computed delay", async () => {
    const clock = fakeClock();
    const failure: FakeResult = { ok: false, error: err({ errorCode: "NETWORK_ERROR" }) };
    const fn = vi.fn<() => Promise<FakeResult>>().mockResolvedValue(failure);
    const onRetry = vi.fn();

    await withRetry(fn, { maxAttempts: 3, sleep: clock.sleep, random: () => 0.5, onRetry });

    expect(onRetry).toHaveBeenCalledTimes(2);
    expect(onRetry.mock.calls[0]?.[0]).toMatchObject({ attempt: 1 });
    expect(onRetry.mock.calls[1]?.[0]).toMatchObject({ attempt: 2 });
  });

  it("shouldAbort stops the loop before any further fetch — the zombie-retry guard", async () => {
    const clock = fakeClock();
    let aborted = false;
    const fn = vi.fn<() => Promise<FakeResult>>().mockImplementation(() => {
      // Simulate "the component unmounted while this attempt's backoff was pending".
      aborted = true;
      return Promise.resolve({ ok: false, error: err({ errorCode: "NETWORK_ERROR" }) });
    });

    await withRetry(fn, { maxAttempts: 5, sleep: clock.sleep, random: () => 0.5, shouldAbort: () => aborted });

    // Aborts right after the first attempt sets `aborted = true` — never a second call.
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("shouldAbort true before any attempt returns immediately without calling fn", async () => {
    const clock = fakeClock();
    const fn = vi.fn<() => Promise<FakeResult>>().mockResolvedValue({ ok: true, value: "unused" });

    const result = await withRetry(fn, { sleep: clock.sleep, shouldAbort: () => true });

    expect(fn).not.toHaveBeenCalled();
    expect(result.ok).toBe(false);
  });
});
