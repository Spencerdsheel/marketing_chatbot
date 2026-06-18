# CLAUDE.md — Chatbot Platform

> Always-loaded project constitution. Every agent obeys this file. Service-specific detail lives in
> per-service skills under `.claude/skills/`. When this file conflicts with a skill, **this file wins**.
> When the `knowledge_base/` standard conflicts with `system_flow/solution_flow.docx`, **the
> knowledge_base wins** (it is the canonical engineering standard).

---

## 1. What we're building

An **embeddable, multi-tenant chatbot platform** shipped to clients. It is far more than a chat box:

- **Embeddable widget** dropped onto any client website via one script tag.
- **Lead capture + built-in CRM** (pipeline, qualification, agent assignment, export, optional sync out).
- **AI "brain"** — RAG over client-specific knowledge + provider-agnostic LLM, with a confidence/turn-count
  fallback to scheduling.
- **Call/meeting scheduling** with calendar sync and reminder automation (3d / 24h / 1h).
- **Notifications** (email default; optional SMS/WhatsApp).
- **Admin console** for client onboarding, knowledge upload, lead review, conversation analytics, and config.
- **Document ingestion** pipeline (parse/OCR → chunk → embed → pgvector).

### Delivery model — HYBRID (non-negotiable)
One codebase supports **both**:
1. **Multi-tenant SaaS** — many client tenants on shared infrastructure (default).
2. **Dedicated single-tenant install** — one client, isolated deployment.

The deployment mode is driven by **configuration**, not code branches. **Tenant isolation is always on at
the data/repository layer** regardless of mode. Code must never assume "only one tenant exists."

---

## 2. Architecture map

Source of truth: `system_flow/chatbotarchitecture.png` and `system_flow/solution_flow.docx`.

```
Website Visitor
   │
   ▼
Embedded Chat Widget ── Voice/Prompt Layer          [apps/widget]
   │
   ▼
API Gateway / BFF (Nginx + FastAPI)                 [api-gateway-bff]
   ├── Auth & Session Service                        [auth-session-service]
   ├── Conversation Orchestrator ──┬── RAG Retrieval [conversation-orchestrator / rag-retrieval]
   │                               ├── LLM Provider  [llm-provider]
   │                               ├── Conversation Store [conversation-store]
   │                               └── Analytics/Logs/Traces [analytics-observability]
   ├── Lead Capture + CRM ── Lead DB / CRM Sync      [lead-capture-crm]
   ├── Scheduling Service ── Calendar + Scheduler/Queue [scheduling-service]
   │        └── Notification Service ── Email / SMS / WhatsApp [notification-service]
   └── Admin API (Client Mgmt, Question Upload, Lead Review) [admin-api]
            └── Document Ingestion ── Parser/OCR → Chunk/Embed → Vector(pgvector) [document-ingestion-service]

Admin Web Console (Next.js)                          [apps/admin-web]
```

### Topology — HYBRID
- **Core modular monolith** — one FastAPI app sharing `services/common` + one PostgreSQL. Modules:
  `api-gateway-bff` (BFF half), `auth-session-service`, `conversation-orchestrator`, `rag-retrieval`,
  `llm-provider`, `conversation-store`, `lead-capture-crm`, `scheduling-service`, `admin-api`,
  `analytics-observability`. Each module has strict seams (own router, repository, models, schemas) so it can
  be extracted into its own service later **without rewrites**.
- **Carved-out deployables** (queue/worker-driven, scale independently): `document-ingestion-service`,
  `notification-service`, and the **reminder scheduler** (Celery Beat).
- **Process split:** `api`, `celery-worker`, `celery-beat`, `widget`, `admin-web`, plus `nginx`, `postgres`,
  `pgbouncer`, `redis`.

---

## 3. Non-negotiable standards

These apply to **every** service. Skills reference these rather than restating them. Derived from
`knowledge_base/`.

### Multi-tenancy (highest priority)
- Tenant isolation is enforced at the **repository layer**, not the API layer.
- `tenant_id` is **never** accepted from user/visitor input. It comes from `AuthClaims` (admin JWT) or the
  signed visitor session minted by the gateway.
- Every repository method takes `AuthClaims` (carrying `tenant_id`) and filters by it. No method works
  without tenant context.
- `tenant_id` is established at creation/ingestion time and is **immutable**.
- Client-facing responses strip internal tenant-scoped fields.

### Data access
- **Repository pattern via `typing.Protocol`.** Define the contract; implement per backend; select via env.
- **No ORM for queries** — raw async SQL with `asyncpg`, **parameterized only** (never string-format SQL).
  SQLAlchemy/Alembic for migrations only.
- **pgvector** holds embeddings in the same Postgres, accessed through the repository pattern.
- **Cache-aside** with Redis; cache keys **always include `tenant_id`**; TTL reflects data volatility;
  invalidate on mutation, never on read.

### AuthZ / RBAC (4 roles)
- `PLATFORM_ADMIN` — global (`tenant_id = null`), manages all tenants. Platform operator only.
- `CLIENT_ADMIN` — manages their own tenant's bot, knowledge, users, config.
- `CLIENT_AGENT` — reviews leads & conversations within their tenant; **cannot** change config.
- `VISITOR` — anonymous website visitor; signed short-lived session only.
- Enforce at the data layer (authorization is a *filter*, not just a UI gate). Roles live in JWT claims.

### AuthN
- **Admin/agent:** JWT (HS256) in **httpOnly + Secure + SameSite** cookies; Redis blacklist for logout;
  single-use, time-limited password-reset tokens; PBKDF2-SHA256 (120k iters, per-password salt, constant-time
  compare).
- **Widget visitor:** public **client key** + per-tenant **Origin allowlist** validated at the gateway →
  short-lived **signed session** carrying `tenant_id` + anonymous `visitor_id`. The client key is public
  (lives in client-side JS) and is **not** a secret; abuse protection comes from the Origin allowlist +
  IP/key rate limiting.

### Errors & resilience
- Custom exception hierarchy: `AppException` → `NotFoundError` (404), `AuthorizationError` (401/403),
  `RateLimitError` (429), `ValidationError` (422), `InternalServerError` (500).
- One centralized error middleware maps exceptions → HTTP, attaches a **correlation ID**, logs full detail
  server-side, returns user-safe messages with **UPPER_SNAKE_CASE** error codes.
- **No silent fallbacks** for data integrity (never serve fake/sample answers when live data/LLM fails — fail
  explicitly). Infrastructure fallbacks are allowed and must be explicit (Redis down → in-memory rate limit;
  replica down → primary).
- Background tasks are **idempotent and retryable** (exponential backoff + jitter, max retries, dead-letter).
- Correlation IDs propagate from gateway through every layer and into every log line.

### Security
- AES-256-GCM (unique nonce, verified auth tag) for secrets at rest (provider keys, OAuth tokens, client
  secrets); keys from env, never in code/DB plaintext; plan for key rotation.
- Validate all input with Pydantic (422 on bad input). Rate limit (auth, admin, global tiers; Redis-backed,
  in-memory fallback). Security headers + strict CORS at Nginx. Never log secrets/tokens/PII.
- **GDPR/consent:** capture explicit consent before storing contact details or scheduling reminders; support
  data export and deletion; minimize PII in logs. Treat consent as a cross-cutting requirement.

### Config & observability
- **Pydantic Settings**; validate at startup; **fail fast** on missing required config; `.env.example` is
  documentation, not defaults.
- **Structured JSON logging** with correlation ID + contextual fields (`tenant_id`, `user_id`/`visitor_id`,
  endpoint). Prometheus metrics (`/metrics`), Sentry for errors. Health: `/healthz` (liveness, no deps),
  `/readyz` (readiness, checks DB + Redis).
- **Audit trail** for auth events, admin actions, and data mutations.

### Testing
- Test pyramid: many unit, some integration, few e2e. Test behavior at boundaries, not implementation.
- **Mandatory:** multi-tenant isolation tests (tenant A cannot read tenant B), RBAC tests per role,
  idempotency tests for ingestion/notification tasks. CI: lint → typecheck → unit → integration → build →
  smoke. Enforce coverage thresholds.

---

## 4. Tech stack (locked)

| Layer | Choice |
|------|--------|
| Backend API | **FastAPI** (async), Pydantic models, dependency injection |
| DB | **PostgreSQL** + **asyncpg** (no ORM), **pgvector**, **PgBouncer** (transaction mode); Alembic migrations |
| Cache / broker | **Redis** |
| Background | **Celery** + **Celery Beat** |
| LLM | **Provider-agnostic** `LLMProvider` Protocol (generate/classify/stream/embed); Anthropic, OpenAI, Azure as first-class impls; **no default** — chosen per-tenant via config |
| Vector store | **pgvector** (single implementation, via repository pattern) |
| Admin web | **Next.js** App Router + **React Server Components** + **shadcn/ui** + Tailwind; server-first, server actions; TS strict; Zod |
| Widget | **React + TypeScript + Shadow DOM**, self-contained bundle, browser TTS greeting |
| Gateway | **Nginx** (SSL termination, path routing, security headers, correlation IDs) |
| Packaging | **Docker** multi-stage, non-root, healthchecks; Docker Compose (dev + prod) |
| Config | **Pydantic Settings** (backend) / Zod (frontend) |
| Observability | structured JSON logs, **Prometheus**, **Sentry** |

---

## 5. Intended repo layout

```
chatbot/
├── CLAUDE.md                  # this file
├── .claude/skills/<service>/SKILL.md   # one skill per service
├── services/
│   ├── common/                # platform-foundations: repo Protocol, AuthClaims, errors, settings,
│   │                          #   logging, cache, pgvector access, RBAC, crypto
│   ├── api/                   # FastAPI app wiring the core monolith modules + gateway BFF
│   ├── gateway/               # (or Nginx conf) edge routing/auth — see api-gateway-bff
│   ├── auth/                  # auth-session-service
│   ├── conversation/          # conversation-orchestrator
│   ├── rag/                   # rag-retrieval
│   ├── llm/                   # llm-provider
│   ├── conversation_store/    # conversation-store
│   ├── leads/                 # lead-capture-crm
│   ├── scheduling/            # scheduling-service
│   ├── admin/                 # admin-api
│   ├── analytics/             # analytics-observability
│   ├── ingestion/             # document-ingestion-service (worker)
│   └── notifications/         # notification-service (worker)
├── apps/
│   ├── widget/                # chat-widget (React + Shadow DOM)
│   └── admin-web/             # admin-web (Next.js)
├── deploy/                    # docker-compose, nginx, postgres tuning, .env.example
└── knowledge_base/ , system_flow/   # source standards + flows (read-only references)
```

---

## 6. How to work

1. **Before building or modifying a service, load its skill** via the Skill tool
   (e.g. `lead-capture-crm`). The skill carries that service's data model, API contract, patterns, and tests.
2. Always obey **this file** + the **`platform-foundations`** skill (shared library + universal patterns).
3. Cite the relevant `knowledge_base/` sections; reuse `services/common` utilities rather than reinventing.
4. Keep module seams strict — cross-module access goes through repositories/contracts, never reaching into
   another module's internals or tables directly.
5. Process work first, then implementation: brainstorm/plan, then TDD where applicable.

### Skill index

| Skill | Scope |
|-------|-------|
| `guardrails` | How agents must behave here: git hands-off, spec/secret protection, no silent fallbacks, scope, TDD — and which rules the `.claude/hooks/` enforce |
| `platform-foundations` | `services/common`: repo Protocol, AuthClaims, multi-tenancy, errors, settings, logging, cache, pgvector, RBAC, crypto |
| `api-gateway-bff` | Edge: routing, SSL/headers, CORS, correlation IDs, rate limiting, widget key + Origin allowlist, visitor session minting |
| `auth-session-service` | Admin JWT/cookies, visitor signed sessions, password reset, RBAC role model |
| `conversation-orchestrator` | Turn mgmt, intent routing, confidence + 6–7-turn fallback to scheduling, guardrails, consent gating |
| `rag-retrieval` | Tenant-isolated retrieval over client knowledge, pgvector queries, ranking, confidence signals |
| `llm-provider` | Provider-agnostic LLM Protocol (generate/classify/stream/embed), per-tenant provider+model config |
| `conversation-store` | Conversation/message persistence, history windowing, analytics hooks |
| `lead-capture-crm` | Lead form/model, pipeline, qualification, agent assignment, export, CRMSync connectors |
| `scheduling-service` | Availability, ScheduleEvent, CalendarProvider sync, booking flow, reminder jobs |
| `admin-api` | Tenant onboarding/config, user mgmt, knowledge upload trigger, lead review, analytics, settings |
| `analytics-observability` | Logs/traces, Prometheus, Sentry, conversation analytics, audit trail |
| `document-ingestion-service` | Parse/OCR → chunk → embed → pgvector; idempotent UPSERT; run logs (worker) |
| `notification-service` | NotificationProvider Protocol; email/SMS/WhatsApp; confirmation + reminder jobs (worker) |
| `chat-widget` | Embeddable React + Shadow DOM widget; lead form; quick replies; schedule CTA; a11y; TTS greeting |
| `admin-web` | Next.js App Router + RSC + shadcn/ui admin console; server-first; RBAC-aware |

---

## 7. Agent guardrails (hard rules)

Some standards in this file are mechanically **enforced** by Claude Code hooks in `.claude/hooks/` (wired in
`.claude/settings.json`). They block the action (exit 2) and feed the reason back to the agent. Full detail
lives in the **`guardrails`** skill — load it for any "am I allowed to…?" question.

- **Git is the user's job — never the agent's.** The entire git **write path** is blocked: no `git add`,
  `commit`, `push`, `merge`, `rebase`, `reset`, `checkout`/`switch`, `stash`, `tag -d`, `branch -d/-D`,
  `remote add/set-url`, `clean`, etc. Read-only git (`status`/`log`/`diff`/`show`/`fetch`) is fine. When work
  is ready to version, **ask the user to run git themselves** (e.g. via the `!` prefix). Never use
  `--no-verify` or other bypass flags. *(enforced: `block_commands.py`)*
- **No destructive deletes.** `rm -rf`/`rm -fr` and `Remove-Item -Recurse -Force` are blocked; remove
  specific paths or ask the user. *(enforced: `block_commands.py`)*
- **The spec is read-only.** `knowledge_base/` and `system_flow/` are always blocked; `CLAUDE.md`,
  `.claude/skills/**`, `.claude/settings.json`, `.claude/hooks/**` are blocked unless deliberate spec work
  (`CHATBOT_EDIT_SPEC=1` or the `.claude/.allow_spec_edit` sentinel). *(enforced: `protect_paths.py`)*
- **No hardcoded secrets.** Content matching AWS/private/LLM keys or `api_key|secret|password|token = "…"`
  literals is blocked; use env / Pydantic Settings + AES-256-GCM at rest, placeholders in `.env.example`.
  *(enforced: `protect_paths.py`)*
- **Verify before "done."** A Stop hook reminds the agent to run lint + typecheck + tests (with real output)
  and re-confirm git was untouched before claiming completion. *(enforced: `verify_reminder.py`)*

Do **not** disable, edit, or route around these hooks. If a guardrail is wrong, surface it to the user —
changing the guardrails is the user's decision, not the agent's.
