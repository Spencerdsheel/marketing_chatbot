/**
 * Opt-in browser TTS greeting (S14.5 decision 5, scope item 6).
 *
 * Thin wrapper over the native Web Speech API (`window.speechSynthesis` +
 * `SpeechSynthesisUtterance`) — zero-dependency, zero-backend, purely
 * client-side. No third-party TTS service, no audio assets, no autoplay.
 *
 * Hard constraint: this module must NEVER be the reason speech happens
 * without a preceding user gesture (browsers enforce this; unsolicited
 * audio on a third-party host page is hostile). Callers are responsible for
 * only invoking `speakGreeting()` from within a user-gesture-triggered
 * handler (the panel's first open) — this module does not and cannot
 * enforce that on its own, but every code path here is otherwise inert
 * until called.
 *
 * Capability check + try/catch is load-bearing: `window.speechSynthesis`
 * may be absent (older/locked-down browsers), and `speak()`/`cancel()` can
 * throw (blocked by browser policy, permissions, etc.) — any failure here
 * must degrade to a harmless no-op and never throw into the host page or
 * affect chat.
 */

/** Baked-in greeting text (decision 5) — no server-driven/per-tenant config yet (flagged). */
export const TTS_GREETING_TEXT = "Hi, I'm your assistant. How can I help?";

function getSpeechSynthesis(): SpeechSynthesis | null {
  if (typeof window === "undefined") return null;
  const synth = window.speechSynthesis;
  if (!synth || typeof synth.speak !== "function") return null;
  return synth;
}

/**
 * Speak the baked-in greeting exactly once, if the Web Speech API is
 * available. Callers gate this on "first open in this page session" and
 * "not muted" — this function itself does not track either; it only
 * guarantees capability-checked, exception-safe speech.
 */
export function speakGreeting(): void {
  const synth = getSpeechSynthesis();
  if (!synth) return;

  try {
    const Utterance = window.SpeechSynthesisUtterance;
    if (typeof Utterance !== "function") return;
    const utterance = new Utterance(TTS_GREETING_TEXT);
    synth.speak(utterance);
  } catch {
    // Silent degradation — speech failing must never break or throw into
    // the host page, and must never affect chat (decision 5 / load-bearing
    // constraint 2).
  }
}

/** Cancel any in-progress/queued speech (e.g. on mute toggle or panel close). */
export function cancel(): void {
  const synth = getSpeechSynthesis();
  if (!synth) return;

  try {
    synth.cancel();
  } catch {
    // Silent degradation, same rationale as speakGreeting.
  }
}
