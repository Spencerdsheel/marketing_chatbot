---
name: admin-api
description: Use when building or modifying the admin/back-office API for the chatbot platform — tenant/client onboarding and configuration, user management, triggering knowledge/question uploads, the lead review console endpoints, conversation analytics endpoints, and per-tenant settings (greeting, business hours, escalation policy, tone, confidence threshold, provider/model). Use this for anything platform-admin or client-admin facing on the backend.
---

# Admin API

> The control plane for platform admins and client admins/agents. Backs the `admin-web` console. Obey
> `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- **Tenant/client onboarding & config** (PLATFORM_ADMIN creates tenants; CLIENT_ADMIN configures their own).
- **User management** within RBAC rules.
- **Knowledge/question upload** triggering → hands files to `document-ingestion-service`.
- **Lead review console** endpoints (delegates to `lead-capture-crm`).
- **Conversation analytics** endpoints (delegates to `analytics-observability`).
- **Per-tenant settings:** greeting/voice copy, business hours, escalation policy, tone rules, confidence
  threshold, max turns, LLM provider/model, domain allowlist, client keys.

## Boundaries
- **In scope:** admin-facing orchestration + config/settings storage; upload trigger; review/analytics
  read endpoints.
- **Out of scope:** auth/tokens (`auth-session-service`), lead pipeline internals (`lead-capture-crm`),
  ingestion processing (`document-ingestion-service`), analytics computation (`analytics-observability`).
- **Upstream:** admin-web. **Downstream:** ingestion, leads, analytics, conversation-store, auth.

## Data model (config/settings)
- `tenants(tenant_id PK, name, deployment_mode, status, created_at)`.
- `tenant_settings(tenant_id PK, greeting, business_hours jsonb, escalation_policy jsonb, tone jsonb,
  confidence_threshold, max_turns, llm_config jsonb, domain_allowlist text[], client_keys jsonb)`.
- `users(user_id PK, tenant_id, email, name, role, project_ids, ...)` (auth uses this for login).

## API contract (representative)
- `POST /admin/tenants` (PLATFORM_ADMIN) · `PATCH /admin/tenants/{id}/settings` (CLIENT_ADMIN, own tenant).
- `POST /admin/users` / `PATCH` / `DELETE` (RBAC-gated; CLIENT_ADMIN scoped to own tenant).
- `POST /admin/knowledge/upload` → store to object storage, enqueue ingestion.
- `GET /admin/leads...` (delegates), `GET /admin/analytics...` (delegates).

## Patterns & standards
- All endpoints rate-limited at the admin tier (5/hr for sensitive ops) and RBAC-gated at the data layer.
- CLIENT_ADMIN can only ever read/write within its own `tenant_id`; PLATFORM_ADMIN is global. CLIENT_AGENT is
  read-mostly (leads/conversations), no config writes.
- Every admin action is **audited** (actor, tenant, action, correlation_id).
- Settings validated with Pydantic; fail closed on invalid config.

## Security & multi-tenancy notes
- Highest-value surface — strict RBAC + audit. `tenant_id` from claims, never request body. Client keys are
  public identifiers; client secrets/provider keys are encrypted.

## Observability
- Metrics: admin actions by type/role, upload counts, config changes; full audit trail.

## Testing requirements
- RBAC matrix per endpoint (platform vs client-admin vs agent vs cross-tenant denial); settings validation;
  upload → ingestion enqueue; audit emission; tenant scoping of users/leads/analytics.

## Reusable insights (knowledge_base / solution_flow)
- Admin console: client onboarding, upload, lead review, analytics, escalation/greeting/business-hours config;
  isolate content/leads/config per tenant. (solution_flow)
- Single, tightly controlled platform-admin scope; audit admin actions. (RBAC_MODEL)

## As-built & doctrine (audit 2026-07-11)
- **Status: NOT BUILT** — Phase 12 (S12.1–S12.4). Precursor pieces already exist elsewhere: tenant CRUD/seed in `api/tenants/` + `api/seed.py`, per-tenant LLM/CRM/calendar/notification config repos in their owning modules, lead review data in `api/leads/`, audit read in `api/audit/`.
- **S12.1 carries audit debt:** hash the plaintext `tenants.client_key` + constant-time lookup + rotation endpoint (audit P3-1), and record the visitor-session-secret decision (P3-2).
- **Think here:** admin-api *aggregates* other modules through their repositories — it owns onboarding orchestration and settings, never other modules' tables. Onboarding is the product's first impression: one-shot, idempotent, and the client key is shown exactly once. Every settings knob added here must already have a consumer (orchestrator/provider) that reads it — no dead config.
