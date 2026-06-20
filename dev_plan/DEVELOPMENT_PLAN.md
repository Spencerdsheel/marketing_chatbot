# Chatbot Platform — Development Plan (Sprint Backlog)

> Living delivery plan. The **spec** is `CLAUDE.md` + `.claude/skills/**` + `knowledge_base/**` (read-only,
> authoritative). This file is the **how/when** — the dependency-ordered sprint backlog and the operating
> model the agents follow. `first_phase_chatbot/` is a **reference only** (different stack: NestJS/Prisma/TS).
> We port its *flows and data model*, not its code — its "AI" was a deterministic stub (no real LLM, no real
> vector search).

---

## 1. Operating model (how each sprint runs)

A fixed loop per sprint. **Implementation is done by a Qwen model running in opencode**; Opus plans and
reviews; the user runs Qwen, tests manually, and owns git.

| Role | Who | Responsibility |
|------|-----|----------------|
| **Planner / reviewer / fix-author / integrator** | **Opus** (this agent) | Writes the just-in-time **sprint spec** (`dev_plan/sprints/SX.md`); after Qwen implements, reviews as a **senior tester** (flag-only) — may dispatch a review/test agent whose model is chosen by complexity (Haiku=simple CRUD, Sonnet=auth/RAG/orchestrator/security); reads security-critical files; re-runs the suite via `venv/python.exe`; live-verifies new SQL; authors fix briefs for logic bugs. |
| **Implementer** | **Qwen** (in opencode) | Reads `dev_plan/QWEN_IMPLEMENTATION_GUIDE.md` + the sprint spec; implements test-first; self-verifies `ruff`/`mypy`/`pytest`; reports. opencode loads `CLAUDE.md` + `.claude/skills/**` natively but does **not** run `.claude/hooks/` — the guide encodes those guardrail rules. |
| **Manual tester / git owner** | **User** | Runs Qwen, performs the Postman/curl manual test, runs all git. |

**Per-sprint loop:**
1. **Opus specs** the sprint into `dev_plan/sprints/SX.md`.
2. **Handoff** — Opus tells the user: *"In opencode, read `dev_plan/QWEN_IMPLEMENTATION_GUIDE.md` then
   `dev_plan/sprints/SX.md`, and implement."*
3. **Qwen implements** test-first, self-verifies (`ruff`/`mypy`/`pytest` green via `venv/python.exe`), reports.
4. **Opus reviews as senior tester** — flag issues/bugs only; re-verify the suite; read critical files;
   live-check new SQL against the real DB (fake/stub-DB tests miss column drift — see the S1.2 lesson).
5. **Fix routing** — Opus/its agents may directly apply **trivial mechanical fixes** (lint, formatting, obvious
   typos); **behavioral / logic / security / tenancy bugs** become a fix brief (`dev_plan/sprints/SX-fix-N.md`)
   handed to the user → Qwen → re-review.
6. **User manually tests** (Postman/curl) via the sprint's recipe.
7. **Opus marks the sprint DONE** and proceeds.

**Definition of Done (every backend sprint):** TDD; `ruff` clean; `mypy --strict` clean; unit + isolation +
RBAC tests green (+ idempotency for workers); a live/integration check for any new SQL; the feature reachable
on the **running FastAPI app** and verified via the Postman/curl recipe; no hardcoded secrets; no silent
fallbacks; no `demo`/`dummy`/`fake` anywhere.

**Guardrails under opencode:** the `.claude/hooks/` do NOT run for Qwen. Their rules (spec read-only, no
secrets, git hands-off, no destructive deletes, verify-before-done) are encoded in
`dev_plan/QWEN_IMPLEMENTATION_GUIDE.md` §2 and enforced by Opus in review; the git rule is additionally a
project opencode permission. Recommended: extend `opencode.json` to also deny edits to the spec paths and deny
destructive deletes.

---

## 2. Sprint sizing & status legend

- Sprints are **thin** — one narrow, independently Postman-testable slice each. A module spans several sprints.
- Near-term phases (0–2) are specified in detail; later phases are epics that get a detailed sprint spec
  just-in-time at their start (scope may shift as we learn). Order follows the dependency graph.
- Status: `TODO` · `IN PROGRESS` · `IN REVIEW` (awaiting user manual test) · `DONE`.

---

## 3. Phase map (dependency order)

```
P0 Runnable foundation ─► P1 Auth & tenancy ─► P2 Gateway/public edge ─► P3 LLM provider
   │                                                                          │
   └─► P4 Conversation store ◄───────────────────────────────────────────────┤
   P5 Ingestion worker ─► P6 RAG retrieval ◄──────────────────────────────────┘
   P7 Leads ── P8 Scheduling ── P9 Notifications (worker)
                          └────────────┬───────────────┘
   P10 Conversation orchestrator (the brain) ◄─ needs P3,P4,P6,P7,P8,P11
   P11 Analytics & observability   P12 Admin API ◄─ aggregates P1,P5,P7,P10,P11
   P13 Admin web (Next.js)   P14 Chat widget (React/Shadow DOM)   [frontends last]
   Infra track (Nginx, Dockerfiles, CI) — interleaved, lands with P0 and hardened later
```

Shortest end-to-end vertical slice (visitor chats, gets RAG-grounded answers):
`P0 → P1 → P2 → P3 → P4 → P5 → P6 → P10.1`.

---

## 4. Sprint backlog

### Phase 0 — Runnable foundation (so Postman works from day one)

**S0.1 — Dev infra: compose + Postgres/pgvector/Redis** · Haiku · depends: —
- `deploy/docker-compose.dev.yml` (postgres+pgvector, redis, pgbouncer), root `.env.example`, Postgres init
  that runs `CREATE EXTENSION vector`.
- **Test:** `docker compose -f deploy/docker-compose.dev.yml up -d`; containers healthy; `psql` shows the
  `vector` extension present.

**S0.2 — `services/api` FastAPI shell wired to `common`** · Sonnet · depends: S0.1
- App factory loading `common.settings` (fail-fast), `common.logging` JSON logs, correlation-ID middleware,
  centralized error middleware mapping `AppException → {error_code,message,correlation_id}`, and
  `/healthz` + `/readyz` (DB+Redis via `common.health`) + `/metrics`.
- **Test (Postman):** `GET /healthz` → 200 liveness; `GET /readyz` → JSON with db/redis ok; `GET /metrics` →
  Prometheus text. Stop Redis → `/readyz` reports redis fail (no silent pass).

**S0.3 — Alembic migration harness** · Haiku · depends: S0.2
- Alembic configured against `DATABASE_URL`; empty baseline + a smoke migration; `make`/script targets to
  upgrade/downgrade. (Business tables arrive with their modules.)
- **Test:** run upgrade → `alembic_version` table exists; downgrade/upgrade round-trips cleanly.

### Phase 1 — Auth & tenancy foundation

**S1.1 — Tenants/users/roles schema + tenant repo** · Haiku · depends: S0.3
- Migration for `tenants`, `users`, `roles` (4-role model: PLATFORM_ADMIN/CLIENT_ADMIN/CLIENT_AGENT/VISITOR);
  `PostgresRepository`-based access; seed script creating one platform admin + one initial tenant + one client admin.
- **Test:** migrate + seed; `psql` shows seeded rows; isolation unit test (tenant A ≠ tenant B) green.

**S1.2 — Admin/agent login → JWT in httpOnly cookie** · Sonnet · depends: S1.1
- `POST /auth/login`: verify password via `common.crypto.verify_password`; mint HS256 JWT (claims → `AuthClaims`);
  set httpOnly + Secure + SameSite cookie.
- **Test (Postman):** login with seeded admin → 200 + `Set-Cookie`; wrong password → 401 `UNAUTHENTICATED`.

**S1.3 — Auth dependency resolving `AuthClaims` + `/auth/me`** · Sonnet · depends: S1.2
- FastAPI dependency that validates the cookie JWT → `AuthClaims`; protected `GET /auth/me`.
- **Test (Postman):** `/auth/me` with login cookie → claims; without cookie → 401.

**S1.4 — Logout + Redis token blacklist** · Sonnet · depends: S1.3
- `POST /auth/logout` clears cookie + blacklists jti in Redis; auth dependency rejects blacklisted tokens.
- **Test (Postman):** logout → cookie cleared; reuse old token → 401.

**S1.5 — Password reset (request + confirm)** · Sonnet · depends: S1.3
- Single-use, time-limited reset token (in dev, token is logged/returned since email lands in P9); confirm sets
  a new PBKDF2 hash.
- **Test (Postman):** request reset → token (from logs); confirm with new password → login works; reuse token → 401.

**S1.6 — RBAC enforcement helpers on routes** · Haiku · depends: S1.3
- Apply `common.tenancy.require_role` as route guards; a sample CLIENT_ADMIN-only and PLATFORM_ADMIN-only endpoint.
- **Test (Postman):** agent token hitting an admin-only route → 403 `ROLE_NOT_PERMITTED`.

### Phase 2 — Gateway / public edge

**S2.1 — Client key + Origin allowlist → signed visitor session** · Sonnet · depends: S1.1
- `POST /public/session`: validate public client key + per-tenant Origin allowlist; mint short-lived **signed
  visitor session** carrying `tenant_id` + anonymous `visitor_id` (VISITOR `AuthClaims`).
- **Test (Postman):** valid key + allowed Origin → signed session token; disallowed Origin → 403; bad key → 401.

**S2.2 — Rate limiting (Redis, tiered) + Retry-After** · Sonnet · depends: S2.1
- Redis-backed limiter (auth/admin/global tiers) with explicit in-memory fallback if Redis down.
- **Test (Postman):** exceed limit on a public route → 429 `RATE_LIMITED` + `Retry-After`.

**S2.3 — Security headers + strict CORS** · Haiku · depends: S2.1
- Security headers + per-tenant CORS at the app edge (Nginx conf deferred to infra track).
- **Test (curl):** response carries security headers; disallowed origin blocked by CORS.

### Phase 3 — LLM provider (no default; per-tenant config)

**S3.1 — `LLMProvider` Protocol + Anthropic `generate` + encrypted per-tenant config** · Sonnet · depends: S1.1
- Protocol (generate/classify/stream/embed); Anthropic impl for `generate`; per-tenant provider+model+API key
  stored encrypted via `common.crypto.SecretBox`. Default to the latest Claude model.
- **Test (Postman):** seed a tenant LLM config; `POST /debug/llm/generate {prompt}` → real Claude completion.

**S3.2 — `embed`** · Sonnet · depends: S3.1
- Embeddings via the configured provider.
- **Test (Postman):** `POST /debug/llm/embed {text}` → vector of expected dimension.

**S3.3 — `classify` + `stream`** · Sonnet · depends: S3.1
- Classification helper + streaming generate.
- **Test (Postman/curl):** `classify` → label+score; `stream` → chunked tokens.

**S3.4 — OpenAI + Azure impls + retries/backoff + token/cost** · Sonnet (×2 parallel) · depends: S3.1
- Two more impls behind the same Protocol; exponential backoff + jitter; token/cost capture.
- **Test (Postman):** switch a tenant's provider config to OpenAI → same `/debug/llm/generate` now routes there.

### Phase 4 — Conversation store

**S4.1 — Conversation + Message tables + repo** · Haiku · depends: S1.1
- Tenant-scoped `conversations` + `messages` (role, content, intent, confidence, decision, metadata).
- **Test (Postman):** debug endpoints to create a conversation + append messages; tenant isolation enforced.

**S4.2 — History windowing + fetch** · Haiku · depends: S4.1
- Windowed history retrieval (last N) for context.
- **Test (Postman):** append >N messages → fetch returns the last N in order.

**S4.3 — Retention/deletion + analytics hooks** · Haiku · depends: S4.1
- GDPR delete/export by conversation; emit events for analytics.
- **Test (Postman):** delete conversation → rows gone; export returns transcript.

### Phase 5 — Document ingestion (Celery worker)

**S5.1 — Celery + Redis broker + healthy worker** · Sonnet · depends: S0.1
- `celery-worker` process + a no-op task; `celery-beat` placeholder.
- **Test:** enqueue debug task via API → worker log shows completion; inspect ping.

**S5.2 — Upload + object storage + parse (txt/docx, then pdf/OCR)** · Sonnet · depends: S5.1
- Upload to object storage (local driver in dev); parse txt/docx (port phase-1 Q&A extraction); pdf/OCR.
- **Test (Postman):** upload a doc → stored + parsed text returned in run record.

**S5.3 — Chunk + embed + idempotent UPSERT to pgvector** · Sonnet · depends: S5.2, S3.2
- Sentence-aware chunking; embeddings via llm-provider; UPSERT into pgvector keyed for idempotency.
- **Test (Postman):** ingest doc → pgvector rows present; re-ingest same doc → no duplicates (idempotent).

**S5.4 — Ingestion run logs + status endpoint** · Haiku · depends: S5.2
- Persist run status/errors; `GET /admin/ingestion/runs/{id}`.
- **Test (Postman):** poll run status → queued→running→succeeded.

### Phase 6 — RAG retrieval

**S6.1 — Tenant-isolated pgvector similarity search + top-k** · Sonnet · depends: S5.3
- Use `common.pgvector.similarity_search`; top-k over the tenant's chunks only.
- **Test (Postman):** `POST /debug/rag/search {query}` → relevant chunks for that tenant only (isolation verified).

**S6.2 — Hybrid/keyword ranking + confidence signal** · Sonnet · depends: S6.1
- Blend vector + keyword; emit the confidence signal the orchestrator consumes.
- **Test (Postman):** search returns ranked results + a confidence score.

### Phase 7 — Lead capture + CRM

**S7.1 — Lead table + capture endpoint + consent** · Haiku · depends: S2.1
- `leads` model; `POST /public/leads` (visitor session); explicit consent capture before storing contact details.
- **Test (Postman):** submit lead with consent → stored; without consent → 422.

**S7.2 — Pipeline stages + qualification scoring** · Sonnet · depends: S7.1
- Stage transitions + qualification score.
- **Test (Postman):** move a lead through stages; score recomputed.

**S7.3 — Notes/activity timeline + agent assignment** · Haiku · depends: S7.1
- Notes, activity log, assign to CLIENT_AGENT.
- **Test (Postman):** add note, assign agent → reflected on lead.

**S7.4 — Export + CRMSync (webhook first, then HubSpot/Salesforce)** · Sonnet · depends: S7.1
- CSV export; outbound webhook connector; provider connectors behind a `CRMSync` Protocol.
- **Test (Postman/curl):** export returns CSV; configure webhook → new lead fires it (capture with a test URL).

### Phase 8 — Scheduling

**S8.1 — Availability/slots + `ScheduleEvent` + native booking** · Sonnet · depends: S2.1
- Slot generation, `schedule_events`, native booking flow with timezone + consent.
- **Test (Postman):** `GET /public/schedule/slots` → slots; `POST /public/schedule/book` → event created.

**S8.2 — CalendarProvider (Google free-busy + sync)** · Sonnet · depends: S8.1
- `CalendarProvider` Protocol; Google free-busy + event sync (OAuth tokens encrypted at rest).
- **Test (Postman):** with a connected (or mocked) calendar, booked slot reflects free-busy + creates calendar event.

**S8.3 — Reminder jobs (3d/24h/1h) via Celery beat** · Sonnet · depends: S8.1, S5.1
- On booking, schedule idempotent reminder jobs at 3d/24h/1h.
- **Test:** book → three reminder jobs scheduled (inspect); idempotent on rebook.

### Phase 9 — Notification service (Celery worker)

**S9.1 — `NotificationProvider` + email default + idempotent send** · Sonnet · depends: S5.1
- Email impl (SMTP/MailHog in dev); idempotent + retryable send task.
- **Test:** trigger send → email visible in MailHog; retry doesn't double-send.

**S9.2 — Booking confirmation + reminder delivery + reset email** · Sonnet · depends: S9.1, S8.3, S1.5
- Wire confirmations, reminders, and password-reset emails to the provider.
- **Test:** book → confirmation email; reminder job fires → reminder email; reset flow now emails the token.

**S9.3 — Optional SMS/WhatsApp (Twilio)** · Sonnet · depends: S9.1
- Twilio channel behind the same Protocol.
- **Test:** send via SMS channel (Twilio test creds) → delivered/logged.

### Phase 10 — Conversation orchestrator (the brain)

**S10.1 — Turn pipeline: session → store → retrieve → grounded LLM answer** · Sonnet · depends: S3.1,S4.1,S6.1
- `POST /public/chat/message`: visitor session → store user msg → RAG retrieve → grounded `generate` → store +
  return answer with sources. No silent fallback if retrieval/LLM fails.
- **Test (Postman):** with ingested KB, ask a covered question → grounded answer citing tenant sources.

**S10.2 — Intent classification + confidence + 3-way decision** · Sonnet · depends: S10.1, S6.2
- Classify intent, score confidence, decide answer/clarify/escalate on per-tenant thresholds.
- **Test (Postman):** covered question → answer; vague question → clarify; off-topic → escalate.

**S10.3 — Consent gating + guardrails** · Sonnet · depends: S10.2
- Gate contact capture on consent; content guardrails on prompts/outputs.
- **Test (Postman):** escalation asks consent before collecting details; guardrail blocks disallowed content.

**S10.4 — Fallback-to-scheduling (low confidence or ~6–7 turns)** · Sonnet · depends: S10.2, S8.1
- When confidence stays low or turn count exceeds the cap, offer a scheduling CTA.
- **Test (Postman):** drive a conversation past the turn cap → response offers booking a call.

**S10.5 — Streaming responses** · Sonnet · depends: S10.1, S3.3
- Stream the assistant answer.
- **Test (curl):** streamed token chunks for a chat message.

### Phase 11 — Analytics & observability

**S11.1 — Audit trail** · Haiku · depends: S1.1
- Audit auth events, admin actions, data mutations.
- **Test (Postman):** perform an admin action → audit row recorded.

**S11.2 — Conversation analytics endpoints** · Sonnet · depends: S4.1, S10.2
- Fallback rate, schedule conversion, intent distribution, deflection; time-bucketed.
- **Test (Postman):** `GET /admin/analytics/overview` → metrics over seeded conversations.

**S11.3 — Domain Prometheus metrics + Sentry** · Haiku · depends: S0.2
- Conversation/LLM metrics on `/metrics`; Sentry error capture.
- **Test:** `/metrics` includes new counters; forced error appears in Sentry (dev DSN).

### Phase 12 — Admin API

**S12.1 — One-shot tenant onboarding** · Sonnet · depends: S1.1, S2.1
- Create tenant + bot config + public client key (hash stored) + initial CLIENT_ADMIN user.
- **Test (Postman):** PLATFORM_ADMIN onboards a client → returns client key once; client admin can log in.

**S12.2 — User mgmt + per-tenant settings** · Haiku · depends: S12.1
- CRUD users; settings (greeting, business hours, escalation policy, tone, confidence threshold, provider/model).
- **Test (Postman):** update settings → persisted + reflected by orchestrator config read.

**S12.3 — Knowledge upload trigger + status** · Haiku · depends: S5.2, S12.1
- Admin endpoint to upload knowledge → enqueues ingestion; surface run status.
- **Test (Postman):** upload via admin → ingestion run progresses to succeeded.

**S12.4 — Lead review + conversation analytics console endpoints** · Haiku · depends: S7.1, S11.2
- List/filter leads + conversations for the review console.
- **Test (Postman):** list leads/conversations scoped to tenant; agent sees only their tenant.

### Phase 13 — Admin web (Next.js) — tested in browser, not Postman

**S13.1** scaffold (App Router + RSC + shadcn/ui) + RBAC-aware middleware/login · Sonnet ·
**S13.2** client onboarding UI · **S13.3** knowledge upload UI · **S13.4** lead review console ·
**S13.5** conversation analytics dashboards · **S13.6** tenant settings.
- **Test:** browser walkthrough per screen against the live admin-api.

### Phase 14 — Chat widget (React + Shadow DOM) — tested in browser via a local host page

**S14.1** Shadow-DOM bundle scaffold + script-tag boot + visitor session · Sonnet ·
**S14.2** chat UI (bubbles, typing, markdown, quick replies) · **S14.3** early lead form · **S14.4** schedule CTA ·
**S14.5** TTS greeting + accessibility · **S14.6** rate-limit/error UX.
- **Test:** load a local HTML host page embedding the widget; chat end-to-end against the gateway.

### Infra track (interleaved)

**I.1** Nginx conf (SSL, routing, security headers, correlation IDs) — after P2.
**I.2** Multi-stage Dockerfiles (non-root, healthchecks) for api/worker/beat/widget/admin-web — as each lands.
**I.3** `docker-compose.prod.yml` + PgBouncer tuning — before first deploy.
**I.4** CI pipeline (`lint → typecheck → unit → integration → build → smoke`, coverage thresholds) — after P1.

---

## 5. Porting notes from `first_phase_chatbot/` (reference only)

**Carry forward (flows/data model):** the turn pipeline shape (validate key → upsert session → store msg →
classify → retrieve → score → decide → store → return); the 3-way decision on per-tenant thresholds; one-shot
client onboarding; public client-key + Origin allowlist; sentence-aware chunking; KB status/version lifecycle;
the human-approved learning loop (**deferred** — see below).

**Must replace/add (phase-1 gaps):** real LLM generation + provider abstraction + streaming; real embeddings +
pgvector search (phase-1 retrieval was keyword overlap); fixed 4-role RBAC + httpOnly cookies + revocation +
reset + visitor sessions; **turn-count cap + scheduling handoff** (absent in phase 1); full lead pipeline;
notifications (phase-1 "notify_admin" sent nothing); real job queue (phase-1 used an in-process poller); remove
hardcoded secrets (the phase-1 `local-pepper`, the placeholder client key, admin password returned in API response).

**Deferred to a later phase (your decision):** the human-approved **learning loop** — UnresolvedQuestion →
AiSuggestion → admin approve/edit → KnowledgeBase → reindex, with TrainingJob + rollback. Slot it after P12 as
**Phase 15** when we take it on.

---

## 6. Immediate next action

Start **S0.1**. Opus writes `dev_plan/sprints/S0.1.md`, dispatches a Haiku subagent to author the compose +
env + Postgres init, verifies containers come up healthy with the `vector` extension, then hands you the
`docker compose up` + verification commands to confirm before S0.2.
