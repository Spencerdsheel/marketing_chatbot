"""Unit tests for the API application shell.

Uses httpx.AsyncClient with ASGITransport -- no live DB or Redis needed.
Test doubles are injected via app.state after create_app().
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from common.errors import NotFoundError
from httpx import ASGITransport, AsyncClient

# -- Test doubles --------------------------------------------------------------


class _StubDatabase:
    """Database double whose fetchval can succeed or raise."""

    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    async def fetchval(self, query: str, *args: object) -> object:
        if not self._healthy:
            raise RuntimeError("db down")
        return 1

    async def close(self) -> None:
        pass


class _StubRedis:
    """Stub redis.asyncio client."""

    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    async def ping(self) -> bool:
        if not self._healthy:
            raise ConnectionError("redis down")
        return True

    async def aclose(self) -> None:
        pass


# -- Helpers -------------------------------------------------------------------

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
}


def _build_app(
    *,
    db_healthy: bool = True,
    redis_healthy: bool = True,
    include_redis: bool = True,
    extra_routes: bool = False,
) -> Any:
    """Create app with test doubles injected, bypassing the real lifespan."""
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from common.settings import get_settings

        from api.config import get_api_settings

        get_settings.cache_clear()
        get_api_settings.cache_clear()
        from api.app import create_app

        app = create_app()
        get_settings.cache_clear()
        get_api_settings.cache_clear()

    # Replace lifespan-provided state with test doubles
    app.state.db = _StubDatabase(healthy=db_healthy)
    if include_redis:
        app.state.redis = _StubRedis(healthy=redis_healthy)

    if extra_routes:

        @app.get("/test-not-found")
        async def _raise_not_found() -> None:
            raise NotFoundError("thing not here")

        @app.get("/test-unhandled")
        async def _raise_unhandled() -> None:
            raise RuntimeError("kaboom internal")

    return app


# -- /healthz ------------------------------------------------------------------


async def test_healthz_returns_200() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# -- /readyz -------------------------------------------------------------------


async def test_readyz_ready_200() -> None:
    app = _build_app(db_healthy=True, redis_healthy=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


async def test_readyz_db_down_503() -> None:
    app = _build_app(db_healthy=False, redis_healthy=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["checks"]["database"] == "fail"


async def test_readyz_redis_down_503() -> None:
    app = _build_app(db_healthy=True, redis_healthy=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["checks"]["redis"] == "fail"


async def test_readyz_no_redis_configured() -> None:
    app = _build_app(db_healthy=True, include_redis=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert "redis" not in body["checks"]


# -- /metrics ------------------------------------------------------------------


async def test_metrics_returns_200_with_prometheus_content_type() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


# -- Correlation ID ------------------------------------------------------------


async def test_correlation_id_echoed() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz", headers={"X-Correlation-Id": "test-123"})
    assert resp.headers["x-correlation-id"] == "test-123"


async def test_correlation_id_generated_when_absent() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz")
    cid = resp.headers.get("x-correlation-id")
    assert cid is not None
    assert len(cid) == 32  # uuid4().hex is 32 hex chars


# -- Error envelope ------------------------------------------------------------


async def test_app_exception_returns_envelope() -> None:
    app = _build_app(extra_routes=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/test-not-found")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert "message" in body
    assert "correlation_id" in body


async def test_unhandled_exception_returns_500_without_leak() -> None:
    app = _build_app(extra_routes=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/test-unhandled")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "kaboom" not in body["message"]
    assert "correlation_id" in body
