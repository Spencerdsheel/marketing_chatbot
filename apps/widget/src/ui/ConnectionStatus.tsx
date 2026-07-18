/**
 * Honest connection-status indicator (S14.6 decisions 4/6, scope item 5).
 *
 * A small, unobtrusive affordance rendered in the panel header. Reflects
 * real state only — it never says "connected"/shows nothing-is-wrong chrome
 * during a retrying/rate-limited/offline state, and never implies success
 * that didn't happen. Friendly, jargon-free copy; no raw `error_code`/
 * `correlation_id` (those stay in the console per the existing logging
 * convention — decision 6). Each degraded state that has stopped
 * auto-retrying exposes a manual Retry button (decision 4).
 *
 * A single `role="status" aria-live="polite"` region carries the current
 * state's text — it stays mounted across every state (including `online`,
 * where it is empty) so a screen reader reliably picks up the *transition*
 * into/out of a degraded state, per S14.5's polite-for-status /
 * assertive-for-errors split (the per-message error line already uses
 * `role="alert"` — this component only ever announces politely, since a
 * retry/backoff isn't itself an actionable error the way a failed send is).
 * `online` renders no visible chrome (decision 4) — the default,
 * unremarkable case.
 */
export type ConnectionState =
  | { kind: "online" }
  | { kind: "retrying" }
  | { kind: "rate-limited"; retryAfterSeconds: number | null }
  | { kind: "reconnecting-session" }
  | { kind: "offline" }
  | { kind: "session-expired" };

export interface ConnectionStatusProps {
  state: ConnectionState;
  onRetry: () => void;
}

/** Friendly, honest, jargon-free copy per state (decision 6). Never a raw error_code/correlation_id. */
function describeState(state: ConnectionState): { text: string; showRetry: boolean } {
  switch (state.kind) {
    case "online":
      return { text: "", showRetry: false };
    case "retrying":
      return { text: "Reconnecting…", showRetry: false };
    case "rate-limited":
      return {
        text:
          state.retryAfterSeconds !== null
            ? `You're sending messages a bit fast — trying again in ${state.retryAfterSeconds}s`
            : "You're sending messages a bit fast — trying again shortly",
        showRetry: false,
      };
    case "reconnecting-session":
      return { text: "Your session expired — reconnecting…", showRetry: false };
    case "offline":
      return { text: "We can't reach chat right now.", showRetry: true };
    case "session-expired":
      return { text: "Your session expired. Please reload the page to continue.", showRetry: false };
  }
}

export function ConnectionStatus({ state, onRetry }: ConnectionStatusProps) {
  const { text, showRetry } = describeState(state);

  return (
    <div className="cw-status" role="status" aria-live="polite">
      {text && <span className="cw-status-text">{text}</span>}
      {showRetry && (
        <button type="button" className="cw-status-retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
