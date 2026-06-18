---
name: document-ingestion-service
description: Use when building or modifying the document ingestion pipeline for the chatbot — uploading client FAQs/docs to object storage, parsing/OCR, chunking, generating embeddings (via the provider-agnostic llm-provider), and UPSERTing chunks into pgvector. This is a carved-out Celery worker. Use this for anything about ingesting, parsing, chunking, or embedding client knowledge.
---

# Document Ingestion Service (worker)

> Carved-out, queue-driven pipeline that turns uploaded client content into tenant-isolated, searchable
> vectors. Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- Accept uploaded files (triggered by `admin-api`) from object storage.
- **Parse/OCR** → normalize → **chunk** → **embed** (via `llm-provider` embeddings) → **UPSERT** into pgvector.
- Track run logs, handle partial failures, stay idempotent.

## Boundaries
- **In scope:** the ETL pipeline (parse/OCR/chunk/embed/persist), run logging, idempotency.
- **Out of scope:** retrieval/search (`rag-retrieval`), the model abstraction itself (`llm-provider`), upload
  UI/trigger (`admin-api`/`admin-web`).
- **Upstream:** admin-api enqueues jobs. **Downstream:** llm-provider (embeddings), pgvector via repository.

## Pipeline stages (knowledge_base/06 pattern)
```
object storage file → parser/OCR → transform/normalize (tenant context)
  → chunk (size/overlap per config) → embed (llm-provider, tenant's embedding model)
  → UPSERT into knowledge_chunks (ON CONFLICT) → write run log
                         (Celery worker, async, retryable)
```

## Data model
- `knowledge_docs(tenant_id, doc_id PK, source, filename, status, content_hash, created_at)`.
- `knowledge_chunks(tenant_id, doc_id, chunk_id PK, content, embedding vector(N), metadata jsonb)`.
- `ingestion_runs(tenant_id, run_id PK, doc_id, rows_in, chunks_out, errors jsonb, status, duration)`.

## Patterns & standards
- **Idempotency via UPSERT** keyed on natural/content keys (`ON CONFLICT (tenant_id, chunk_id) DO UPDATE`);
  re-running a doc is a no-op if unchanged (content hash). Tasks retry with backoff/jitter; dead-letter on
  permanent failure.
- Validate early, fail loud: log invalid rows, don't silently drop; report partial failures in the run log.
- Embedding model + dimension must match the pgvector column; a model change requires re-embedding (full
  re-run) and cache invalidation in `rag-retrieval`.
- Parser/OCR behind a small abstraction so engines can be swapped.

## Security & multi-tenancy notes
- Every chunk/doc carries `tenant_id`; ingestion enriches with tenant context at the transform stage. Files
  are tenant-scoped in object storage. Provider keys used for embeddings are encrypted.

## Observability
- Metrics: rows ingested/run, chunks produced, duration, error rate, queue depth, embedding cost. Run logs
  with correlation_id; alert on backlog.

## Testing requirements
- Idempotency (re-ingest = no-op via UPSERT/hash); chunking correctness; embedding dimension consistency;
  partial-failure logging; tenant tagging; retry/dead-letter.

## Reusable insights (knowledge_base / solution_flow)
- UPSERT is the key to idempotent loading; extraction/transform must be idempotent. (`06`)
- Design every background task as if it will be retried 3 times. (`02`)
- Ingestion: parser/OCR → chunking & embeddings → vector DB. (solution_flow)
