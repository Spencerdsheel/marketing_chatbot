# Chatbot Platform

An embeddable, multi-tenant AI chatbot platform: it answers website visitors only from a
client's own knowledge, captures and qualifies leads with explicit consent, and converts
low-confidence or long conversations into booked calls — automatically, per tenant.

Built by **iSN Business Solutions** (IT consultancy + digital-marketing practice) to sell
end-to-end to clients, starting with mystery-shopping companies and digital-marketing clients
(e.g. roofers), and dogfooded on iSN's own site.

---

## 1. Problem & impact

SMBs and service businesses lose website visitors because questions go unanswered outside
business hours, and generic chatbots either hallucinate or can't actually do anything about
the visitor's intent. This platform is built around three rules that make it trustworthy
enough to put in front of a client's customers:

- **No invented answers.** The bot answers only from the tenant's ingested knowledge, via
  retrieval-augmented generation. If it can't ground an answer, it says so and falls back —
  it never serves a fabricated or generic reply (`CLAUDE.md` §3, "no silent fallbacks").
- **Consent-gated data capture.** Contact details and scheduling reminders are never stored
  without explicit GDPR consent.
- **Isolation by construction.** Every tenant's conversations, leads, knowledge, and LLM
  config are isolated at the repository layer, not just filtered in the API.

The resulting funnel a buyer cares about:

**24/7 grounded answers → captured + qualified leads → booked meetings**, with per-tenant
attribution of LLM usage/cost, deflection rate, and schedule-conversion rate as the
observability layer matures (see [Status & roadmap](#9-status--roadmap)).

---

## 2. Feature overview

| Area | What it does |
|---|---|
| Embeddable widget | One script tag, self-contained bundle, no CSS/JS collisions with the host site *(not yet built — see roadmap)* |
| AI "brain" | Hybrid RAG (pgvector + full-text, RRF-fused) over tenant knowledge + provider-agnostic LLM, with a confidence/turn-count fallback to scheduling |
| Lead capture + CRM | Pipeline, qualification, agent assignment, activity notes, CSV export, outbound webhook/CRM sync, consent-gated |
| Scheduling | Availability, slot booking, Google Calendar sync, reminders at 3 days / 24 hours / 1 hour before the call |
| Notifications | Per-tenant provider abstraction; email today, SMS/WhatsApp designed-for-later |
| Document ingestion | Upload → parse (txt/docx today, PDF/OCR planned) → chunk → embed → idempotent UPSERT into pgvector |
| Admin console | Client onboarding, knowledge upload, lead review, conversation analytics *(not yet built — see roadmap)* |
| Multi-tenancy | One codebase, two delivery modes (shared SaaS or dedicated single-tenant install), switched by config — tenant isolation is always on |

---

## 3. Architecture

### Request flow

```
                                   Website Visitor
                                          │
                                          ▼
                         Embedded Chat Widget (planned, P14)
                                          │  public client_key + Origin
                                          ▼
                    POST /widget/session   ──►  validate client_key + Origin allowlist
                                          │      mint short-lived signed VISITOR JWT
                                          ▼
                    POST /public/chat/message  (bearer = visitor JWT)
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │      Conversation Orchestrator          │
                      │      (answer_turn, orchestrator/)       │
                      │                                          │
                      │  1. resolve tenant LLM config (fail-fast)│
                      │  2. get/create conversation              │
                      │  3. append durable user turn              │
                      │  4. build working memory (windowed        │
                      │     turns + running summary)               │
                      │  5. hybrid RAG retrieval (rag/) ──────┐   │
                      │  6. grounded LLM generate (llm/) ◄────┘   │
                      │  7. append assistant turn + cited sources │
                      │  8. return leak-free response              │
                      └────────────────────────────────────────┘
                                          │
                     ┌────────────────────┼────────────────────────┐
                     ▼                    ▼                        ▼
           conversation_store/    leads/ + crm/           scheduling/
           (Postgres, tenant-      (pipeline, export,      (availability, booking,
            scoped history)        webhook/CRM sync)        Google Calendar sync)
                                                                    │
                                                                    ▼
                                                          Celery worker/beat
                                                          ── reminder jobs (3d/24h/1h)
                                                          ── notifications/ (email)
                                                          ── ingestion/ (parse→chunk→
                                                             embed→pgvector UPSERT)

Cross-cutting: audit/ (audit trail) · observability/ (structured logs, correlation IDs,
Prometheus /metrics) · auth/ + rbac/ (admin JWT, 4-role RBAC) · services/common (shared
AuthClaims, errors, settings, crypto, cache, pgvector access) run through every request.
```

### Topology

- **Core modular monolith** — one FastAPI app (`services/api`) sharing `services/common` and
  one PostgreSQL (pgvector) behind PgBouncer, plus Redis. Modules have strict seams (own
  router, repository, models, schemas) so any of them can be carved out later without a
  rewrite.
- **Carved-out worker processes** (same codebase, separate Celery processes today; named
  queues planned): document ingestion, notifications, and the reminder scheduler
  (Celery Beat).
- **Not yet built**: Nginx edge, the admin web console, the chat widget, and production
  Docker images / CI (see [roadmap](#9-status--roadmap)). Locally the FastAPI app is reached
  directly on port 8000.

### Module map (as-built)

All paths are under `services/api/src/api/`.

| Module | Path | Scope |
|---|---|---|
| Gateway / widget admission | `gateway/`, `edge.py`, `ratelimit.py` | Public client key + Origin allowlist, visitor session minting, rate limiting |
| Auth & RBAC | `auth/`, `rbac/` | Admin JWT (httpOnly cookies), password reset, 4-role RBAC |
| Conversation orchestrator | `orchestrator/` | `answer_turn` 8-step grounded turn pipeline |
| Conversation store | `conversation_store/` | Idempotent append, windowed history + running summary, GDPR export/delete |
| RAG retrieval | `rag/` | Hybrid pgvector-HNSW + Postgres full-text, RRF fusion, confidence signal |
| LLM provider | `llm/` | Provider-agnostic Protocol (generate/classify/stream/embed); Anthropic / OpenAI-compatible / Azure; per-tenant encrypted config; no default provider |
| Leads + CRM | `leads/`, `crm/` | Pipeline, qualification, activities, CSV export, webhook CRM sync, consent-gated |
| Scheduling | `scheduling/` | Availability, slots, booking, Google `CalendarProvider`, reminder jobs |
| Notifications | `notifications/` | Per-tenant `NotificationProvider`, exactly-once job flip (Celery worker) |
| Ingestion | `ingestion/` | Upload → parse (txt/docx) → chunk → embed → idempotent pgvector UPSERT (Celery worker) |
| Observability & audit | `observability/`, `audit/` | Prometheus `/metrics`, optional Sentry, correlation IDs, tenant-scoped audit trail |
| Tenants / Celery plumbing | `tenants/`, `seed.py`, `tasks/` | Tenant records, dev seed script, shared `celery_app` |

Reference architecture diagram: `system_flow/chatbotarchitecture.png`. Constitution and the
authoritative as-built module table live in `CLAUDE.md` §5b. Detailed sprint history and audit
findings: `dev_plan/DEVELOPMENT_PLAN.md` and `dev_plan/PRODUCT_AUDIT_2026-07-11.md`.

---

## 4. Multi-tenancy & security model

These are differentiators, not just implementation detail — they're what makes it safe to put
one codebase behind multiple clients' customer-facing chat.

- **Repository-layer isolation.** Every repository method takes `AuthClaims` (carrying
  `tenant_id`) and filters by it; no method runs without tenant context. `tenant_id` is never
  accepted from user/visitor input — it comes only from the admin JWT or the signed visitor
  session minted at the gateway, and it is immutable once set at creation/ingestion time.
- **RBAC, enforced at the data layer.** Four roles — `PLATFORM_ADMIN` (global),
  `CLIENT_ADMIN`, `CLIENT_AGENT`, `VISITOR` (anonymous, session-only) — with authorization as
  a query filter, not just a UI gate.
- **Widget admission without a shared secret.** The public `client_key` lives in client-side
  JS and is not treated as a secret; abuse protection comes from the per-tenant Origin
  allowlist plus IP/key rate limiting, exchanged for a short-lived signed visitor session.
- **Encryption at rest.** AES-256-GCM (unique nonce, verified auth tag) for tenant secrets —
  LLM provider keys, OAuth tokens, client secrets. Admin passwords use PBKDF2-SHA256 (120k
  iterations, per-password salt, constant-time compare). Password-reset tokens are single-use
  and time-limited.
- **No silent fallbacks for data integrity.** If live data or the LLM call fails, the system
  fails explicitly (mapped through a centralized error hierarchy with `UPPER_SNAKE_CASE`
  codes and a correlation ID) rather than serving a fabricated or cached-stale answer.
  Infrastructure fallbacks (e.g. Redis down → in-memory rate limiting) are allowed, but must
  be explicit.
- **GDPR posture.** Explicit consent is captured before contact details are stored or
  reminders are scheduled; conversation data supports export and deletion; PII is minimized
  in logs and never appears in log lines alongside secrets/tokens.
- **Background-task idempotency.** Ingestion and notification jobs are idempotent and
  retryable (exponential backoff + jitter, bounded retries); reminder jobs are claimed via an
  atomic SQL flip to guarantee exactly-once delivery.

---

## 5. Getting started

### Prerequisites

- Python 3.11+ in a conda-style venv at `venv/` in the repo root (interpreter:
  `venv/python.exe` — **not** `venv/Scripts/python.exe`)
- Docker Desktop (running) — for Postgres, PgBouncer, and Redis
- `psql` (PostgreSQL client) for manual DB inspection
- `cmd.exe` recommended for the manual-test recipes below (PowerShell's `$env:` syntax
  differs from the `set "VAR=value"` form used here)

### Environment

```cmd
copy deploy\.env.example .env
```

`.env.example` is documentation, not defaults — every required variable must be filled in or
the app refuses to start (fail-fast, per `CLAUDE.md` §3). Minimum required values for local
dev:

```
DEPLOYMENT_MODE=saas
POSTGRES_USER=chatbot
POSTGRES_PASSWORD=chatbot
POSTGRES_DB=chatbot
DATABASE_URL=postgresql://chatbot:chatbot@localhost:6432/chatbot
DATABASE_URL_DIRECT=postgresql://chatbot:chatbot@localhost:5432/chatbot
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<at-least-32-random-characters>
SECRET_ENCRYPTION_KEY=<base64-encoded-32-byte-key>
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=C:\temp\chatbot-storage
```

`DATABASE_URL_DIRECT` (port 5432) is used for migrations; `DATABASE_URL` (port 6432, via
PgBouncer, `statement_cache_size=0`) is used by the running app — PgBouncer's transaction pool
mode cannot run DDL.

```cmd
mkdir C:\temp\chatbot-storage
```

### Start infrastructure

```cmd
docker compose -f deploy\docker-compose.dev.yml up -d
docker compose -f deploy\docker-compose.dev.yml ps
```

This brings up three services — `postgres` (pgvector/pgvector:pg16, port 5432), `pgbouncer`
(transaction pool mode, port 6432), and `redis` (port 6379) — all with healthchecks.

### Migrate

Migrations connect directly to Postgres (5432), not through PgBouncer:

```cmd
cd services\api
..\..\venv\python.exe -m alembic upgrade head
cd ..\..
```

### Seed (optional)

```cmd
cd services\api
set "SEED_TENANT_NAME=Acme Corp"
set "SEED_TENANT_SLUG=acme"
set "SEED_PLATFORM_ADMIN_EMAIL=platform-admin@example.com"
set "SEED_CLIENT_ADMIN_EMAIL=client-admin@example.com"
..\..\venv\python.exe -m api.seed
cd ..\..
```

Passwords are generated and printed once unless you set
`SEED_PLATFORM_ADMIN_PASSWORD` / `SEED_CLIENT_ADMIN_PASSWORD` explicitly.

### Run the API

```cmd
venv\python.exe -m uvicorn api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

### Run the workers (separate terminals)

```cmd
venv\python.exe -m celery -A api.tasks.celery_app worker --loglevel=info --pool=solo
venv\python.exe -m celery -A api.tasks.celery_app beat --loglevel=info
```

`--pool=solo` is required on Windows (prefork cannot fork; the thread pool is unreliable).

### Verify

```cmd
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

`/healthz` is liveness only (no dependency checks); `/readyz` checks Postgres and Redis and
returns `{"ready": true, "checks": {"database": true, "redis": true}}`. `/metrics` serves
Prometheus text format.

Exercise the widget-admission → chat flow end to end (requires a seeded tenant with a
`client_key` and an allowed Origin):

```cmd
curl -X POST http://localhost:8000/widget/session ^
  -H "Content-Type: application/json" ^
  -H "Origin: https://example-client-site.com" ^
  -d "{\"client_key\": \"<tenant-client-key>\"}"
```

This returns `{"visitor_token": "...", "expires_at": "..."}`. Use that token as a bearer
token to send a chat turn:

```cmd
curl -X POST http://localhost:8000/public/chat/message ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer <visitor_token>" ^
  -d "{\"message\": \"What are your hours?\"}"
```

The response is leak-free (no `tenant_id`/`visitor_id`) and includes `decision`
(`answer`/`clarify`/`escalate`), `confidence`, and cited `sources` (chunk identifiers + score,
never raw chunk content).

---

## 6. Configuration highlights

Full reference: `deploy/.env.example` (values below are placeholders — never commit real
secrets).

| Variable | Purpose |
|---|---|
| `DEPLOYMENT_MODE` | `saas` (shared multi-tenant) or `single_tenant` (dedicated install) |
| `DATABASE_URL` / `DATABASE_URL_DIRECT` | App DSN (via PgBouncer, 6432) / migration DSN (direct, 5432) |
| `REDIS_URL` | Rate limiting, JWT blacklist, Celery broker/result backend |
| `JWT_SECRET` | HS256 signing key for admin JWTs and visitor sessions (32+ random chars) |
| `SECRET_ENCRYPTION_KEY` | AES-256-GCM key for tenant secrets at rest (base64, 32 bytes) |
| `COOKIE_SECURE` / `COOKIE_SAMESITE` / `COOKIE_NAME` | Admin session cookie attributes |
| `ACCESS_TOKEN_TTL_SECONDS` / `PASSWORD_RESET_TTL_SECONDS` | Admin JWT and reset-token lifetimes |
| `PASSWORD_RESET_URL_BASE` | Base URL the reset link is built from (points at admin-web) |
| `VISITOR_SESSION_TTL_SECONDS` | Widget visitor session lifetime |
| `WIDGET_SESSION_RATE_LIMIT_MAX` / `_WINDOW_SECONDS` | Rate limit on `POST /widget/session` |
| `AUTH_RATE_LIMIT_MAX` / `_WINDOW_SECONDS` | Rate limit on admin auth endpoints |
| `LLM_MAX_TOKENS` / `LLM_DEFAULT_MODEL` / `LLM_MAX_RETRIES` / `LLM_TIMEOUT_SECONDS` | LLM call defaults (per-tenant config overrides these; there is intentionally **no** hardcoded default provider) |
| `STORAGE_BACKEND` / `STORAGE_LOCAL_ROOT` | Ingestion upload storage (`local` today; S3/GCS planned) |
| `INGESTION_MAX_UPLOAD_BYTES` | Upload size cap |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Defaults to `REDIS_URL` if unset |

---

## 7. Testing & quality

Test pyramid: many unit tests, some integration tests, few end-to-end — behavior at
boundaries, not implementation. ~70 unit test modules currently under
`services/api/tests/unit` plus `services/common/tests`. Mandatory coverage per
`CLAUDE.md` §3: multi-tenant isolation (tenant A can never read tenant B's data), RBAC per
role, and idempotency for ingestion/notification tasks.

```cmd
REM Lint
venv\python.exe -m ruff check services\api
venv\python.exe -m ruff check services\common

REM Type check (strict)
cd services\api  && ..\..\venv\python.exe -m mypy --strict src && cd ..\..
cd services\common && ..\..\venv\python.exe -m mypy --strict src && cd ..\..

REM Unit tests
venv\python.exe -m pytest services\api\tests\unit -q
venv\python.exe -m pytest services\common\tests\unit -q

REM Integration tests (requires TEST_DATABASE_URL + live Postgres)
venv\python.exe -m pytest services\api\tests -q
venv\python.exe -m pytest services\common\tests -q
```

CI target (not yet wired — see roadmap): lint → typecheck → unit → integration → build →
smoke, with enforced coverage thresholds. Backend work follows TDD (`superpowers:tdd` /
`CLAUDE.md` §6b): red test first, then implementation.

---

## 8. Project structure

```
marketing_chatbot/
├── CLAUDE.md                      # project constitution — read this first
├── .claude/skills/<service>/      # one skill per service module
├── services/
│   ├── common/                    # platform-foundations: repo Protocol, AuthClaims,
│   │                               #   errors, settings, logging, cache, pgvector, crypto
│   └── api/                       # the FastAPI modular monolith
│       ├── src/api/
│       │   ├── gateway/ edge.py ratelimit.py   # widget admission
│       │   ├── auth/ rbac/                      # admin JWT, RBAC
│       │   ├── orchestrator/                    # conversation brain (answer_turn)
│       │   ├── conversation_store/
│       │   ├── rag/ llm/
│       │   ├── leads/ crm/
│       │   ├── scheduling/
│       │   ├── notifications/                   # Celery worker module
│       │   ├── ingestion/                       # Celery worker module
│       │   ├── observability/ audit/
│       │   ├── tenants/ seed.py tasks/
│       │   ├── config.py app.py
│       ├── migrations/versions/                 # Alembic, raw SQL
│       └── tests/unit/ tests/integration/
├── deploy/                        # docker-compose.dev.yml, .env.example
├── dev_plan/                      # DEVELOPMENT_PLAN.md, sprint specs, audit reports
├── knowledge_base/, system_flow/  # canonical engineering standard + architecture (read-only)
└── apps/                          # widget + admin-web — planned, not yet present
```

---

## 9. Status & roadmap

Phases and sprint statuses tracked in `dev_plan/DEVELOPMENT_PLAN.md` §3b; findings from the
most recent audit in `dev_plan/PRODUCT_AUDIT_2026-07-11.md`.

| Phase | Status |
|---|---|
| P0–P4, P6–P8 — foundation, auth/tenancy, gateway, LLM provider, conversation store, RAG, leads/CRM, scheduling | **Done** |
| P5 — document ingestion | Done, except PDF/OCR parsing, the ingestion run-status endpoint, and the crawler source |
| P9 — notifications | Done |
| P10 — conversation orchestrator | First slice (turn pipeline: session → store → retrieve → grounded answer) in review; intent classification, consent gating, scheduling fallback, and streaming not yet built |
| P11 — analytics & observability | Audit trail and HTTP metrics done; tracing and conversation-analytics endpoints not yet built |
| P12 — admin API | Not started |
| P13 — admin web console (Next.js) | Not started |
| P14 — embeddable chat widget (React + Shadow DOM) | Not started |
| Infra track — Nginx, production Docker images, CI | Not started |

An audit-remediation sprint is queued ahead of further orchestrator work — see
`dev_plan/DEVELOPMENT_PLAN.md` §7.

---

## 10. Contributing / dev workflow

- Start with `CLAUDE.md` — it is the always-loaded constitution and wins over any
  conflicting guidance. Per-service detail lives in `.claude/skills/<service>/SKILL.md`;
  load the relevant skill before touching a module.
- Sprint plan, decisions, and status live in `dev_plan/DEVELOPMENT_PLAN.md` and
  `dev_plan/DESIGN_DECISIONS_AI_BRAIN.md`.
- `knowledge_base/` and `system_flow/` are the canonical, read-only engineering standard and
  architecture reference.
- Version control is a human decision in this repo — agents do not run git write commands;
  changes are reviewed and committed by a person.

## License

Proprietary — iSN Business Solutions. All rights reserved.
