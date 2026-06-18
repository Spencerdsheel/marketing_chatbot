---
name: notification-service
description: Use when building or modifying outbound notifications for the chatbot platform — the NotificationProvider abstraction, email as the default channel (SES/SendGrid/Mailgun/Postmark-style impls), optional SMS/WhatsApp (Twilio), and the confirmation + reminder jobs (booking confirmations, password-reset emails, reminders at 3d/24h/1h). This is a carved-out Celery worker. Use this for anything about sending email/SMS/WhatsApp.
---

# Notification Service (worker)

> Carved-out, queue-driven delivery of all outbound messages. Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Provide a **`NotificationProvider` Protocol** with **email as the default channel** and optional
  **SMS/WhatsApp**.
- Process notification jobs: booking confirmations (user + tenant), scheduling reminders (3d/24h/1h),
  password-reset emails, lead alerts.
- Render templates (per-tenant branding), handle retries, respect consent + unsubscribe.

## Boundaries
- **In scope:** provider abstraction, channel impls, template rendering, job processing, retries, consent/
  unsubscribe, delivery tracking.
- **Out of scope:** *deciding* when to notify (scheduling/leads/auth enqueue jobs), reminder scheduling
  (`scheduling-service` owns the cron via Celery Beat).
- **Upstream:** scheduling-service, lead-capture-crm, auth-session-service enqueue jobs.

## Contract
```python
class NotificationProvider(Protocol):
    async def send(self, claims, message: Notification) -> DeliveryRef: ...
# channels: EmailProvider (SES/SendGrid/Mailgun/Postmark), SmsProvider/WhatsAppProvider (Twilio) — optional.
# selected per tenant config; provider keys encrypted.
```

## Data model
- `notification_jobs(tenant_id, job_id PK, channel, template, to, payload jsonb, status, attempts, run_at,
  delivery_ref?, created_at)` — idempotent (dedupe key).
- `notification_templates(tenant_id, key PK, channel, subject?, body, locale)`.

## Patterns & standards
- **Idempotent + retryable** (backoff/jitter, max attempts, dead-letter). A reminder must send **exactly
  once** (dedupe on `(event_id, offset)`).
- Respect consent + unsubscribe before sending; never send to non-consented contacts.
- Never log message bodies containing PII or provider keys. No silent failure — record delivery status and
  surface permanent failures.

## Security & multi-tenancy notes
- Jobs/templates/keys tenant-scoped; provider credentials encrypted per tenant. From-addresses/branding per
  tenant.

## Observability
- Metrics: sent/failed by channel/provider, retry counts, queue depth, reminder delivery rate, bounce/
  unsubscribe rate. Correlation_id on every job.

## Testing requirements
- Provider conformance (contract tests); reminder exactly-once/idempotency; consent + unsubscribe gating;
  retry/dead-letter; template rendering; tenant isolation; PII redaction.

## Reusable insights (knowledge_base / solution_flow)
- Define the interface at the boundary; swap providers via config. (`01`, ADR-002)
- Idempotent, retryable tasks for every external call. (`02`, `06`)
- Email via SES/SendGrid/Mailgun/Postmark; optional SMS/WhatsApp via Twilio; reminders at 3d/24h/1h.
  (solution_flow)
