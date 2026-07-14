---
name: conversation-store
description: Use when building or modifying persistence of chatbot conversations and messages — the Conversation and Message data model, history windowing for context, tenant-scoped storage and retrieval, retention/deletion, and the hooks that feed conversation analytics. Use this for anything about saving or loading chat history.
---

# Conversation Store

> The system of record for conversations and messages. Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Persist conversations and their messages, tenant-scoped.
- Provide **windowed history** retrieval for the orchestrator (recent N turns / token budget).
- Support retention/deletion policies (GDPR) and feed analytics.

## Boundaries
- **In scope:** conversation/message CRUD, history windowing, retention/deletion, analytics hooks.
- **Out of scope:** dialog policy (`conversation-orchestrator`), lead records (`lead-capture-crm`),
  analytics aggregation (`analytics-observability`).
- **Upstream:** orchestrator, admin-api (read for review). **Downstream:** repository/Postgres.

## Data model
- `conversations(tenant_id, conversation_id PK, visitor_id, status, channel, started_at, ended_at,
  metadata jsonb)`.
- `messages(tenant_id, conversation_id, message_id PK, role[user|bot|system], content, intent?, confidence?,
  tokens?, created_at)`.
- Composite keys include `tenant_id`; indexed on `(tenant_id, conversation_id, created_at)`.

## API contract (internal + admin read)
- `append_message(claims, conversation_id, msg)`, `get_window(claims, conversation_id, limit|token_budget)`.
- `list_conversations(claims, filters)`, `get_conversation(claims, id)` — used by `admin-api`/`analytics`.

## Patterns & standards
- Parameterized async SQL; UPSERT where natural; never expose internal tenant fields in client responses.
- History windowing caps context size to control LLM cost/latency.
- Retention: configurable per-tenant; deletion cascades messages; support visitor data-deletion requests.

## Security & multi-tenancy notes
- Every read/write filtered by `claims.tenant_id`. `CLIENT_AGENT` may read within tenant; `VISITOR` may only
  read its own conversation.

## Observability
- Metrics: messages/sec, conversation length distribution, storage growth, retention-purge counts.

## Testing requirements
- Tenant isolation of history; windowing correctness; retention/deletion; agent vs visitor read scope;
  idempotent append on retry.

## Reusable insights (knowledge_base)
- UPSERT for idempotent writes; composite keys with tenant_id. (`06`)
- Strip internal tenant-scoped fields from client responses. (`02`)

## As-built & doctrine (audit 2026-07-11)
- **Status: built** (S4.1–S4.4 + 0022). Path: `services/api/src/api/conversation_store/`. Migrations 0007–0009, 0022 (`sources` on messages).
- **As-built facts:** messages use a composite PK with `tenant_id`; `append_message` is idempotent (`ON CONFLICT DO NOTHING` on message_id); roles are `user|bot|system` (`bot` is mapped to `assistant` only at the LLM boundary); working memory = `get_working_memory` → running `summary` (folded via the tenant's LLM when the window overflows, D8) + windowed recent tail; GDPR delete/export shipped in S4.4. VISITORs see only their own conversation.
- **Think here:** this is the system of record for the product's most sensitive data — writes are idempotent-by-key or they don't ship; a durable user turn outranks a pretty error path (store first, fail loud after). Retention/deletion changes are one-way doors: surface them, don't slip them in.
