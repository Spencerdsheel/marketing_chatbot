---
name: llm-provider
description: Use when building or modifying the provider-agnostic LLM abstraction for the chatbot — the LLMProvider Protocol (generate, classify, stream, embed), per-tenant provider+model configuration, and the Anthropic/OpenAI/Azure implementations. Use this for anything about calling an LLM, switching models/providers per tenant, embeddings generation, streaming, retries, or token/cost handling. There is intentionally NO default provider.
---

# LLM Provider (model-agnostic)

> The only place that talks to an LLM vendor. Everything else depends on the Protocol, never a vendor SDK.
> Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Define a **provider-agnostic `LLMProvider` Protocol** and implement it for **Anthropic, OpenAI, Azure
  OpenAI** as first-class backends.
- Resolve the provider + model **per tenant** from config (no hard-wired default).
- Handle generation, intent classification, streaming, and embeddings; manage retries, timeouts, token
  accounting, and secret handling.

## Boundaries
- **In scope:** the abstraction, vendor impls, per-tenant routing, retries/timeouts, cost/token metrics,
  prompt-agnostic execution.
- **Out of scope:** prompt content/policy (`conversation-orchestrator`), retrieval (`rag-retrieval`),
  chunking (`document-ingestion-service`).
- **Upstream:** orchestrator, rag-retrieval (embeddings), document-ingestion (embeddings).

## Contract
```python
class LLMProvider(Protocol):
    async def generate(self, messages, *, model, **opts) -> Completion: ...
    async def stream(self, messages, *, model, **opts) -> AsyncIterator[Chunk]: ...
    async def classify(self, text, labels, *, model) -> Label: ...
    async def embed(self, texts, *, model) -> list[Vector]: ...

def provider_for(claims: AuthClaims, settings) -> LLMProvider:
    """Resolve provider+model from the tenant's config. No global default."""
```

## Per-tenant config
- Tenant settings declare `{ provider, generation_model, classification_model, embedding_model, api_key_ref }`.
- API keys stored **encrypted** (AES-256-GCM via `platform-foundations`); decrypted only at call time.
- Embedding model + dimension must stay consistent with the pgvector column dimension; a model change requires
  re-embedding (coordinate with `document-ingestion-service`).

## Patterns & standards
- Resilient external calls: retry with exponential backoff + jitter, bounded timeouts, circuit-breaker on
  repeated failures. **No silent fallback** to a fake answer — surface an explicit error so the orchestrator
  can escalate.
- Strategy pattern (knowledge_base): swap implementations via config; the contract is the boundary.
- Streaming passthrough for low-latency UX.

## Security & multi-tenancy notes
- Never log prompts/completions containing PII or the API keys. Keys are per-tenant and encrypted.
- A tenant can only use its own configured provider/keys.

## Observability
- Metrics: per-provider/model latency, token usage + estimated cost, error/timeout/retry counts, stream TTFB.
  Tag with tenant_id + correlation_id.

## Testing requirements
- Protocol conformance across all three impls (contract tests); per-tenant resolution; retry/backoff;
  timeout/circuit-breaker; embedding dimension consistency; key decryption path; no-default enforcement.

## Reusable insights (knowledge_base / solution_flow)
- Define the interface at the boundary; swap impls via config. (`01`, ADR-002)
- Every external call needs a retry policy; failures are inevitable. (`06`)
- Model-agnostic abstraction layer for the LLM. (solution_flow)
- When building with Claude, use current model IDs (e.g. Opus 4.8 `claude-opus-4-8`, Haiku 4.5
  `claude-haiku-4-5`); verify via the claude-api reference rather than memory.

## As-built & doctrine (audit 2026-07-11)
- **Status: built** (S3.1–S3.5b). Path: `services/api/src/api/llm/` — `provider.py` (Protocol: generate/classify/stream/embed), `anthropic_provider`, `openai_provider` (any `base_url` — OpenCode Zen/Ollama/real OpenAI), `azure_provider`, `metered_provider` (token/cost capture), `factory.provider_for`, `config_repository` (per-tenant provider+model+key, key encrypted via `SecretBox`).
- **As-built facts:** no default provider — an unconfigured tenant is a deterministic `LLM_NOT_CONFIGURED`, never a fallback. Anthropic gets no `temperature` (rejects it) and has no embeddings API (`embed` raises — no fake vectors). Upstream errors are logged server-side with status/detail (never the key), surfaced as generic `LLMError`.
- **Think here:** every LLM call is tenant money — new call sites must be metered, bounded (`max_tokens`, timeout, bounded retries), and attributable (correlation id). A provider quirk is handled inside that provider's impl, never leaked into callers.
