---
name: rag-retrieval
description: Use when building or modifying retrieval-augmented generation for the chatbot — querying the tenant-isolated client knowledge store, pgvector similarity search, hybrid/keyword ranking, top-k selection, and producing the confidence signal the orchestrator uses for its fallback policy. Use this for anything about searching client FAQs/docs/embeddings or how retrieval confidence is computed.
---

# RAG Retrieval Layer

> Turns a query + tenant into ranked, relevant context chunks plus a confidence signal. Obey `CLAUDE.md` +
> `platform-foundations` (pgvector access + tenant filtering live there).

## Purpose & responsibilities
- Embed the incoming query (via `llm-provider` embeddings) and run **pgvector** similarity search over the
  tenant's knowledge chunks.
- Optionally combine with keyword/metadata filtering (hybrid search) and re-rank.
- Return top-k chunks with sources + a **confidence score** the orchestrator consumes.

## Boundaries
- **In scope:** query embedding orchestration, vector + hybrid search, ranking, confidence, source citing.
- **Out of scope:** ingesting/chunking/embedding documents (`document-ingestion-service`), model calls
  themselves (`llm-provider`), dialog policy (`conversation-orchestrator`).
- **Upstream:** orchestrator. **Downstream:** `llm-provider` (embeddings), pgvector via repository.

## Data model (read side)
- `knowledge_chunks(tenant_id, doc_id, chunk_id PK, content, embedding vector(N), metadata jsonb, ...)`.
  Written by `document-ingestion-service`. **Every query includes the tenant filter.**
- Cosine distance `<=>` with an IVFFlat/HNSW index; per-tenant partitioning or filtering as appropriate.

## API contract (internal)
- `retrieve(claims, query, k, filters?) -> { chunks: [{content, source, score}], confidence }`.

## Confidence signal
- Derive from top-k similarity scores (e.g. top score + margin/coverage). The orchestrator compares it to the
  **per-tenant threshold** to decide answer vs escalate. Tune defaults; expose threshold in tenant config.

## Patterns & standards
- Cache-aside for hot queries (tenant-scoped key, short TTL); invalidate when ingestion completes for a tenant.
- Repository pattern for all vector access (single pgvector implementation — do not add another vector DB).
- No silent fallback: if retrieval finds nothing above floor, return low confidence and let the orchestrator
  escalate — never fabricate sources.

## Security & multi-tenancy notes
- Cross-tenant retrieval must be impossible: the tenant filter is applied in the repository, not optional.
  Add a test that tenant A's query can never return tenant B's chunks.

## Observability
- Metrics: retrieval latency, top-k score distribution, confidence histogram, cache hit rate, empty-result
  rate, per-tenant query volume.

## Testing requirements
- Tenant isolation of results; confidence computation; k/threshold behavior; cache invalidation after
  ingestion; empty-knowledge-base behavior (low confidence, no crash).

## Reusable insights (knowledge_base / solution_flow)
- Cache-aside with tenant-scoped keys + invalidate after ingestion. (`02`, `03`)
- RAG: retrieve client-specific content; if confidence low, escalate rather than hallucinate. (solution_flow)
