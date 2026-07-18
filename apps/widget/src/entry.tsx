/**
 * IIFE boot orchestration (S14.1 decision 3, scope item 6).
 *
 * The ONLY module with top-level side effects. Runs synchronously at
 * script-eval time (so `document.currentScript` resolves correctly in
 * config.ts), then performs the async admission handshake.
 *
 * Sequence: config -> mount shell -> mint -> render placeholder / handle
 * failure. A missing client key mounts nothing at all (step 1). Every
 * other failure mounts the shadow host (so the debug strip has somewhere
 * to render) but shows no user-facing UI unless data-debug is set.
 *
 * S14.6 (decision 2, scope item 4): the admission mint is wrapped in
 * `withRetry` so a transient boot-time network blip doesn't permanently
 * kill the widget — bounded attempts with exponential backoff + jitter,
 * then the existing honest hard-stop (no UI / debug strip only) when the
 * cap is hit. A non-retryable admission error (`INVALID_CLIENT_KEY`,
 * `ORIGIN_NOT_ALLOWED`, `TENANT_DISABLED`) is still never retried — the
 * shared `withRetry` classifier already returns those immediately.
 */
import { loadConfig } from "./config";
import { mountWidget } from "./mount";
import { mintVisitorSession, type AdmissionResult } from "./session";
import { withRetry } from "./retry";
import { ChatWidget } from "./ui/ChatWidget";
import { DiagnosticStrip } from "./ui/DiagnosticStrip";

const LOG_PREFIX = "[chatbot-widget]";
/** Bounded boot-admission retry cap (decision 2) — small, matching the turn-retry cap in ChatWidget.tsx. */
const BOOT_ADMISSION_MAX_ATTEMPTS = 4;

async function boot(): Promise<void> {
  const configResult = loadConfig();

  if (!configResult.ok) {
    // Decision 3 step 1: a misconfigured embed must never render a broken
    // box on a client's live site — log loudly, mount nothing.
    console.error(`${LOG_PREFIX} ${configResult.error.message}`);
    return;
  }

  const { config } = configResult;

  // Mount the shadow host unconditionally once we have a valid config, so
  // the (opt-in) debug strip has a place to render on failure too.
  const { reactRoot } = mountWidget(config.mountSelector);

  const admission = await withRetry<AdmissionResult>(() => mintVisitorSession(config), {
    maxAttempts: BOOT_ADMISSION_MAX_ATTEMPTS,
    onRetry: ({ attempt, error }) => {
      console.info(
        `${LOG_PREFIX} admission attempt ${attempt} failed (${error.errorCode}); retrying with backoff…`,
      );
    },
  });

  if (!admission.ok) {
    const { errorCode, message, correlationId, status } = admission.error;
    console.error(
      `${LOG_PREFIX} admission failed: ${errorCode} (status=${status ?? "n/a"}, correlation_id=${correlationId ?? "n/a"}): ${message}`,
    );
    // Decision 3 step 5: no user-facing UI on failure, never fake a
    // working widget. S14.6: the mint above already retried bounded
    // (transient network only, non-retryable errors like
    // INVALID_CLIENT_KEY/ORIGIN_NOT_ALLOWED/TENANT_DISABLED returned
    // immediately) — this is the honest hard-stop once that cap is hit.
    if (config.debug) {
      reactRoot.render(<DiagnosticStrip errorCode={errorCode} message={message} correlationId={correlationId} />);
    }
    return;
  }

  // S14.1 decision 3 step 4 / decision 5 success proof + S14.2 decision 1:
  // the real interactive chat root replaces the S14.1 placeholder at this
  // single render site.
  console.info(`${LOG_PREFIX} visitor session minted, expires_at=${admission.session.expiresAt}`);
  reactRoot.render(<ChatWidget config={config} expiresAt={admission.session.expiresAt} />);
}

// Top-level side effect — the only one in this bundle. Never let a boot
// failure throw into the host page (decision 3 / CLAUDE.md no-silent-
// fallback + fail-invisible doctrine): any unexpected exception is caught
// and logged, not propagated.
void boot().catch((err: unknown) => {
  console.error(`${LOG_PREFIX} unexpected boot error:`, err);
});
