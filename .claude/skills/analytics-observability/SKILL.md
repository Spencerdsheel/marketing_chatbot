---
name: analytics-observability
description: Use when building or modifying observability and analytics for the chatbot platform — structured JSON logging, correlation IDs, Prometheus metrics, Sentry error tracking, health/readiness endpoints, the audit trail, and conversation analytics (fallback rate, schedule conversion, intent distribution, deflection). Use this for anything about logs, traces, metrics, dashboards, or measuring conversation outcomes.
---

# Analytics & Observability

> Cross-cutting measurement: technical observability + business conversation analytics. Obey `CLAUDE.md` +
> `platform-foundations` (logging/metrics helpers live there).

## Purpose & responsibilities
- **Observability:** structured JSON logs with correlation IDs, Prometheus metrics (`/metrics`), Sentry error
  tracking, `/healthz` + `/readyz`.
- **Audit trail:** tamper-evident record of auth events, admin actions, data mutations, exports.
- **Conversation analytics:** ingest events from the orchestrator/scheduling/leads and compute fallback rate,
  schedule conversion, intent distribution, deflection/answer rate, average turns, lead conversion.

## Boundaries
- **In scope:** the logging/metrics/tracing conventions, audit storage, analytics event model + aggregation,
  analytics read APIs (consumed by `admin-api`).
- **Out of scope:** raw conversation storage (`conversation-store`), generating the events (each service emits
  them).
- **Upstream:** all services emit events/metrics. **Downstream:** admin-api/admin-web read aggregates.

## Data model (analytics + audit)
- `analytics_events(tenant_id, event_id PK, type, conversation_id?, payload jsonb, occurred_at)` — append-only.
- `audit_log(tenant_id?, entry_id PK, actor, action, target, correlation_id, created_at, prev_hash?)` —
  tamper-evident chain optional.
- Aggregations precomputed (Celery Beat) or queried with window functions; tenant-scoped.

## API contract (representative)
- `GET /admin/analytics/overview` → `{ fallback_rate, schedule_conversion, deflection, avg_turns, lead_rate }`.
- `GET /admin/analytics/conversations` → time-series. All tenant-scoped; PLATFORM_ADMIN can aggregate across.

## Patterns & standards
- Logs: JSON, correlation_id + tenant_id + actor + endpoint on every line; never log secrets/tokens/PII.
- Metrics: request count/latency/error per endpoint; business metrics (active tenants, ingestion status,
  fallback rate). Health vs readiness are distinct (liveness vs can-serve).
- Audit is append-only; redact sensitive payloads.

## Security & multi-tenancy notes
- Analytics reads scoped to `claims.tenant_id`; only PLATFORM_ADMIN sees cross-tenant rollups. Audit entries
  are immutable.

## Observability (of itself)
- Alert on error-rate spikes, ingestion backlog, reminder failures, low readiness.

## Testing requirements
- Aggregation correctness (fallback rate, conversion); tenant scoping of analytics; audit immutability +
  redaction; health vs readiness behavior; log field presence.

## Reusable insights (knowledge_base / solution_flow)
- Metrics answer "what"; logs answer "why" — you need both. JSON logs + correlation IDs from day one. (`08`)
- Health ≠ readiness. (`03`) · Audit security-relevant events; redact PII. (`07`)
- Admin views fallback rates and schedule conversion. (solution_flow)
