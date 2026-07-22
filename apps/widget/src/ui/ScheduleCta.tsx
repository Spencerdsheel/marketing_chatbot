/**
 * Consent-gated inline scheduling flow (S14.4 decisions 1/3/4/5/7, scope item 2;
 * SR-5 decisions 1/6/7 — staged calendar/day-strip/timezone picker + in-flow
 * invite email + booking-awareness).
 *
 * Two entry shapes:
 *   (a) legacy/no-summary — a flat list of open slots (server-returned,
 *       shown in the visitor's local timezone via Intl; an empty list is an
 *       honest "no times available", never a fabricated slot).
 *   (b) `summary` supplied (SR-5, launched from the persistent CTA) — a
 *       staged flow: existing-booking ask (if any, decision 7a) -> a real
 *       month calendar with a Sun-Sat day-of-week grid (only days the
 *       server's day map marks available are enabled, decision 2) -> a
 *       timezone selector (defaults to the visitor's resolved zone,
 *       overridable for display only — the booking always sends an
 *       explicit IANA timezone, open-question 2) -> the 3-column time grid
 *       for the chosen day -> in-flow "where should we send the invite?"
 *       email/name capture + consent -> gray recap -> confirm.
 * Confirm calls bookSlot echoing the exact server-returned UTC starts_at +
 * the chosen IANA timezone + truthful consent + the typed invite email/name
 * (decision 6). On a real 201, an honest, non-rebookable confirmation
 * replaces the picker. On failure: SLOT_UNAVAILABLE re-fetches slots and
 * lets the visitor re-pick (never fabricates a confirmation);
 * CALENDAR_SYNC_FAILED/network/other shows an honest error with manual
 * retry; never auto-retry/loop. All state is in-memory only (component
 * state); nothing is keyed/cached by tenant_id; PII/booking is never logged
 * (failure console.error carries only error_code/correlation_id/status).
 *
 * A11y (SR-5 Constraints): the month calendar is a real ARIA grid
 * (`role="grid"` > `role="row"` > `role="gridcell"` > a focusable button),
 * focus moves onto the first enabled day when the calendar step mounts,
 * and every step transition keeps the existing S14.5 focus-management
 * pattern (confirm heading, booking confirmation, `role="status"`/
 * `role="alert"` live regions).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import type { WidgetConfig } from "../config";
import { SCHEDULE_CONSENT_PURPOSE, SCHEDULE_CONSENT_TEXT, bookSlot, fetchSlots, type AvailabilitySummary, type Slot } from "../schedule";

const LOG_PREFIX = "[chatbot-widget]";

/** A short, fixed list covering common regions plus the visitor's own
 * resolved zone (added dynamically if not already present) — this widget
 * has no server-delivered timezone catalog, so the selector stays a small,
 * deterministic set rather than pulling in a full IANA database. */
const COMMON_TIME_ZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export interface ScheduleCtaProps {
  config: WidgetConfig;
  /** Optional linkage to a lead captured earlier in this in-memory page session (decision 6). */
  leadId?: string;
  /** Server-authoritative day map when launched from the persistent CTA. */
  summary?: AvailabilitySummary;
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

interface CalendarDay {
  date: string;
  dayOfMonth: number;
  hasAvailability: boolean;
}

interface CalendarMonth {
  key: string;
  label: string;
  /** Each week is exactly 7 cells (Sun..Sat); `null` pads days outside the month. */
  weeks: (CalendarDay | null)[][];
}

/** Groups the server's flat day map into month-shaped week grids (decision 1)
 * — pure client-side presentation over data the server already computed. */
function buildCalendarMonths(days: AvailabilitySummary["days"]): CalendarMonth[] {
  const byMonth = new Map<string, CalendarDay[]>();
  for (const day of days) {
    const parsed = new Date(`${day.date}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) continue;
    const monthKey = day.date.slice(0, 7);
    const list = byMonth.get(monthKey) ?? [];
    list.push({ date: day.date, dayOfMonth: parsed.getUTCDate(), hasAvailability: day.hasAvailability });
    byMonth.set(monthKey, list);
  }

  const months: CalendarMonth[] = [];
  for (const [monthKey, monthDays] of [...byMonth.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    monthDays.sort((a, b) => a.date.localeCompare(b.date));
    const first = new Date(`${monthDays[0]?.date ?? `${monthKey}-01`}T00:00:00Z`);
    const label = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(first);

    const byDayOfMonth = new Map(monthDays.map((d) => [d.dayOfMonth, d]));
    const daysInMonth = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    const leadingBlanks = first.getUTCDay();

    const cells: (CalendarDay | null)[] = [];
    for (let i = 0; i < leadingBlanks; i += 1) cells.push(null);
    for (let dom = 1; dom <= daysInMonth; dom += 1) cells.push(byDayOfMonth.get(dom) ?? null);
    while (cells.length % 7 !== 0) cells.push(null);

    const weeks: (CalendarDay | null)[][] = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

    months.push({ key: monthKey, label, weeks });
  }
  return months;
}

export function ScheduleCta({ config, leadId, summary }: ScheduleCtaProps) {
  const [step, setStep] = useState<Step>({ name: "loading" });
  const [consentChecked, setConsentChecked] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const hasExistingBooking = summary?.existingBooking !== null && summary?.existingBooking !== undefined;
  const [calendarVisible, setCalendarVisible] = useState(summary !== undefined && !hasExistingBooking);
  const [existingDecisionPending, setExistingDecisionPending] = useState(hasExistingBooking);
  /** "Keep it" (decision 7a): dismiss without ever showing the picker or
   * booking anything new — a pure no-op end state, not a fall-through into
   * the calendar. */
  const [dismissed, setDismissed] = useState(false);
  const resolvedZone = useRef(resolveVisitorTimeZone()).current;
  const [timeZone, setTimeZone] = useState(() => summary?.timezone ?? resolvedZone);
  const firstSlotButtonRef = useRef<HTMLButtonElement | null>(null);
  const confirmHeadingRef = useRef<HTMLDivElement | null>(null);
  const confirmationRef = useRef<HTMLDivElement | null>(null);
  const firstEnabledDayRef = useRef<HTMLButtonElement | null>(null);
  const existingBookingHeadingRef = useRef<HTMLParagraphElement | null>(null);

  const timeZoneOptions = useMemo(() => {
    const zones = new Set(COMMON_TIME_ZONES);
    zones.add(resolvedZone);
    if (summary?.timezone) zones.add(summary.timezone);
    return [...zones].sort();
  }, [resolvedZone, summary?.timezone]);

  const calendarMonths = useMemo(() => buildCalendarMonths(summary?.days ?? []), [summary?.days]);
  const [monthIndex, setMonthIndex] = useState(0);
  const activeMonth = calendarMonths[monthIndex] ?? null;

  async function loadSlots(day?: string) {
    setStep({ name: "loading" });
    const result = await fetchSlots(config, day ? { dateFrom: day, dateTo: day } : {});
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
    if (!summary) void loadSlots();
    // Load slots exactly once on mount; loadSlots is intentionally
    // re-invoked imperatively (not via effect deps) on SLOT_UNAVAILABLE.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary]);

  useEffect(() => {
    if (existingDecisionPending) {
      existingBookingHeadingRef.current?.focus();
      return;
    }
    if (calendarVisible) {
      firstEnabledDayRef.current?.focus();
      return;
    }
    if (step.name === "list") {
      firstSlotButtonRef.current?.focus();
    } else if (step.name === "confirm") {
      confirmHeadingRef.current?.focus();
    } else if (step.name === "booked") {
      confirmationRef.current?.focus();
    }
  }, [step.name, calendarVisible, existingDecisionPending, monthIndex]);

  function selectSlot(slot: Slot) {
    setConsentChecked(false);
    setStep({ name: "confirm", slot });
  }

  async function confirmBooking(slot: Slot) {
    setStep({ name: "booking", slot });

    const result = await bookSlot(config, {
      startsAt: slot.startsAt,
      timezone: timeZone,
      consent: { granted: true, purpose: SCHEDULE_CONSENT_PURPOSE, text: SCHEDULE_CONSENT_TEXT },
      ...(leadId ? { leadId } : {}),
      ...(email.trim() ? { email: email.trim() } : {}),
      ...(name.trim() ? { name: name.trim() } : {}),
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
        await loadSlots(selectedDay ?? undefined);
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

  if (existingDecisionPending && summary?.existingBooking) {
    return (
      <div className="cw-sched" role="status">
        <p ref={existingBookingHeadingRef} tabIndex={-1}>
          You&rsquo;re already booked for {formatLocalSlotLabel(summary.existingBooking.startsAt)}. Keep it, or book an additional call?
        </p>
        <div className="cw-sched-confirm-actions">
          <button type="button" className="cw-sched-back-button" onClick={() => { setExistingDecisionPending(false); setDismissed(true); }}>Keep it</button>
          <button type="button" className="cw-sched-confirm-button" onClick={() => { setExistingDecisionPending(false); setCalendarVisible(true); }}>Book another</button>
        </div>
      </div>
    );
  }

  if (dismissed) {
    return (
      <div className="cw-sched-confirmation" role="status">
        Your existing appointment is still booked.
      </div>
    );
  }

  if (calendarVisible) {
    let seenFirstEnabled = false;
    return (
      <div className="cw-sched" role="status">
        <div className="cw-sched-list-label">Choose a day</div>
        <div className="cw-sched-month-nav">
          <button
            type="button"
            className="cw-sched-back-button"
            disabled={monthIndex === 0}
            aria-label="Previous month"
            onClick={() => setMonthIndex((i) => Math.max(0, i - 1))}
          >
            ‹
          </button>
          <span className="cw-sched-month-label">{activeMonth?.label ?? ""}</span>
          <button
            type="button"
            className="cw-sched-back-button"
            disabled={monthIndex >= calendarMonths.length - 1}
            aria-label="Next month"
            onClick={() => setMonthIndex((i) => Math.min(calendarMonths.length - 1, i + 1))}
          >
            ›
          </button>
        </div>
        <div className="cw-sched-weekday-row" role="presentation">
          {WEEKDAY_LABELS.map((label) => (
            <span key={label} className="cw-sched-weekday">{label}</span>
          ))}
        </div>
        <div className="cw-sched-calendar" role="grid" aria-label="Available appointment days">
          {(activeMonth?.weeks ?? []).map((week, weekIndex) => (
            <div key={weekIndex} role="row" className="cw-sched-week-row">
              {week.map((day, cellIndex) => {
                if (!day) {
                  return <span key={cellIndex} role="gridcell" className="cw-sched-day-blank" aria-hidden="true" />;
                }
                const isFirstEnabled = day.hasAvailability && !seenFirstEnabled;
                if (isFirstEnabled) seenFirstEnabled = true;
                return (
                  <span key={day.date} role="gridcell">
                    <button
                      type="button"
                      ref={isFirstEnabled ? firstEnabledDayRef : undefined}
                      className="cw-sched-slot cw-sched-day"
                      disabled={!day.hasAvailability}
                      aria-label={`${day.date}${day.hasAvailability ? ", available" : ", unavailable"}`}
                      onClick={() => { setSelectedDay(day.date); setCalendarVisible(false); void loadSlots(day.date); }}
                    >
                      {day.dayOfMonth}
                    </button>
                  </span>
                );
              })}
            </div>
          ))}
        </div>
        {calendarMonths.length === 0 && (
          <div className="cw-sched-empty" role="status">No times are currently available.</div>
        )}
        <label className="cw-sched-tz-label" htmlFor="cw-sched-timezone">Timezone</label>
        <select
          id="cw-sched-timezone"
          className="cw-input cw-sched-tz-select"
          value={timeZone}
          onChange={(e) => setTimeZone(e.target.value)}
        >
          {timeZoneOptions.map((zone) => (
            <option key={zone} value={zone}>{zone}</option>
          ))}
        </select>
      </div>
    );
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
        <button type="button" className="cw-sched-retry" onClick={() => void loadSlots(selectedDay ?? undefined)}>
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
          {summary && (
            <button type="button" className="cw-sched-back-button" onClick={() => setCalendarVisible(true)}>
              Back to calendar
            </button>
          )}
        </div>
      );
    }
    return (
      <div className="cw-sched">
        <div className="cw-sched-list-label" id="cw-sched-list-label">
          Choose a time ({timeZone})
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
        {summary && (
          <button type="button" className="cw-sched-back-button" onClick={() => setCalendarVisible(true)}>
            Back to calendar
          </button>
        )}
      </div>
    );
  }

  if (step.name === "confirm" || step.name === "booking" || step.name === "book-error") {
    const submitting = step.name === "booking";
    const label = formatLocalSlotLabel(step.slot.startsAt);
    return (
      <div className="cw-sched">
        <div className="cw-sched-confirm-heading" tabIndex={-1} ref={confirmHeadingRef}>
          Confirm your appointment
        </div>

        {summary && (
          <div className="cw-sched-recap" role="status">
            <div><span className="cw-sched-recap-label">Time</span> {label}</div>
            <div><span className="cw-sched-recap-label">Timezone</span> {timeZone}</div>
          </div>
        )}
        {!summary && <p>{label}</p>}

        {summary && <>
          <label className="cw-sched-email-label" htmlFor="cw-sched-email">Where should we send the invite?</label>
          <input id="cw-sched-email" className="cw-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} disabled={submitting} required aria-label="Invite email" />
          <input className="cw-input" type="text" value={name} onChange={(e) => setName(e.target.value)} disabled={submitting} aria-label="Name, optional" placeholder="Name (optional)" />
        </>}

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
            disabled={!consentChecked || (summary !== undefined && !email.trim()) || submitting}
            onClick={() => void confirmBooking(step.slot)}
          >
            {submitting ? "Booking…" : "Confirm"}
          </button>
          <button
            type="button"
            className="cw-sched-back-button"
            disabled={submitting}
            onClick={() => summary ? setCalendarVisible(true) : void loadSlots()}
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
