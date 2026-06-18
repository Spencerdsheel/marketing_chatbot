---
name: conversation-orchestrator
description: Use when building or modifying the chatbot's brain — the conversation orchestrator that manages turns, classifies intent, builds prompts with tenant context, scores answer confidence, enforces guardrails, gates on consent, and applies the fallback-to-scheduling policy when confidence is low or the conversation exceeds ~6-7 turns. Use this for dialog flow, RAG+LLM coordination, or escalation logic.
---

# Conversation Orchestrator (the brain)

> Coordinates RAG, LLM, conversation store, lead capture, and scheduling into one dialog. Owns the *policy*,
> not the implementations. Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Manage the turn loop for a visitor conversation within a tenant.
- Classify intent (sales / support / schedule / lead / off-topic) via `llm-provider`.
- Retrieve client-specific context via `rag-retrieval`; build a prompt with tenant tone rules + fallback
  policy; generate via `llm-provider`; validate the response (guardrails).
- Apply the **fallback policy** → escalate to `scheduling-service`.
- Persist turns via `conversation-store`; emit analytics events.
- Gate contact capture/reminders on **explicit consent**.

## Boundaries
- **In scope:** orchestration, intent routing, confidence scoring, fallback policy, guardrails, consent gate.
- **Out of scope:** raw vector search (`rag-retrieval`), model calls (`llm-provider`), persistence
  (`conversation-store`), booking (`scheduling-service`), lead records (`lead-capture-crm`).
- **Upstream:** gateway (VISITOR claims). **Downstream:** rag, llm, store, leads, scheduling, analytics.

## Fallback policy (core rule — from solution_flow)
Escalate from answering to **offering scheduling** when ANY holds:
- retrieval/answer **confidence < tenant threshold**, OR
- conversation exceeds **~6–7 user turns**, OR
- intent is `schedule`/high-value, OR
- the user asks for pricing/legal/anything outside approved content.
**Never hallucinate** to avoid escalating (no silent fallback — `CLAUDE.md`). On escalation, hand off to
`scheduling-service` (and ensure a lead exists via `lead-capture-crm`).

## Turn loop (sketch)
```
receive message (VISITOR claims)
  → load recent history (conversation-store, windowed)
  → classify intent (llm-provider)
  → retrieve context (rag-retrieval, tenant-scoped) → confidence
  → if fallback-policy triggers → offer scheduling (+ ensure lead, consent)
  → else build prompt (tenant tone + guardrails) → generate (llm-provider) → validate
  → persist turn + emit analytics → return reply (+ quick replies / CTA)
```

## API contract (representative)
- `POST /api/conversations/{id}/messages` → `{ reply, quick_replies?, action? (schedule|lead_form), confidence }`.
- `POST /api/conversations` → start conversation (tenant from claims).

## Patterns & standards
- Per-tenant config: tone rules, confidence threshold, max turns, escalation policy, greeting — read from
  tenant settings (`admin-api`).
- Guardrails: response validator blocks unsafe/irrelevant/out-of-scope answers before returning.
- Streaming responses supported via `llm-provider` streaming.
- Idempotency: a retried message submit must not double-persist or double-escalate.

## Security & multi-tenancy notes
- All retrieval, persistence, and config are scoped to `claims.tenant_id`. Cross-tenant context is impossible
  because every downstream call carries the visitor's claims.
- Capture explicit consent before storing contact details or creating reminders (GDPR).

## Observability
- Metrics: turns/conversation, intent distribution, fallback rate, schedule-conversion, confidence
  histogram, guardrail blocks, LLM latency. Emits conversation analytics events to `analytics-observability`.

## Testing requirements
- Fallback triggers (low confidence, turn cap, out-of-scope) → scheduling; guardrail blocks; consent gating;
  no-hallucination on retrieval miss; tenant isolation of context; idempotent message handling.

## Reusable insights (knowledge_base / solution_flow)
- No silent fallbacks: explicit escalation beats a confident wrong answer. (ADR-010, `CLAUDE.md`)
- Lead capture early; escalate to scheduling on low confidence or 6–7 turns. (solution_flow)
