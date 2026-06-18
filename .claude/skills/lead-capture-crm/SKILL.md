---
name: lead-capture-crm
description: Use when building or modifying lead capture and the built-in CRM for the chatbot — the early lead form, lead data model, pipeline stages, qualification scoring, notes/activity timeline, agent assignment, export, consent capture, and the optional outbound CRMSync connectors (HubSpot/Salesforce/webhook). Use this for anything about leads, contacts, or CRM.
---

# Lead Capture + Built-in CRM

> Captures contacts early and manages them through a pipeline; optionally syncs outward. Obey `CLAUDE.md` +
> `platform-foundations`.

## Purpose & responsibilities
- **Capture leads early** (before the main conversation): short form (name, email, phone) with **explicit
  consent**.
- **Built-in CRM:** pipeline stages, status, qualification score, notes/activity timeline, agent assignment,
  export.
- **Optional outbound sync:** push leads to external CRMs via a `CRMSync` Protocol (HubSpot/Salesforce/
  generic webhook), per-tenant, opt-in.

## Boundaries
- **In scope:** lead model, pipeline/qualification, activity log, assignment, export, consent, CRMSync.
- **Out of scope:** booking (`scheduling-service`), conversation storage (`conversation-store`), sending
  emails (`notification-service`).
- **Upstream:** orchestrator (creates/qualifies leads), admin-api (lead review console). **Downstream:**
  notification-service, CRMSync connectors.

## Data model
- `leads(tenant_id, lead_id PK, visitor_id?, name, email, phone, status, stage, qualification_score,
  consent jsonb, assigned_agent_id?, source, created_at, updated_at)`.
- `lead_activities(tenant_id, lead_id, activity_id PK, type, payload jsonb, actor, created_at)` — timeline.
- All keyed/filtered by `tenant_id`; PII fields treated as sensitive (redacted in logs).

## CRMSync contract
```python
class CRMSync(Protocol):
    async def upsert_lead(self, claims, lead) -> ExternalRef: ...
    async def push_activity(self, claims, lead_id, activity) -> None: ...
# impls: HubSpotSync, SalesforceSync, WebhookSync — selected per tenant config; keys encrypted.
```

## API contract (representative)
- `POST /api/leads` (visitor, from widget/orchestrator) → create with consent.
- `PATCH /admin/leads/{id}` (agent/admin) → stage/status/assignment/notes.
- `GET /admin/leads` + `GET /admin/leads/export` (agent/admin, tenant-scoped).

## Patterns & standards
- Consent is mandatory before storing contact details or enabling reminders (GDPR). Record consent payload.
- Outbound sync runs as an **idempotent, retryable** background job (Celery) — never block the chat path.
- Cache-aside for lead lists (tenant-scoped, short TTL); invalidate on mutation.

## Security & multi-tenancy notes
- Leads are strictly tenant-scoped; `CLIENT_AGENT` sees only assigned/tenant leads per policy. Export is
  audited. External CRM keys are encrypted per tenant.

## Observability
- Metrics: leads created, qualification distribution, stage conversion, sync success/failure, export counts.
  Audit pipeline changes and exports.

## Testing requirements
- Tenant isolation; consent enforcement; pipeline transitions; qualification scoring; assignment; CRMSync
  idempotency + retry; export scoping; PII redaction in logs.

## Reusable insights (knowledge_base / solution_flow)
- Lead capture happens early, before the main conversation. (solution_flow)
- Store explicit consent for contact capture and reminders. (solution_flow, `07`)
- Idempotent, retryable background jobs for external calls. (`02`, `06`)
