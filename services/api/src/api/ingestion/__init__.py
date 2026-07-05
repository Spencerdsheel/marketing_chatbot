"""Document ingestion module — upload, parse, run-log.

This module implements the S5.2 parse slice of the document-ingestion-service
pipeline. It provides:
- ``StorageProvider`` Protocol + ``LocalStorageProvider`` (storage.py).
- ``parse()`` dispatcher for txt/docx (parsers.py).
- Tenant-scoped repository for knowledge_docs + ingestion_runs (repository.py).
- ``ingest_document`` Celery task (tasks.py).
- Upload + read endpoints (routes.py).

Chunk/embed/pgvector UPSERT lands in S5.3.
"""
