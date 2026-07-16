/**
 * Shared file-constraint constants + helpers for the knowledge upload screen
 * (S13.3 decision 5). Sourced verbatim from the real backend values, not
 * invented:
 *  - `MAX_UPLOAD_BYTES` mirrors `ingestion_max_upload_bytes`
 *    (services/api/src/api/config.py:77).
 *  - `ALLOWED_CONTENT_TYPES` mirrors `_ALLOWED_CONTENT_TYPES`
 *    (services/api/src/api/ingestion/routes.py:39-42).
 * Used by both the client-side pre-check (upload-form.tsx) and the
 * server-action re-check (actions.ts) -- the backend remains the real,
 * authoritative gate in both cases.
 */

export const MAX_UPLOAD_BYTES = 10_485_760;

export const ALLOWED_CONTENT_TYPES = [
  "text/plain",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
] as const;

export const ALLOWED_EXTENSIONS = [".txt", ".docx"] as const;

/** `<input accept>` value: both extensions and MIME types, for maximum
 * browser compatibility (some browsers filter by extension, some by type). */
export const FILE_INPUT_ACCEPT = [...ALLOWED_EXTENSIONS, ...ALLOWED_CONTENT_TYPES].join(",");

/**
 * Run-status terminal-state predicate (S13.3 decision 4). The poll loop
 * stops once a run reaches `succeeded` or `failed`; `queued`/`running` are
 * non-terminal and keep polling.
 */
export function isTerminalRunStatus(status: string): boolean {
  return status === "succeeded" || status === "failed";
}

/**
 * Defensively render `ingestion_runs.errors`, which is loosely typed on the
 * backend as `list[Any] | dict[str, Any] | None` (repository.py:74, 427).
 * Never assumes a fixed shape; never throws. No-silent-fallback (CLAUDE.md
 * §3): this is what actually surfaces the real recorded error to the admin.
 */
export function formatRunErrors(errors: unknown): string {
  if (errors === null || errors === undefined) {
    return "Ingestion failed, but no error detail was recorded.";
  }

  if (Array.isArray(errors)) {
    if (errors.length === 0) {
      return "Ingestion failed, but no error detail was recorded.";
    }
    return errors
      .map((entry) => (typeof entry === "string" ? entry : safeStringify(entry)))
      .join("\n");
  }

  if (typeof errors === "object") {
    return safeStringify(errors);
  }

  return String(errors);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Human-readable MiB rendering for size-limit messages. */
export function formatBytes(bytes: number): string {
  const mib = bytes / (1024 * 1024);
  return `${mib.toFixed(mib < 10 ? 1 : 0)} MiB`;
}

/**
 * Pure, framework-agnostic polling driver (S13.3 decision 4). Extracted out
 * of the status-panel React component so the stop-on-terminal-state and
 * poll-cap behavior is unit-testable with fake timers without a DOM/RTL
 * dependency (this repo has neither wired up).
 *
 * Calls `pollOnce()` immediately, then every `intervalMs`. After each result,
 * `onResult` is invoked with the result and the 1-based poll count so far.
 * Polling stops automatically -- clearing its own interval -- the moment
 * `isTerminal(result)` is true, or once `maxPolls` attempts have completed
 * without a terminal result (in which case `onCapped()` fires once). Returns
 * a `stop()` function for the caller's cleanup (e.g. a React effect's
 * unmount), safe to call multiple times.
 */
export function schedulePolling<T>(opts: {
  pollOnce: () => Promise<T>;
  isTerminal: (result: T) => boolean;
  onResult: (result: T, pollCount: number) => void;
  onCapped?: () => void;
  intervalMs: number;
  maxPolls: number;
}): () => void {
  let stopped = false;
  let count = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  function stop(): void {
    if (stopped) return;
    stopped = true;
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  async function tick(): Promise<void> {
    if (stopped) return;
    const result = await opts.pollOnce();
    if (stopped) return;
    count += 1;
    opts.onResult(result, count);
    if (opts.isTerminal(result)) {
      stop();
      return;
    }
    if (count >= opts.maxPolls) {
      opts.onCapped?.();
      stop();
    }
  }

  void tick();
  timer = setInterval(() => {
    void tick();
  }, opts.intervalMs);

  return stop;
}
