---
name: chat-widget
description: Use when building or modifying the embeddable chat widget for the platform — the self-contained React + TypeScript + Shadow DOM bundle dropped onto client sites via one script tag, the chat UI (bubbles, quick replies, typing indicators, markdown), the early lead form, the schedule CTA, anonymous visitor session handling, the voice/prompt (browser TTS) greeting, accessibility, and rate-limit/error handling. Use this for anything about the visitor-facing widget.
---

# Chat Widget (`apps/widget`)

> Self-contained embeddable widget for any client website. Obey `CLAUDE.md`. Talks only to the gateway.

## Purpose & responsibilities
- A **single `<script>` drop-in** that mounts an isolated chat widget on any site.
- Chat UX: widget shell, chat bubbles, quick replies, typing indicators, file-safe markdown, schedule CTA.
- **Lead form early** in the flow (name/email/phone + consent) before the main conversation.
- **Anonymous visitor session**: obtain a signed visitor token from the gateway (`POST /widget/session`),
  carry it on all calls; never send `tenant_id`.
- **Voice/prompt layer**: optional browser text-to-speech greeting on first open.
- Accessibility + graceful rate-limit/error handling.

## Boundaries
- **In scope:** the widget bundle, its UI/state, session bootstrap, lead form, schedule CTA UI, TTS greeting,
  a11y, error/rate-limit UX.
- **Out of scope:** any business logic or persistence (all server-side), admin UI (`admin-web`).
- **Upstream:** the host website. **Downstream:** `api-gateway-bff` only.

## Tech & isolation
- **React + TypeScript + Shadow DOM** for full CSS isolation from the host page; lightweight state (no heavy
  global store); built as a single CDN-served bundle. TS strict; Zod for validating server payloads.
- Embed: `<script src=".../widget.js" data-client-key="pk_..."></script>` → boots, mints visitor session,
  renders.

## Bootstrap flow
```
script loads with public client key
  → POST /widget/session (key + Origin) → signed visitor token
  → render shell; optional TTS greeting
  → (early) lead form + consent → POST /api/leads
  → chat: POST /api/conversations/{id}/messages → render reply / quick replies / schedule CTA
  → on schedule CTA → booking flow (scheduling endpoints via gateway)
```

## Patterns & standards (knowledge_base/04, frontend_optimization_guide)
- Minimal client JS; lazy-load heavy bits; respect `prefers-reduced-motion`; flat, fast interactions
  (short transitions).
- Accessibility: keyboard navigation, ARIA labels, live-region announcements for new messages,
  focus management, WCAG AA contrast. **A11y is a requirement, not a feature.**
- Markdown rendering is sanitized (no raw HTML injection). Handle 429/5xx with friendly retry UX —
  **no silent failure** that fakes a reply.
- Reconnect/retry with backoff for transient errors; show connection status.

## Security & multi-tenancy notes
- The client key is **public** (lives in page source) — tenant safety comes from the gateway's Origin
  allowlist + rate limiting, not from hiding the key. The widget never holds secrets or `tenant_id`.
- Consent captured in the lead form before any contact storage.

## Observability
- Lightweight client telemetry (open rate, lead-form completion, message count, errors) sent through the
  gateway; no PII in client logs.

## Testing requirements
- Shadow DOM isolation on a hostile host page; session bootstrap + Origin behavior; lead-form + consent;
  schedule CTA; a11y (keyboard + screen reader); rate-limit/error UX; markdown sanitization.

## Reusable insights (knowledge_base / solution_flow)
- Server-first: keep logic/secrets server-side, widget is presentation + interaction. (`01`, `04`)
- Self-contained bundle / Web Component, CSS isolation via Shadow DOM, anonymous visitor ID, a11y,
  TTS greeting. (solution_flow)

## As-built & doctrine (audit 2026-07-11)
- **Status: NOT BUILT** — Phase 14 (S14.1–S14.6); `apps/` does not exist yet. The backend it talks to is live: `POST /widget/session` (admission) and `POST /public/chat/message` (turns; metering arrives in SR-1.2 — build the widget's 429/`Retry-After` and `TURN_BUDGET_EXCEEDED` UX against it from day one).
- **Think here when it starts:** the widget runs on *someone else's* page — Shadow DOM isolation, zero globals, zero third-party leakage, and it must fail invisible (a broken bot never breaks the host site). The client key is public by design; the session token is the only credential and lives in memory, not storage. Accessibility and the TTS greeting are launch features, not polish (S14.5).
