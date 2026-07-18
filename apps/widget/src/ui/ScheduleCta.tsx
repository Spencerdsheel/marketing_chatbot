/**
 * Consent-gated inline scheduling flow (S14.4 decisions 1/3/4/5/7, scope item 2).
 *
 * Replaces the `schedule_cta` action stub with a real three-step flow:
 *   (a) loading -> list of open slots (server-returned, shown in the
 *       visitor's local timezone via Intl; an empty list is an honest
 *       "no times available", never a fabricated slot),
 *   (b) selecting a slot advances to a consent-gated confirm step
 *       (unchecked-by-default checkbox, Confirm disabled until checked),
 *   (c) Confirm calls bookSlot echoing the exact server-returned UTC
 *       starts_at + resolved IANA timezone + truthful consent.
 * On a real 201, an honest, non-rebookable confirmation replaces the
 * picker. On failure: SLOT_UNAVAILABLE re-fetches slots and lets the
 * visitor re-pick (never fabricates a confirmation); CALENDAR_SYNC_FAILED/
 * network/other shows an honest error with manual retry; never
 * auto-retry/loop. All state is in-memory only (component state); nothing
 * is keyed/cached by tenant_id; PII/booking is never logged (failure
 * console.error carries only error_code/correlation_id/status).
 *
 * S14.5 audit result (no behavior/consent/request/slot change): this
 * component's step-transition focus management (first slot button on
 * `list`, the confirm heading on `confirm`, the confirmation on `booked`)
 * and its announced loading/empty/error states (`role="status"`/
 * `role="alert"`) were already correct when audited — no changes were
 * needed beyond the shared `:focus-visible` contrast/motion pass in
 * `widgetCss.ts`.
 */
import { useEffect, useRef, useState } from "react";

import type { WidgetConfig } from "../config";
import { SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT, bookSlot, fetchSlots, type Slot } from "../schedule";

const LOG_PREFIX = "[chatbot-widget]";

export interface ScheduleCtaProps {
  config: WidgetConfig;
  /** Optional linkage to a lead captured earlier in this in-memory page session (decision 6). */
  leadId?: string;
}

type Step =
  | { name: "loading" }
  | { name: "list"; slots: Slot[] }
  | { name: "list-error"; message: string }
  | { name: "confirm"; slot: Slot }
  | { name: "booking"; slot: Slot }
  | { name: "booked"; slot: Slot }
  | { name: "book-error"; slot: Slot; message: string };

function resolveVisitorTimeZone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone || "UTC";
  } catch {
    return "UTC";
  }
}

function formatLocalSlotLabel(startsAtIso: string): string {
  const date = new Date(startsAtIso);
  if (Number.isNaN(date.getTime())) return startsAtIso;
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  } catch {
    return date.toISOString();
  }
}

export function ScheduleCta({ config, leadId }: ScheduleCtaProps) {
  const [step, setStep] = useState<Step>({ name: "loading" });
  const [consentChecked, setConsentChecked] = useState(false);
  const visitorTimeZone = useRef(resolveVisitorTimeZone()).current;
  const firstSlotButtonRef = useRef<HTMLButtonElement | null>(null);
  const confirmHeadingRef = useRef<HTMLDivElement | null>(null);
  const confirmationRef = useRef<HTMLDivElement | null>(null);

  async function loadSlots() {
    setStep({ name: "loading" });
    const result = await fetchSlots(config, {});
    if (!result.ok) {
      const { errorCode, correlationId, status } = result.error;
      console.error(
        `${LOG_PREFIX} fetchSlots failed: ${errorCode} (status=${status ?? "n/a"}, correlation_id=${correlationId ?? "n/a"})`,
      );
      setStep({ name: "list-error", message: "Sorry — we couldn't load available times. Please try again." });
      return;
    }
    setStep({ name: "list", slots: result.slots });
  }

  useEffect(() => {
    void loadSlots();
    // Load slots exactly once on mount; loadSlots is intentionally
    // re-invoked imperatively (not via effect deps) on SLOT_UNAVAILABLE.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (step.name === "list") {
      firstSlotButtonRef.current?.focus();
    } else if (step.name === "confirm") {
      confirmHeadingRef.current?.focus();
    } else if (step.name === "booked") {
      confirmationRef.current?.focus();
    }
  }, [step.name]);

  function selectSlot(slot: Slot) {
    setConsentChecked(false);
    setStep({ name: "confirm", slot });
  }

  async function confirmBooking(slot: Slot) {
    setStep({ name: "booking", slot });

    const result = await bookSlot(config, {
      startsAt: slot.startsAt,
      timezone: visitorTimeZone,
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
      ...(leadId ? { leadId } : {}),
    });

    if (!result.ok) {
      const { errorCode, correlationId, status } = result.error;
      // Loud on the developer channel, PII-safe: never the booked time as
      // more than needed, never contact details.
      console.error(
        `${LOG_PREFIX} bookSlot failed: ${errorCode} (status=${status ?? "n/a"}, correlation_id=${correlationId ?? "n/a"})`,
      );

      if (errorCode === "SLOT_UNAVAILABLE") {
        // Honest recovery: the slot was taken between load and confirm —
        // re-fetch so the visitor picks from freshly-open slots. Never show
        // a confirmation for this booking attempt.
        await loadSlots();
        return;
      }

      setStep({
        name: "book-error",
        slot,
        message: "Sorry — we couldn't confirm this booking. Please try again.",
      });
      return;
    }

    setStep({ name: "booked", slot });
  }

  if (step.name === "loading") {
    return (
      <div className="cw-sched" role="status">
        Loading available times…
      </div>
    );
  }

  if (step.name === "list-error") {
    return (
      <div className="cw-sched">
        <div className="cw-sched-error" role="alert">
          {step.message}
        </div>
        <button type="button" className="cw-sched-retry" onClick={() => void loadSlots()}>
          Retry
        </button>
      </div>
    );
  }

  if (step.name === "list") {
    if (step.slots.length === 0) {
      return (
        <div className="cw-sched">
          <div className="cw-sched-empty" role="status">
            No times are currently available.
          </div>
        </div>
      );
    }
    return (
      <div className="cw-sched">
        <div className="cw-sched-list-label" id="cw-sched-list-label">
          Choose a time
        </div>
        <ul className="cw-sched-list" aria-labelledby="cw-sched-list-label">
          {step.slots.map((slot, index) => (
            <li key={slot.startsAt}>
              <button
                type="button"
                className="cw-sched-slot"
                ref={index === 0 ? firstSlotButtonRef : undefined}
                onClick={() => selectSlot(slot)}
              >
                {formatLocalSlotLabel(slot.startsAt)}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (step.name === "confirm" || step.name === "booking" || step.name === "book-error") {
    const submitting = step.name === "booking";
    const label = formatLocalSlotLabel(step.slot.startsAt);
    return (
      <div className="cw-sched">
        <div className="cw-sched-confirm-heading" tabIndex={-1} ref={confirmHeadingRef}>
          Confirm your appointment: {label}
        </div>

        <div className="cw-sched-consent-row">
          <input
            id="cw-sched-consent"
            className="cw-sched-checkbox"
            type="checkbox"
            checked={consentChecked}
            disabled={submitting}
            onChange={(e) => setConsentChecked(e.target.checked)}
          />
          <label className="cw-sched-consent-label" htmlFor="cw-sched-consent">
            {SCHEDULE_CONSENT_TEXT}
          </label>
        </div>

        {step.name === "book-error" && (
          <div className="cw-sched-error" role="alert">
            {step.message}
          </div>
        )}

        <div className="cw-sched-confirm-actions">
          <button
            type="button"
            className="cw-sched-confirm-button"
            disabled={!consentChecked || submitting}
            onClick={() => void confirmBooking(step.slot)}
          >
            {submitting ? "Booking…" : "Confirm"}
          </button>
          <button
            type="button"
            className="cw-sched-back-button"
            disabled={submitting}
            onClick={() => void loadSlots()}
          >
            Back
          </button>
        </div>
      </div>
    );
  }

  // step.name === "booked"
  const label = formatLocalSlotLabel(step.slot.startsAt);
  return (
    <div className="cw-sched-confirmation" role="status" tabIndex={-1} ref={confirmationRef}>
      You&rsquo;re booked for {label}. We&rsquo;ll send a reminder beforehand.
    </div>
  );
}
