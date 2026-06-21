"""FastAPI application factory.

Boot via ``uvicorn api.app:create_app --factory``.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from common.db import Database
from common.errors import AppException, InternalServerError, RateLimitError
from common.health import check_database, check_redis, liveness, metrics_payload, readiness
from common.logging import get_logger, log_context
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from api.config import get_api_settings

_log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect DB and optional Redis on startup; close on shutdown."""
    settings = get_api_settings()

    db = await Database.connect(settings.database_url, statement_cache_size=0)
    app.state.db = db

    redis_client: Any = None
    if settings.redis_url:
        from redis.asyncio import from_url

        redis_client = from_url(settings.redis_url)
        app.state.redis = redis_client

    _log.info("api started", extra={"event": "startup"})
    try:
        yield
    finally:
        await db.close()
        if redis_client is not None:
            await redis_client.aclose()
        _log.info("api stopped", extra={"event": "shutdown"})


def _error_response(exc: AppException, correlation_id: str) -> JSONResponse:
    """Build a JSON error envelope from an AppException."""
    body: dict[str, Any] = {
        "error_code": exc.code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimitError) and exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(status_code=exc.http_status, content=body, headers=headers)


def create_app() -> FastAPI:
    """Application factory -- called by uvicorn ``--factory``."""
    # Fail-fast: settings validated here; missing/invalid env -> crash before serving.
    settings = get_api_settings()

    # Configure structured JSON logging.
    root = get_logger("api")
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    app = FastAPI(title="Chatbot API", version="0.1.0", lifespan=_lifespan)

    # -- Correlation-ID middleware (also catches unhandled exceptions) ----------
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next: Any) -> Response:
        cid = request.headers.get("x-correlation-id") or uuid4().hex
        with log_context(correlation_id=cid):
            try:
                response: Response = await call_next(request)
            except Exception:
                _log.exception("unhandled exception", extra={"event": "unhandled_error"})
                safe = InternalServerError()
                return JSONResponse(
                    status_code=safe.http_status,
                    content={
                        "error_code": safe.code,
                        "message": safe.message,
                        "correlation_id": cid,
                    },
                )
            response.headers["X-Correlation-Id"] = cid
            return response

    # -- Exception handler for AppException ------------------------------------
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        from common.logging import _correlation_id  # noqa: PLC2701

        cid = _correlation_id.get() or ""
        _log.warning(
            exc.message,
            extra={"status_code": exc.http_status, "event": "app_error"},
        )
        return _error_response(exc, cid)

    # -- Routers ---------------------------------------------------------------
    from api.auth.routes import router as auth_router
    from api.rbac.routes import router as rbac_router
    from api.tenants.routes import router as tenants_router

    app.include_router(auth_router)
    app.include_router(rbac_router)
    app.include_router(tenants_router)

    # -- Routes ----------------------------------------------------------------
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return liveness()

    @app.get("/readyz")
    async def readyz(request: Request) -> Response:
        checks: dict[str, Any] = {
            "database": lambda: check_database(request.app.state.db),
        }
        if hasattr(request.app.state, "redis"):
            checks["redis"] = lambda: check_redis(request.app.state.redis)
        ready, detail = await readiness(checks)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "checks": detail},
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        body, content_type = metrics_payload()
        return Response(content=body, media_type=content_type)

    return app
