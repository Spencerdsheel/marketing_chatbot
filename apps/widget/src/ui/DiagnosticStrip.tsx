/**
 * `data-debug="true"` opt-in (S14.1 decision 3.6): renders inside the
 * shadow root so an integrator can self-diagnose a misconfigured
 * key/Origin without opening the console. Never shown to real visitors by
 * default.
 *
 * Moved out of the now-deleted `Placeholder.tsx` (S14.2 decision 1): the
 * inert S14.1 placeholder badge is superseded by the real launcher inside
 * `ChatWidget`, but this diagnostic strip is still needed by `entry.tsx`'s
 * failure path.
 */
export interface DiagnosticStripProps {
  errorCode: string;
  message: string;
  correlationId: string | null;
}

export function DiagnosticStrip({ errorCode, message, correlationId }: DiagnosticStripProps) {
  return (
    <div className="cw-diagnostic" role="alert">
      <strong>[chatbot-widget debug]</strong>
      <div>error_code: {errorCode}</div>
      <div>message: {message}</div>
      <div>correlation_id: {correlationId ?? "(none)"}</div>
    </div>
  );
}
