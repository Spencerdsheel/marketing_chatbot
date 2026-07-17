"""Ingestion endpoints — upload + read.

Both endpoints require ``CLIENT_ADMIN`` (RBAC, CLAUDE.md §3).

POST /admin/ingestion/upload
    Multipart ``file`` field. Validates size and content type, computes
    SHA-256, checks for an existing doc with the same hash (idempotent
    re-upload → return existing doc_id, no second enqueue), stores raw bytes,
    inserts ``knowledge_docs`` + ``ingestion_runs``, enqueues
    ``ingestion.ingest_document``.

GET /admin/ingestion/docs/{doc_id}
    Returns doc + latest run + first 500 chars of ``parsed.txt`` (if
    available). Response NEVER includes ``tenant_id`` or ``storage_key``.
    Returns 404 ``DOC_NOT_FOUND`` if absent / not visible to the caller.
"""
from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from common.auth import AuthClaims, Role
from common.errors import NotFoundError, ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import JSONResponse

from api.audit.repository import record_audit
from api.auth.dependencies import get_platform_admin_actor, require_roles, resolve_tenant_scope
from api.config import get_api_settings
from api.ingestion import repository as repo
from api.ingestion.storage import get_storage
from api.ingestion.tasks import ingest_document

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/ingestion", tags=["ingestion"])
tenant_scoped_router = APIRouter(prefix="/admin/tenants/{tenant_id}/ingestion", tags=["ingestion"])

_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def _upload_document(file: UploadFile, request: Request, claims: AuthClaims) -> Any:
    """Accept a document upload, store it, and enqueue the ingestion task.

    Returns ``{doc_id, run_id, status:"pending"}`` on a fresh upload.
    Returns ``{doc_id, run_id: null, status:"<existing-status>"}`` on an
    idempotent re-upload (same bytes, no new run enqueued).
    Returns 413 JSONResponse when the upload exceeds the configured byte limit.
    """
    from common.logging import _correlation_id  # noqa: PLC2701, PLC0415

    cid = _correlation_id.get() or ""
    settings = get_api_settings()
    db = request.app.state.db

    # -- Validate content type ------------------------------------------------
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported content type: {file.content_type!r}. "
            "Supported: text/plain, "
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.",
            code="UNSUPPORTED_CONTENT_TYPE",
        )

    # -- Read bytes + validate size -------------------------------------------
    data = await file.read()
    if len(data) > settings.ingestion_max_upload_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "error_code": "FILE_TOO_LARGE",
                "message": (
                    f"Upload exceeds the {settings.ingestion_max_upload_bytes}-byte limit."
                ),
                "correlation_id": cid,
            },
        )

    # -- Content hash for idempotency -----------------------------------------
    content_hash = hashlib.sha256(data).hexdigest()

    existing = await repo.find_doc_by_hash(db, claims, content_hash)
    if existing is not None:
        # Idempotent re-upload: same content already stored — return the
        # existing doc_id without re-storing, re-inserting, or re-enqueuing.
        _log.info(
            "document_upload_idempotent",
            extra={
                "event": "document_upload_idempotent",
            },
        )
        return {
            "doc_id": existing.doc_id,
            "run_id": None,
            "status": existing.status,
        }

    # -- Store raw bytes -------------------------------------------------------
    # Key pattern: {tenant_id}/{doc_id}/{filename} (decision 3).
    doc_id = uuid4().hex
    filename = file.filename or "upload"
    storage_key = f"{claims.tenant_id}/{doc_id}/{filename}"
    storage = get_storage()
    storage.put(storage_key, data)

    # -- Persist doc + run records --------------------------------------------
    await repo.create_doc(
        db,
        claims,
        source="upload",
        filename=filename,
        content_type=content_type,
        content_hash=content_hash,
        storage_key=storage_key,
        doc_id=doc_id,
    )
    run = await repo.create_run(db, claims, doc_id=doc_id)

    # -- Enqueue task ----------------------------------------------------------
    ingest_document.delay(
        doc_id=doc_id,
        tenant_id=claims.tenant_id,
        run_id=run.run_id,
        correlation_id=cid,
    )

    await record_audit(
        db,
        claims,
        action="document_uploaded",
        target_type="knowledge_doc",
        target_id=doc_id,
        metadata={"filename": filename, "content_type": content_type},
        actor_context=get_platform_admin_actor(request),
    )

    _log.info(
        "document_uploaded",
        extra={
            "event": "document_uploaded",
        },
    )

    return {"doc_id": doc_id, "run_id": run.run_id, "status": "pending"}


@router.post("/upload", response_model=None)
async def upload_document(
    file: UploadFile,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> Any:
    return await _upload_document(file, request, claims)


@tenant_scoped_router.post("/upload", response_model=None)
async def upload_document_for_tenant(
    file: UploadFile,
    request: Request,
    claims: AuthClaims = Depends(resolve_tenant_scope(Role.CLIENT_ADMIN)),  # noqa: B008
) -> Any:
    """PLATFORM_ADMIN super-user variant of ``POST /admin/ingestion/upload`` (S12.7)."""
    return await _upload_document(file, request, claims)


async def _get_document(doc_id: str, request: Request, claims: AuthClaims) -> dict[str, Any]:
    """Return doc metadata + latest run + parsed preview.

    Response NEVER includes ``tenant_id`` or ``storage_key``.
    Returns 404 ``DOC_NOT_FOUND`` if absent or not visible.
    """
    db = request.app.state.db

    doc = await repo.get_doc(db, claims, doc_id)
    if doc is None:
        raise NotFoundError(
            "Knowledge document not found.",
            code="DOC_NOT_FOUND",
        )

    latest_run = await repo.get_latest_run(db, claims, doc_id)

    # Attempt to read the first 500 chars of parsed.txt from storage.
    parsed_preview: str | None = None
    try:
        storage = get_storage()
        parsed_key = f"{claims.tenant_id}/{doc_id}/parsed.txt"
        if storage.exists(parsed_key):
            raw = storage.get(parsed_key)
            parsed_preview = raw.decode("utf-8", errors="replace")[:500]
    except Exception:
        # Storage read failure is non-fatal for the read endpoint — we return
        # the doc record with parsed_preview=null rather than 500-ing.
        parsed_preview = None

    run_payload: dict[str, Any] | None = None
    if latest_run is not None:
        run_payload = {
            "run_id": latest_run.run_id,
            "status": latest_run.status,
            "chars_out": latest_run.chars_out,
            "errors": latest_run.errors,
            "duration_ms": latest_run.duration_ms,
        }

    return {
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "content_type": doc.content_type,
        "status": doc.status,
        "content_hash": doc.content_hash,
        "latest_run": run_payload,
        "parsed_preview": parsed_preview,
    }


@router.get("/docs/{doc_id}")
async def get_document(
    doc_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, Any]:
    return await _get_document(doc_id, request, claims)


@tenant_scoped_router.get("/docs/{doc_id}")
async def get_document_for_tenant(
    doc_id: str,
    request: Request,
    claims: AuthClaims = Depends(resolve_tenant_scope(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, Any]:
    """PLATFORM_ADMIN super-user variant of ``GET /admin/ingestion/docs/{doc_id}`` (S12.7)."""
    return await _get_document(doc_id, request, claims)
