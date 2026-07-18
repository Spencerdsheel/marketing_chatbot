/**
 * Shared bounded backoff/retry utility (S14.6 decision 1, scope item 1).
 *
 * `withRetry` wraps one of the existing one-attempt network functions
 * (`mintVisitorSession` / `sendTurn` / `submitLead` / `fetchSlots` /
 * `bookSlot` — all `{ ok:true; ... } | { ok:false; error }` shapes) and adds
 * a **bounded**, exponential-backoff-plus-jitter retry loop around it. It
 * does not change what those functions do internally — they remain single
 * attempts; this is the layer that decides whether to call them again.
 *
 * Load-bearing invariants (CLAUDE.md §3 resilience doctrine + S14.6
 * constraint 1): a small max-attempt cap, exponential backoff with jitter,
 * a non-retryable-error fast path (return immediately, no wasted attempt),
 * and only one attempt ever in flight at a time (this function does not
 * start attempt N+1 until attempt N's promise has settled). The clock/sleep
 * are injectable so tests never wait real time.
 */

/** The minimal error shape retry needs to see — every *Error type in this
 * codebase (AdmissionError/TurnError/LeadError/ScheduleError) already
 * satisfies this structurally. */
export interface RetryableError {
  readonly errorCode: string;
  readonly status: number | null;
  readonly retryAfterSeconds?: number | null;
}

export interface WithRetryOptions {
  /** Maximum number of attempts (including the first). Default 4. */
  maxAttempts?: number;
  /** Base delay in ms for the exponential schedule (attempt 1 -> attempt 2). Default 500. */
  baseDelayMs?: number;
  /** Upper bound on any single computed delay, before jitter. Default 8000. */
  maxDelayMs?: number;
  /** Injectable sleep — tests supply a fake that resolves instantly and records the delay. */
  sleep?: (ms: number) => Promise<void>;
  /** Injectable jitter source in [0, 1). Tests supply a deterministic fake. Default Math.random. */
  random?: () => number;
  /** Called before each wait with the computed delay (ms) and the attempt about to be retried. Useful for UI status. */
  onRetry?: (info: { attempt: number; delayMs: number; error: RetryableError }) => void;
  /**
   * Checked before each attempt (including the first) and again after each
   * backoff wait. When it returns true, `withRetry` stops immediately and
   * returns the last result it has (or a synthetic ABORTED error if no
   * attempt has run yet) without issuing another fetch — the zombie-retry
   * guard callers wire to "am I unmounted?" (S14.6 decision 7).
   */
  shouldAbort?: () => boolean;
}

/** Returned when `shouldAbort` is already true before any attempt could run. */
function abortedResult<TResult extends { ok: boolean; error?: RetryableError }>(): TResult {
  return {
    ok: false,
    error: {
      errorCode: "ABORTED",
      status: null,
      retryAfterSeconds: null,
    },
  } as TResult;
}

/**
 * Error codes that will never succeed on retry (business/validation errors,
 * or a local guard like NO_SESSION). Retrying these would storm the backend
 * with requests that cannot succeed and delay the honest failure the
 * visitor needs to see (S14.6 decision 1/2).
 */
const NON_RETRYABLE_ERROR_CODES: ReadonlySet<string> = new Set([
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
]);

/**
 * Classify whether an error is worth retrying: network errors (no response
 * was received), 5xx server errors, and 429 rate-limiting are retryable;
 * everything else (explicit non-retryable codes, and any other 4xx we don't
 * recognize) is not, per decision 1/2.
 */
export function isRetryableError(error: RetryableError): boolean {
  if (NON_RETRYABLE_ERROR_CODES.has(error.errorCode)) return false;
  if (error.status === null) return true; // network error / no response
  if (error.status === 429) return true;
  if (error.status >= 500) return true;
  return false;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Compute the delay before the next attempt: exponential backoff off
 * `baseDelayMs` (doubling each attempt), capped at `maxDelayMs`, with full
 * jitter (a random value in [0, computed]) so many widgets on many pages
 * don't retry in lockstep. When the failing error carries a server
 * `retryAfterSeconds`, the wait is the max of that (in ms) and the
 * computed backoff — the server signal is a floor, never undercut
 * (decision 3).
 */
export function computeDelayMs(
  attempt: number,
  error: RetryableError,
  options: Required<Pick<WithRetryOptions, "baseDelayMs" | "maxDelayMs" | "random">>,
): number {
  const exponential = Math.min(options.baseDelayMs * 2 ** (attempt - 1), options.maxDelayMs);
  const jittered = exponential * options.random();
  const serverFloorMs =
    typeof error.retryAfterSeconds === "number" && error.retryAfterSeconds !== null
      ? error.retryAfterSeconds * 1000
      : 0;
  return Math.max(jittered, serverFloorMs);
}

/**
 * Run `fn` with bounded retry. `fn` takes no arguments — callers close over
 * whatever config/input they need (`() => sendTurn(config, input)`), which
 * keeps this utility generic across all five network functions without a
 * shared input shape.
 *
 * Returns the last result — either the first success, or the final failed
 * result once the attempt cap is reached. Never throws (the wrapped
 * functions already never throw); never retries a non-retryable error;
 * never has two attempts in flight at once (each attempt is awaited fully
 * before deciding whether to retry).
 */
export async function withRetry<TResult extends { ok: boolean; error?: RetryableError }>(
  fn: () => Promise<TResult>,
  options: WithRetryOptions = {},
): Promise<TResult> {
  const maxAttempts = options.maxAttempts ?? 4;
  const baseDelayMs = options.baseDelayMs ?? 500;
  const maxDelayMs = options.maxDelayMs ?? 8000;
  const sleep = options.sleep ?? defaultSleep;
  const random = options.random ?? Math.random;
  const shouldAbort = options.shouldAbort ?? (() => false);

  if (shouldAbort()) return abortedResult<TResult>();

  let attempt = 0;
  let lastResult: TResult;

  for (;;) {
    attempt += 1;
    lastResult = await fn();

    if (lastResult.ok) return lastResult;

    const error = lastResult.error as RetryableError;
    if (!isRetryableError(error)) return lastResult;
    if (attempt >= maxAttempts) return lastResult;
    if (shouldAbort()) return lastResult;

    const delayMs = computeDelayMs(attempt, error, { baseDelayMs, maxDelayMs, random });
    options.onRetry?.({ attempt, delayMs, error });
    await sleep(delayMs);

    if (shouldAbort()) return lastResult;
  }
}
