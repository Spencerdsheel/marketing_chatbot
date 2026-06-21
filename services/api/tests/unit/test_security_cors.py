"""Unit tests for security headers + dynamic per-tenant CORS.

Covers:
- Security headers on every response (including errors).
- CORS allowed: known Origin → ACAO reflected + Vary: Origin.
- CORS unknown: unknown Origin → no ACAO header.
- Preflight allowed/unknown: OPTIONS → 204 + CORS headers (or none).
- Caching: two requests with same Origin → DB fetchval invoked once.
- No credentials: Access-Control-Allow-Credentials is never set.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

# -- Test doubles --------------------------------------------------------------

_KNOWN_ORIGIN = "http://localhost:3000"
_UNKNOWN_ORIGIN = "http://evil.example"


class _CountingDatabase:
    """Database double that counts fetchval calls for the CORS query."""

    def __init__(self) -> None:
        self.fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        return None

    async def fetchval(self, query: str, *args: object) -> object:
        self.fetchval_calls.append((query, args))
        origin = str(args[0]) if args else ""
        return origin == _KNOWN_ORIGIN

    async def execute(self, query: str, *args: object) -> str:
        return "UPDATE 1"

    async def close(self) -> None:
        pass


class _StubRedis:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def getdel(self, key: str) -> str | None:
        return None

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass

    def pipeline(self, transaction: bool = False) -> _StubPipeline:
        return _StubPipeline()


class _StubPipeline:
    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        pass

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        pass

    def zcard(self, key: str) -> None:
        pass

    def expire(self, key: str, seconds: int) -> None:
        pass

    async def execute(self) -> list[Any]:
        return [0, None, 0, True]

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        return []


# -- Helpers -------------------------------------------------------------------

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _build_app(db: Any = None) -> Any:
    """Create app with test doubles + InMemoryCache."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app
        app = create_app()

    app.state.db = db if db is not None else _CountingDatabase()
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None  # will be lazily created by the rate-limiter glue
    return app


# ==============================================================================
# Security headers
# ==============================================================================


async def test_security_headers_on_normal_response() -> None:
    """GET /healthz → response carries all SECURITY_HEADERS."""
    from api.edge import SECURITY_HEADERS

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz")
    assert resp.status_code == 200
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value, f"missing {header}"


async def test_security_headers_on_error_response() -> None:
    """GET /auth/me with no cookie → 401 still has all SECURITY_HEADERS."""
    from api.edge import SECURITY_HEADERS

    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me")
    assert resp.status_code == 401
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value, f"missing {header} on error response"


# ==============================================================================
# CORS allowed / denied
# ==============================================================================


async def test_cors_allowed_origin() -> None:
    """Known Origin → ACAO reflected + Vary: Origin."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz", headers={"Origin": _KNOWN_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == _KNOWN_ORIGIN
    assert resp.headers.get("vary") == "Origin"


async def test_cors_unknown_origin() -> None:
    """Unknown Origin → no ACAO header."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz", headers={"Origin": _UNKNOWN_ORIGIN})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


# ==============================================================================
# Preflight
# ==============================================================================


async def test_preflight_allowed() -> None:
    """OPTIONS with known Origin → 204 + CORS headers."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.options(
            "/widget/session",
            headers={
                "Origin": _KNOWN_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    assert resp.status_code == 204
    assert resp.headers.get("access-control-allow-origin") == _KNOWN_ORIGIN
    assert "GET, POST, OPTIONS" in resp.headers.get("access-control-allow-methods", "")
    assert "Authorization, Content-Type" in resp.headers.get("access-control-allow-headers", "")
    assert "access-control-max-age" in resp.headers


async def test_preflight_unknown_origin() -> None:
    """OPTIONS with unknown Origin → 204 with no ACAO."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.options(
            "/widget/session",
            headers={
                "Origin": _UNKNOWN_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    assert resp.status_code == 204
    assert "access-control-allow-origin" not in resp.headers


# ==============================================================================
# Caching
# ==============================================================================


async def test_cors_caching_single_db_call() -> None:
    """Two requests with the same known Origin → DB fetchval invoked once."""
    db = _CountingDatabase()
    app = _build_app(db=db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/healthz", headers={"Origin": _KNOWN_ORIGIN})
        await c.get("/healthz", headers={"Origin": _KNOWN_ORIGIN})
    assert len(db.fetchval_calls) == 1


# ==============================================================================
# No credentials
# ==============================================================================


async def test_no_credentials_header() -> None:
    """Access-Control-Allow-Credentials is never set."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz", headers={"Origin": _KNOWN_ORIGIN})
    assert "access-control-allow-credentials" not in resp.headers

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.options(
            "/widget/session",
            headers={
                "Origin": _KNOWN_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
    assert "access-control-allow-credentials" not in resp.headers
