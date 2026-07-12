"""Unit tests for the API application shell.

Uses httpx.AsyncClient with ASGITransport -- no live DB or Redis needed.
Test doubles are injected via app.state after create_app().
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from common.cache import InMemoryCache
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
    "SENTRY_DSN": "",
    "ENVIRONMENT": "test",
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
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None

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


# -- Router registration (S10.1) -------------------------------------------------


async def test_chat_router_registered() -> None:
    """POST /public/chat/message route exists (chat_router is registered)."""
    app = _build_app()
    route_paths: set[str] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        if path is not None:
            route_paths.add(path)
        original_router = getattr(r, "original_router", None)
        if original_router is not None:
            for sub in original_router.routes:
                sub_path = getattr(sub, "path", None)
                if sub_path is not None:
                    route_paths.add(sub_path)
    assert "/public/chat/message" in route_paths


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


async def test_unhandled_exception_records_500_metric_and_captures_sentry() -> None:
    """An endpoint that raises → 500 metric recorded AND capture_exception called."""
    from prometheus_client import REGISTRY, generate_latest

    app = _build_app(extra_routes=True)

    # Monkeypatch capture_exception to track calls. capture_exception is
    # SYNCHRONOUS (called un-awaited in the middleware), so the double must be
    # sync too -- an async double would return a never-awaited coroutine and
    # the append would never run.
    captured: list[Exception] = []

    def _fake_capture(exc: Exception) -> None:
        captured.append(exc)

    with patch("api.app.capture_exception", side_effect=_fake_capture):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/test-unhandled")

    assert resp.status_code == 500
    assert len(captured) == 1
    assert isinstance(captured[0], RuntimeError)

    # Verify the 500 metric was recorded
    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'status="500"' in output


# -- _validate_runtime_config --------------------------------------------------


def _make_settings(**overrides: object) -> Any:
    """Return a minimal ApiSettings-like stub for _validate_runtime_config tests."""
    from unittest.mock import MagicMock

    stub = MagicMock()
    stub.storage_backend = overrides.get("storage_backend", "local")
    stub.storage_local_root = overrides.get("storage_local_root", None)
    return stub


def test_validate_runtime_config_raises_when_local_and_root_unset() -> None:
    """local backend + no STORAGE_LOCAL_ROOT → RuntimeError naming the var."""
    from api.app import _validate_runtime_config

    stub = _make_settings(storage_backend="local", storage_local_root=None)
    with pytest.raises(RuntimeError, match="STORAGE_LOCAL_ROOT"):
        _validate_runtime_config(stub)


def test_validate_runtime_config_passes_when_local_and_root_set() -> None:
    """local backend + root provided → no exception."""
    from api.app import _validate_runtime_config

    stub = _make_settings(storage_backend="local", storage_local_root="/some/path")
    _validate_runtime_config(stub)  # must not raise


def test_validate_runtime_config_passes_when_backend_not_local() -> None:
    """Non-local backend without root → no exception (root is not required)."""
    from api.app import _validate_runtime_config

    stub = _make_settings(storage_backend="s3", storage_local_root=None)
    _validate_runtime_config(stub)  # must not raise


# -- _lifespan: pgvector codec wiring (S6.1 decision 1) -------------------------


async def test_lifespan_database_connect_called_with_register_vector_init() -> None:
    """``_lifespan`` must connect the app DB with ``init=register_vector_init``.

    Without this, ``app.state.db`` only has the jsonb codec; binding a query
    embedding (``list[float]``) as ``$1`` for the RAG search endpoint fails at
    runtime against a live DB (the S5.2/S5.3 codec lesson, now at the HTTP
    layer -- S6.1 decision 1). Stub tests can't catch a missing codec directly,
    so this test instead asserts the wiring: ``Database.connect`` is invoked
    with the correct ``init`` callback.
    """
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import _lifespan, create_app

        app = create_app()
        get_settings.cache_clear()
        get_api_settings.cache_clear()

    connect_kwargs: list[dict[str, Any]] = []

    class _StubDb:
        async def close(self) -> None:
            pass

    async def _stub_connect(dsn: str, **kwargs: Any) -> Any:
        connect_kwargs.append(kwargs)
        return _StubDb()

    with patch("api.app.Database.connect", side_effect=_stub_connect):
        async with _lifespan(app):
            pass

    assert connect_kwargs, "Database.connect must have been called"

    from common.pgvector import register_vector_init

    assert connect_kwargs[0].get("init") is register_vector_init, (
        "app.state.db must be connected with init=register_vector_init "
        "(S6.1 decision 1 -- the app-db codec wiring)"
    )
