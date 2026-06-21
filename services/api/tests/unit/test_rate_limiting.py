"""Unit tests for rate limiting on public endpoints.

Covers:
- /widget/session: first ``max`` allowed, ``max+1``-th → 429 RATE_LIMITED + Retry-After.
- /auth/login: ``max+1`` rapid attempts → 429 (independent of credentials).
- /auth/password-reset/request: ``max+1`` → 429.
- Fail-open: with a Redis stub that raises RedisError, requests still succeed
  (degrades to in-memory, not 500).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from common.cache import InMemoryCache
from common.crypto import hash_password
from common.ratelimit import InMemoryRateLimiter, build_rate_limiter
from httpx import ASGITransport, AsyncClient

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"
_CLIENT_KEY = "pk_test-key-123"

_KNOWN_PASSPHRASE = "correct horse battery staple"
_KNOWN_HASH = hash_password(_KNOWN_PASSPHRASE)

_ACTIVE_USER_ROW: dict[str, Any] = {
    "id": "user-active-1",
    "tenant_id": _TENANT_ID,
    "email": "admin@example.com",
    "role": "CLIENT_ADMIN",
    "password_hash": _KNOWN_HASH,
    "name": "Account Owner",
    "active": True,
    "last_login_at": None,
}

_TENANT_ROW: dict[str, Any] = {
    "id": _TENANT_ID,
    "slug": "tenant-a",
    "enabled": True,
    "allowed_origins": ["http://localhost:3000"],
}

# -- Test doubles --------------------------------------------------------------


class _StubDatabase:
    """Database double serving both auth and gateway queries."""

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        if args:
            arg0 = str(args[0]).lower()
            if arg0 == _CLIENT_KEY:
                return dict(_TENANT_ROW)
            if arg0 == "admin@example.com":
                return dict(_ACTIVE_USER_ROW)
        return None

    async def fetchval(self, query: str, *args: object) -> object:
        return 1

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
    def __init__(self) -> None:
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        self._ops.append(("zremrangebyscore", (key, min_score, max_score)))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._ops.append(("zadd", (key, mapping)))

    def zcard(self, key: str) -> None:
        self._ops.append(("zcard", (key,)))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", (key, seconds)))

    async def execute(self) -> list[Any]:
        # Simulate: after zremrangebyscore, zadd, zcard → count = number of zadds
        zadd_count = sum(1 for op, _ in self._ops if op == "zadd")
        return [0, None, zadd_count, True]

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        return [(b"member", 1000.0)]


class _FailingRedis:
    """Redis stub whose ops all raise RedisError."""

    async def get(self, key: str) -> str | None:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")

    async def getdel(self, key: str) -> str | None:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")

    async def ping(self) -> bool:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")

    async def aclose(self) -> None:
        pass

    def pipeline(self, transaction: bool = False) -> _FailingPipeline:
        return _FailingPipeline()


class _FailingPipeline:
    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        pass

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        pass

    def zcard(self, key: str) -> None:
        pass

    def expire(self, key: str, seconds: int) -> None:
        pass

    async def execute(self) -> list[Any]:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        from redis.exceptions import RedisError
        raise RedisError("connection refused")


# -- Helpers -------------------------------------------------------------------

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
    # Low limits so tests trip fast
    "WIDGET_SESSION_RATE_LIMIT_MAX": "3",
    "WIDGET_SESSION_RATE_LIMIT_WINDOW_SECONDS": "60",
    "AUTH_RATE_LIMIT_MAX": "3",
    "AUTH_RATE_LIMIT_WINDOW_SECONDS": "60",
}


def _build_app(redis: Any = None) -> Any:
    """Create app with test doubles."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app
        app = create_app()

    app.state.db = _StubDatabase()
    app.state.redis = redis if redis is not None else _StubRedis()
    app.state.cache = InMemoryCache()
    # Use a fresh in-memory rate limiter per test so counts don't leak.
    app.state.rate_limiter = InMemoryRateLimiter()
    return app


# ==============================================================================
# /widget/session rate limiting
# ==============================================================================


async def test_widget_session_rate_limit() -> None:
    """First 3 allowed normally; the 4th (same IP) → 429 RATE_LIMITED + Retry-After."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            resp = await c.post(
                "/widget/session",
                json={"client_key": _CLIENT_KEY},
                headers={"Origin": "http://localhost:3000"},
            )
            assert resp.status_code in (200, 403, 422), f"unexpected {resp.status_code}"

        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 429
    assert resp.json()["error_code"] == "RATE_LIMITED"
    assert "retry-after" in resp.headers


# ==============================================================================
# /auth/login rate limiting
# ==============================================================================


async def test_auth_login_rate_limit() -> None:
    """3 rapid login attempts → 429 RATE_LIMITED (independent of credential validity)."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            resp = await c.post("/auth/login", json={
                "email": "admin@example.com",
                "password": "wrong-password",
            })
            assert resp.status_code in (401, 429), f"unexpected {resp.status_code}"
            if resp.status_code == 429:
                break

        resp = await c.post("/auth/login", json={
            "email": "admin@example.com",
            "password": "wrong-password",
        })
    assert resp.status_code == 429
    assert resp.json()["error_code"] == "RATE_LIMITED"
    assert "retry-after" in resp.headers


# ==============================================================================
# /auth/password-reset/request rate limiting
# ==============================================================================


async def test_auth_password_reset_rate_limit() -> None:
    """3 rapid reset requests → 429 RATE_LIMITED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(3):
            resp = await c.post("/auth/password-reset/request", json={
                "email": "admin@example.com",
            })
            assert resp.status_code == 200

        resp = await c.post("/auth/password-reset/request", json={
            "email": "admin@example.com",
        })
    assert resp.status_code == 429
    assert resp.json()["error_code"] == "RATE_LIMITED"
    assert "retry-after" in resp.headers


# ==============================================================================
# Fail-open on Redis error
# ==============================================================================


async def test_rate_limit_fail_open_on_redis_error() -> None:
    """When Redis raises RedisError, requests still succeed (in-memory fallback)."""
    failing_redis = _FailingRedis()
    app = _build_app(redis=failing_redis)
    # Exercise the REAL FallbackRateLimiter: Redis primary (failing) -> in-memory.
    app.state.rate_limiter = build_rate_limiter(failing_redis)
    # Even with a failing Redis, the in-memory fallback handles the rate-limit check.
    # Use an unknown email so the password-reset store (which also uses Redis) is
    # never called -- we're only testing the rate-limiter fallback here.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # First 3 should succeed (within limit)
        for _ in range(3):
            resp = await c.post("/auth/password-reset/request", json={
                "email": "nobody@example.com",
            })
            assert resp.status_code == 200
