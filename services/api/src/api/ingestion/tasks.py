"""Celery task: ingestion.ingest_document.

This task implements S5.2 decision 6:
  1. Mark run ``running``.
  2. Load raw bytes from storage.
  3. Parse to text.
  4. Store ``parsed.txt`` in storage.
  5. On success  → run ``succeeded`` (chars_out, duration_ms) + doc ``parsed``.
  6. On parse/validation error (deterministic) → run ``failed`` (errors recorded)
     + doc ``failed``. Do NOT raise; do NOT retry — the file will never parse.
  7. On transient infra error (storage/DB) → let it propagate so Celery retries
     with backoff (S5.1 ``acks_late``). Never swallow.

Worker tenant context (decision 1):
  The upload route passes ``tenant_id`` — which came from the admin JWT — as an
  explicit task kwarg. The task builds a tenant-scoped ``AuthClaims`` with
  ``subject="system:ingestion"`` and ``role=Role.CLIENT_ADMIN`` so that every
  repository call is still filtered at the repository layer.

correlation_id (decision 2):
  MUST be declared in the signature. Celery runs ``check_arguments`` inside
  ``apply_async`` at enqueue time, before the base ``_CorrelationTask.__call__``
  can consume it. Omitting it makes ``.delay(correlation_id=...)`` raise
  ``TypeError`` at enqueue — the same bug caught in S5.1.
"""
from __future__ import annotations

import asyncio
import time

from common.auth import AuthClaims, Role
from common.db import Database
from common.errors import ValidationError
from common.logging import get_logger

from api.ingestion import repository as repo
from api.ingestion.parsers import parse
from api.ingestion.storage import StorageProvider, get_storage
from api.tasks.celery_app import _CorrelationTask, celery_app

_log = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ingestion.ingest_document",
    base=_CorrelationTask,
)
def ingest_document(
    self: _CorrelationTask,
    *,
    doc_id: str,
    tenant_id: str,
    run_id: str,
    correlation_id: str | None = None,  # noqa: ARG001 — consumed by _CorrelationTask.__call__
) -> dict[str, object]:
    """Parse a document and record the result in the run log.

    Parameters
    ----------
    doc_id:
        The ``knowledge_docs.doc_id`` to parse.
    tenant_id:
        Trusted tenant identifier. Originates from the admin JWT at enqueue
        time — never from visitor input (S5.2 decision 1).
    run_id:
        The ``ingestion_runs.run_id`` to update throughout execution.
    correlation_id:
        Must be declared here (see module docstring / S5.2 decision 2).
        The value is consumed by ``_CorrelationTask.__call__`` before this
        body runs; it will always be ``None`` here.

    Returns
    -------
    dict
        ``{"doc_id": ..., "run_id": ..., "status": "succeeded"|"failed"}``.
    """
    # Build a tenant-scoped service identity — repo calls are still filtered
    # by tenant_id even though we're outside an HTTP request (decision 1).
    claims = AuthClaims(
        subject="system:ingestion",
        role=Role.CLIENT_ADMIN,
        tenant_id=tenant_id,
    )

    storage = get_storage()

    # We need a running asyncio event loop to call the async repository. In
    # the Celery worker (threads, not coroutines) we create a temporary loop.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _run(self, claims, doc_id, run_id, storage),
        )
    finally:
        loop.close()


async def _run(
    task: _CorrelationTask,
    claims: AuthClaims,
    doc_id: str,
    run_id: str,
    storage: StorageProvider,
) -> dict[str, object]:
    """Async inner body of ``ingest_document``."""
    from api.config import get_api_settings  # noqa: PLC0415

    settings = get_api_settings()
    db = await Database.connect(settings.database_url, statement_cache_size=0)
    try:
        return await _execute(task, db, claims, doc_id, run_id, storage)
    finally:
        await db.close()


async def _execute(
    task: _CorrelationTask,
    db: Database,
    claims: AuthClaims,
    doc_id: str,
    run_id: str,
    storage: StorageProvider,
) -> dict[str, object]:
    """Core parse-and-record logic, given an open DB connection."""

    _log.info(
        "ingest_document started",
        extra={
            "task": "ingestion.ingest_document",
            "event": "task_started",
            "doc_id": doc_id,
            "run_id": run_id,
        },
    )

    # Step 1 — mark run running.
    await repo.update_run(db, claims, run_id, status="running")

    # Step 2 — fetch doc to learn storage_key + content_type.
    doc = await repo.get_doc(db, claims, doc_id)
    if doc is None:
        # This would be a programming error (upload route always creates the doc
        # before enqueuing). Treat as transient so Celery can retry.
        raise RuntimeError(f"Doc {doc_id!r} not found for tenant {claims.tenant_id!r}.")

    t0 = time.monotonic()

    try:
        # Step 3 — load bytes from storage.
        raw_bytes: bytes = storage.get(doc.storage_key)

        # Step 4 — parse.
        parsed_text = parse(doc.content_type, raw_bytes)

        # Step 5 — store parsed.txt next to the raw file.
        parsed_key = f"{claims.tenant_id}/{doc_id}/parsed.txt"
        storage.put(parsed_key, parsed_text.encode("utf-8"))

    except ValidationError as exc:
        # Deterministic parse/validation error — record + fail, do NOT retry.
        duration_ms = int((time.monotonic() - t0) * 1000)
        error_entry = {"code": exc.code, "message": exc.message}
        await repo.update_run(
            db,
            claims,
            run_id,
            status="failed",
            errors=error_entry,
            duration_ms=duration_ms,
        )
        await repo.update_doc_status(db, claims, doc_id, "failed")

        _log.warning(
            "ingest_document parse error",
            extra={
                "task": "ingestion.ingest_document",
                "event": "task_parse_error",
                "doc_id": doc_id,
                "run_id": run_id,
                "error_code": exc.code,
            },
        )
        return {"doc_id": doc_id, "run_id": run_id, "status": "failed"}

    # Step 6 — success path.
    duration_ms = int((time.monotonic() - t0) * 1000)
    chars_out = len(parsed_text)

    await repo.update_run(
        db,
        claims,
        run_id,
        status="succeeded",
        chars_out=chars_out,
        duration_ms=duration_ms,
    )
    await repo.update_doc_status(db, claims, doc_id, "parsed")

    _log.info(
        "ingest_document succeeded",
        extra={
            "task": "ingestion.ingest_document",
            "event": "task_completed",
            "doc_id": doc_id,
            "run_id": run_id,
            "chars_out": chars_out,
            "duration_ms": duration_ms,
        },
    )
    return {"doc_id": doc_id, "run_id": run_id, "status": "succeeded"}
