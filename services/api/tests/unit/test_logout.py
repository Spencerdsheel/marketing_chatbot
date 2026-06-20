"""Unit tests for POST /auth/logout.

Covers:
- Logout success -> 200, cookie cleared, jti blacklisted in Redis
- No cookie -> 401 UNAUTHENTICATED
- Invalid/expired/tampered token -> 401 (strict; no cookie cleared, no set recorded)
- End-to-end revocation: logout then reuse same token -> 401
- Fail-closed: Redis set raises RedisError -> logout raises (NOT silent 200)
"""
from __future__ import annotations

import datetime as _dt
from typing import Any
from unittest.mock import patch

from common.auth import AuthClaims, Role
from common.crypto import hash_password
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError

from api.auth.tokens import create_access_token

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"

_KNOWN_PASSPHRASE = "correct horse battery staple"
_KNOWN_HASH = hash_password(_KNOWN_PASSPHRASE)

_CLIENT_ADMIN_ROW: dict[str, Any] = {
    "id": "ca-user-1",
    "tenant_id": _TENANT_ID,
    "email": "admin@example.com",
    "role": "CLIENT_ADMIN",
    "password_hash": _KNOWN_HASH,
    "name": "Account Owner",
    "active": True,
    "last_login_at": None,
}

_USER_DB: dict[str, dict[str, Any]] = {
    "admin@example.com": _CLIENT_ADMIN_ROW,
}


# -- Test doubles --------------------------------------------------------------


class _StubDatabase:
    """Minimal database double for auth queries."""

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        if args:
            email = str(args[0]).lower()
            for key, row in _USER_DB.items():
                if key.lower() == email:
                    return dict(row)
        return None

    async def fetchval(self, query: str, *args: object) -> object:
        return 1

    async def execute(self, query: str, *args: object) -> str:
        return "UPDATE 1"

    async def close(self) -> None:
        pass


class _RecordingRedis:
    """Redis double that tracks set/get calls for blacklist assertions."""

    def __init__(self, *, fail_set: bool = False, fail_get: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._fail_set = fail_set
        self._fail_get = fail_get
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.get_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        if self._fail_get:
            raise RedisError("connection refused")
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        if self._fail_set:
            raise RedisError("connection refused")
        self._store[key] = value

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


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
    app.state.redis = redis if redis is not None else _RecordingRedis()
    return app


def _mint_cookie(
    *,
    subject: str = "user-1",
    role: Role = Role.CLIENT_ADMIN,
    tenant_id: str | None = _TENANT_ID,
    ttl_seconds: int = 300,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    """Create a signed JWT suitable for use as the access_token cookie."""
    claims = AuthClaims(subject=subject, role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    return token


# ==============================================================================
# Logout success
# ==============================================================================


async def test_logout_success_returns_200() -> None:
    """POST /auth/logout with a valid cookie -> 200."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    token = _mint_cookie(subject="user-1", role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 200


async def test_logout_clears_cookie() -> None:
    """POST /auth/logout -> Set-Cookie with max-age=0 (clears the cookie)."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    token = _mint_cookie()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "access_token=" in cookie_header
    assert "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()


async def test_logout_blacklists_jti_in_redis() -> None:
    """POST /auth/logout -> Redis SET with key auth:blacklist:<jti>, value "1", positive TTL."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    token = _mint_cookie()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 200
    assert len(redis.set_calls) == 1
    key, value, ttl = redis.set_calls[0]
    assert key.startswith("auth:blacklist:")
    assert value == "1"
    assert ttl is not None and ttl > 0


# ==============================================================================
# Strict: no cookie / invalid token -> 401
# ==============================================================================


async def test_logout_without_cookie_returns_401() -> None:
    """POST /auth/logout without a cookie -> 401."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_logout_invalid_token_returns_401() -> None:
    """POST /auth/logout with a tampered token -> 401 (strict; no cookie cleared, no set)."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    token = _mint_cookie()
    tampered = token[:-4] + "XXXX"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": tampered})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"
    assert len(redis.set_calls) == 0


async def test_logout_expired_token_returns_401() -> None:
    """POST /auth/logout with an expired token -> 401 (strict)."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=2)
    with patch("api.auth.tokens._dt") as mock_dt:
        mock_dt.UTC = _dt.UTC
        mock_dt.datetime.now.return_value = past
        mock_dt.timedelta = _dt.timedelta
        token = _mint_cookie(ttl_seconds=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"
    assert len(redis.set_calls) == 0


# ==============================================================================
# End-to-end revocation
# ==============================================================================


async def test_blacklisted_token_rejected_on_me() -> None:
    """After logout, using the same token on /auth/me -> 401."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    token = _mint_cookie()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # First logout
        logout_resp = await c.post("/auth/logout", cookies={"access_token": token})
        assert logout_resp.status_code == 200
        # Then try to use the same token
        me_resp = await c.get("/auth/me", cookies={"access_token": token})
    assert me_resp.status_code == 401
    assert me_resp.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# Fail-closed
# ==============================================================================


async def test_logout_redis_set_fails_closed() -> None:
    """When Redis set raises RedisError, logout does NOT return 200 (fail-closed)."""
    redis = _RecordingRedis(fail_set=True)
    app = _build_app(redis=redis)
    token = _mint_cookie()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/logout", cookies={"access_token": token})
    # Fail-closed: the RedisError propagates -> 500
    assert resp.status_code == 500
