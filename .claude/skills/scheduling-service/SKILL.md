---
name: scheduling-service
description: Use when building or modifying call/meeting scheduling for the chatbot — availability and slots, the ScheduleEvent data model, timezones/consent, the native booking flow, the CalendarProvider abstraction for Google/Outlook (free-busy + event sync) and optional Calendly, and creation of reminder jobs at 3 days / 24 hours / 1 hour before the call. Use this for anything about booking, calendars, or reminders.
---

# Scheduling Service

> Owns native booking + calendar sync + reminder scheduling. The orchestrator escalates here on fallback.
> Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Own the **booking UX/data**: availability, slot selection, timezones, confirmation, cancellation/reschedule.
- Sync events to client calendars via a **`CalendarProvider` Protocol** (Google/Outlook free-busy + event
  create/update; optional Calendly connector).
- Create **reminder jobs** at **3 days / 24h / 1h** before the event (Celery Beat + queue → `notification-
  service`).

## Boundaries
- **In scope:** availability, ScheduleEvent, booking flow, calendar sync, reminder job creation.
- **Out of scope:** actually sending emails/SMS (`notification-service`), lead records (`lead-capture-crm`),
  dialog (`conversation-orchestrator`).
- **Upstream:** orchestrator, admin-web. **Downstream:** notification-service, CalendarProvider connectors.

## Data model
- `schedule_events(tenant_id, event_id PK, lead_id?, visitor_id?, starts_at, ends_at, timezone, status
  [booked|cancelled|completed|no_show], calendar_ref?, consent jsonb, created_at)`.
- `availability(tenant_id, rules jsonb)` — business hours, slot length, buffers.
- `reminder_jobs(tenant_id, event_id, offset[3d|24h|1h], run_at, status, attempts)` — idempotent.

## CalendarProvider contract
```python
class CalendarProvider(Protocol):
    async def free_busy(self, claims, window) -> list[Busy]: ...
    async def create_event(self, claims, event) -> CalendarRef: ...
    async def update_event(self, claims, ref, event) -> None: ...
# impls: GoogleCalendar, Outlook, Calendly(optional) — per-tenant config; OAuth tokens encrypted.
```

## Booking flow
```
escalation/booking request (claims)
  → compute open slots (availability − free_busy)
  → user picks slot (with timezone) + consent
  → create ScheduleEvent + create_event on provider
  → trigger confirmation (notification-service) to user + tenant
  → enqueue reminder_jobs at 3d/24h/1h
```

## Patterns & standards
- Reminder + sync work is **idempotent + retryable** (backoff/jitter; reminders fire once). Celery Beat
  schedules due reminders.
- Timezones explicit end-to-end; store UTC + tz. Consent required before creating reminders.
- No double-booking: check free-busy at commit; handle provider failure explicitly (no silent drop).

## Security & multi-tenancy notes
- Events/availability tenant-scoped. Calendar OAuth tokens encrypted per tenant. Visitors can only act on
  their own event.

## Observability
- Metrics: bookings, slot-search latency, calendar-sync success/failure, reminders sent, no-show rate,
  schedule conversion (with orchestrator).

## Testing requirements
- Slot computation vs free-busy; timezone correctness; reminder scheduling at exact offsets + idempotency;
  CalendarProvider conformance; tenant isolation; consent enforcement; reschedule/cancel.

## Reusable insights (knowledge_base / solution_flow)
- After low confidence or 6–7 turns, present a scheduler; on booking send confirmations + reminders at
  3d/24h/1h. (solution_flow)
- Celery Beat for cron-like scheduling; design every task to be retried. (`02`, `06`)

## As-built & doctrine (audit 2026-07-11)
- **Status: built** (S8.1–S8.3; reminder delivery wired to notifications in S9.2). Path: `services/api/src/api/scheduling/` — availability CRUD + `slots.compute_slots` (window-capped), booking with consent + double-booking guards, `calendar.py` `CalendarProvider` (Google free-busy/sync, OAuth tokens encrypted; 0019), `reminder_repository` + `tasks` (0020).
- **As-built facts:** reminders (3d/24h/1h) are rows claimed by an **atomic UPDATE … LIMIT** in the beat-driven dispatcher — the exactly-once gate lives in the claim SQL, not in Celery; deterministic sink errors → `failed` + `last_error` (no retry), transient → raise (Celery retry).
- **Think here:** time is the bug farm — everything stored UTC, tenant timezone applied at the edges; every guard (closed hours, double-booking, past-slot) is enforced in SQL/repo, not just the UI. Idempotency on rebook: cancel-and-replace reminder jobs keyed by event, never accumulate.
