---
name: admin-web
description: Use when building or modifying the admin console web app for the chatbot platform — the Next.js App Router + React Server Components + shadcn/ui dashboard for platform admins and client admins/agents. Covers server-first data fetching, server actions, RBAC-aware routing/middleware, client onboarding, knowledge upload UI, lead review, conversation analytics dashboards, and tenant settings. Use this for anything about the admin UI.
---

# Admin Web Console (`apps/admin-web`)

> Server-first Next.js console backing the control plane (`admin-api`). Obey `CLAUDE.md`.

## Purpose & responsibilities
- Dashboard for **PLATFORM_ADMIN** (all tenants) and **CLIENT_ADMIN / CLIENT_AGENT** (own tenant).
- Screens: client/tenant onboarding & settings, user management, **knowledge/question upload**, **lead review
  & export**, **conversation analytics** (fallback rate, schedule conversion, intent), scheduling visibility,
  config (greeting/voice copy, business hours, escalation policy, tone, confidence threshold, provider/model,
  domain allowlist, client keys).

## Boundaries
- **In scope:** the admin UI, its server components/actions, RBAC-aware routing, talking to `admin-api`/
  `auth`.
- **Out of scope:** business logic/persistence (backend), the visitor widget (`chat-widget`).
- **Upstream:** admin users. **Downstream:** `admin-api`, `auth-session-service` (via server-side only).

## Tech & patterns (knowledge_base/04, 05, ADR-001/007)
- **Next.js App Router + React Server Components** as default; client components only for interactivity.
  **shadcn/ui** primitives + Tailwind; design tokens/typography per `05_UI_DESIGN_SYSTEM`.
- **Server-first data fetching** in server components; **server actions** for mutations (CSRF-safe, no
  separate API routes for forms). Token stays server-side (httpOnly cookie) — never exposed to client JS.
- **No client state library**: server state via props, form state via controlled components, session via
  cookies (decoded server-side), URL state via routing/search params.
- **Middleware** for auth + RBAC route protection before render; redirect unauthenticated; hide features by
  role (UI defense-in-depth — the API is the real boundary).
- TS strict, Zod for server-action inputs + API payloads. Suspense for loading, error boundaries for failures.

## Performance (frontend_optimization_guide)
- Lazy-load heavy components (charts, large tables); virtualize long lists (leads/conversations); skeleton
  loading for perceived speed; code-split by route; cache-aware data fetching. Charts: prefer Canvas for large
  series, cap data per view.

## Security & multi-tenancy notes
- RBAC enforced server-side; CLIENT_ADMIN/AGENT scoped to own tenant by the backend (UI must not assume it can
  request another tenant). Security headers + CSP in `next.config`. No secrets in client bundles.

## Observability
- Web vitals (LCP/INP/CLS) as CI gate (Lighthouse); Sentry for client errors; surface backend correlation IDs
  in error states for support.

## Testing requirements
- RBAC-aware rendering/routing per role; server-action validation; upload → ingestion trigger; lead review +
  export scoping; analytics rendering; a11y; tenant-scoping assumptions (no cross-tenant requests succeed).

## Reusable insights (knowledge_base)
- Server components by default; push boundaries to the leaves; server actions for mutations. (`04`, ADR-001)
- shadcn/ui for accessible, owned primitives. (`05`, ADR-007) · Measure before optimizing. (frontend guide)

## As-built & doctrine (audit 2026-07-11)
- **Status: NOT BUILT** — Phase 13 (S13.1–S13.6); `apps/` does not exist yet. Blocked on P12 admin-api surface.
- **Think here when it starts:** server-first (RSC + server actions) means the browser never holds tenant data it didn't render — keep client components thin and RBAC-aware routing in middleware, mirroring the API's role model exactly (the API remains the enforcement point; the UI only *hides*). The D9 per-tenant observability dashboard lands here — design list/detail screens around the trace/analytics endpoints S11.2 defines, don't invent parallel aggregates.
