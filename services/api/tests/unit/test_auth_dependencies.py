"""Unit tests for auth dependencies, GET /auth/me, and /debug/tenants protection.

Covers:
- get_current_claims: valid cookie, missing cookie, tampered token, expired token
- GET /auth/me: 200 with cookie, 401 without
- /debug/tenants (now protected): no cookie -> 401; PLATFORM_ADMIN -> unscoped;
  CLIENT_ADMIN -> scoped with tenant filter
"""
from __future__ import annotations

import datetime as _dt
from typing import Any
from unittest.mock import patch

from common.auth import AuthClaims, Role
from common.crypto import hash_password
from httpx import ASGITransport, AsyncClient

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


class _RecordingDatabase:
    """Database double that records SQL + params for assertion."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()
        self._rows = rows or []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return self._rows[0] if self._rows else None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        return list(self._rows)

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


class _BlacklistRedis:
    """Redis double that can simulate a blacklisted jti."""

    def __init__(self, *, blacklisted_jtis: set[str] | None = None) -> None:
        self._blacklisted = blacklisted_jtis or set()

    async def get(self, key: str) -> str | None:
        jti = key.replace("auth:blacklist:", "")
        return "1" if jti in self._blacklisted else None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def getdel(self, key: str) -> str | None:
        return None

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


def _build_app(db: Any = None) -> Any:
    """Create app with test doubles, optionally accepting a custom DB double."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = db if db is not None else _StubDatabase()
    app.state.redis = _StubRedis()
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
# get_current_claims tests (via /auth/me as the simplest claims-dependent route)
# ==============================================================================


async def test_get_current_claims_valid_cookie() -> None:
    """A valid cookie yields correct AuthClaims (verified via /auth/me)."""
    app = _build_app()
    token = _mint_cookie(subject="user-42", role=Role.CLIENT_ADMIN, tenant_id=_TENANT_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "user-42"
    assert body["role"] == "CLIENT_ADMIN"
    assert body["tenant_id"] == _TENANT_ID
    assert body["project_ids"] == []


async def test_get_current_claims_missing_cookie_returns_401() -> None:
    """No cookie at all -> 401 UNAUTHENTICATED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_get_current_claims_tampered_token_returns_401() -> None:
    """A tampered token -> 401 UNAUTHENTICATED."""
    app = _build_app()
    token = _mint_cookie()
    tampered = token[:-4] + "XXXX"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": tampered})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_get_current_claims_expired_token_returns_401() -> None:
    """An expired token -> 401 UNAUTHENTICATED."""
    app = _build_app()
    # Mint a token that was created 2 hours in the past with a 60s TTL
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=2)
    with patch("api.auth.tokens._dt") as mock_dt:
        mock_dt.UTC = _dt.UTC
        mock_dt.datetime.now.return_value = past
        mock_dt.timedelta = _dt.timedelta
        token = _mint_cookie(ttl_seconds=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_get_current_claims_wrong_secret_returns_401() -> None:
    """A token signed with a different secret -> 401."""
    app = _build_app()
    token = _mint_cookie(secret="y" * 48)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# GET /auth/me
# ==============================================================================


async def test_me_returns_200_with_valid_cookie() -> None:
    """GET /auth/me with a valid cookie returns 200 + claim fields."""
    app = _build_app()
    token = _mint_cookie(
        subject="pa-1",
        role=Role.PLATFORM_ADMIN,
        tenant_id=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject"] == "pa-1"
    assert body["role"] == "PLATFORM_ADMIN"
    assert body["tenant_id"] is None
    assert isinstance(body["project_ids"], list)


async def test_me_returns_401_without_cookie() -> None:
    """GET /auth/me without a cookie returns 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# /debug/tenants — now protected (end-to-end RBAC/isolation)
# ==============================================================================


async def test_debug_tenants_no_cookie_returns_401() -> None:
    """/debug/tenants without a cookie -> 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/tenants")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_debug_tenants_platform_admin_unscoped() -> None:
    """PLATFORM_ADMIN sees all tenants -- no tenant filter fragment in SQL."""
    db = _RecordingDatabase(rows=[])
    app = _build_app(db=db)
    token = _mint_cookie(
        subject="admin-global",
        role=Role.PLATFORM_ADMIN,
        tenant_id=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/tenants", cookies={"access_token": token})
    assert resp.status_code == 200
    # The recording DB should show NO tenant filter fragment
    assert "id = $" not in db.last_sql
    assert db.last_params == ()


async def test_debug_tenants_client_admin_scoped() -> None:
    """CLIENT_ADMIN sees only its own tenant -- SQL has 'id = $N' with tenant bound."""
    db = _RecordingDatabase(rows=[])
    app = _build_app(db=db)
    token = _mint_cookie(
        subject="admin-a",
        role=Role.CLIENT_ADMIN,
        tenant_id=_TENANT_ID,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/tenants", cookies={"access_token": token})
    assert resp.status_code == 200
    # The recording DB should show the tenant filter fragment
    assert "id = $1" in db.last_sql
    assert _TENANT_ID in db.last_params


async def test_debug_tenants_get_single_no_cookie_returns_401() -> None:
    """/debug/tenants/{id} without a cookie -> 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/tenants/some-id")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# Blacklisted token (logout)
# ==============================================================================


async def test_blacklisted_jti_returns_401() -> None:
    """A token whose jti is in the Redis blacklist -> 401 UNAUTHENTICATED."""
    # Mint a token, decode it to get the jti, then create a Redis double that
    # reports that jti as blacklisted.
    token = _mint_cookie(subject="user-logged-out", role=Role.CLIENT_ADMIN)
    from api.auth.tokens import decode_access_token
    payload = decode_access_token(token, secret=_TEST_JWT_SECRET)
    jti = str(payload["jti"])

    redis = _BlacklistRedis(blacklisted_jtis={jti})
    app = _build_app()
    app.state.redis = redis

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_blacklist_check_redis_error_fail_closed() -> None:
    """When Redis get raises RedisError, /auth/me -> 401 (fail-closed)."""
    from redis.exceptions import RedisError

    class _FailingRedis:
        async def get(self, key: str) -> str | None:
            raise RedisError("connection refused")

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            raise RedisError("connection refused")

        async def getdel(self, key: str) -> str | None:
            raise RedisError("connection refused")

        async def ping(self) -> bool:
            return False

        async def aclose(self) -> None:
            pass

    redis = _FailingRedis()
    app = _build_app()
    app.state.redis = redis

    token = _mint_cookie(subject="user-1", role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/auth/me", cookies={"access_token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"
