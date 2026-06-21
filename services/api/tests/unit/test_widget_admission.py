"""Unit tests for widget admission (POST /widget/session, GET /widget/whoami).

Covers:
- POST /widget/session: valid key + allowed Origin -> 200; unknown key -> 422;
  disallowed/missing Origin -> 403; disabled tenant -> 403.
- Multi-tenant isolation: key for tenant A + A's origin -> token carries A's tenant_id.
- GET /widget/whoami: valid visitor bearer -> 200; no header -> 401;
  non-visitor token -> 403; tampered/expired bearer -> 401.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any
from unittest.mock import patch

from common.auth import AuthClaims, Role
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_A_ID = "tenant-a-123"
_TENANT_B_ID = "tenant-b-456"
_CLIENT_KEY_A = "pk_key-aaa"
_CLIENT_KEY_B = "pk_key-bbb"

# -- Test doubles --------------------------------------------------------------

_TENANT_A_ROW: dict[str, Any] = {
    "id": _TENANT_A_ID,
    "slug": "tenant-a",
    "enabled": True,
    "allowed_origins": ["http://localhost:3000", "https://a.example.com"],
}

_TENANT_B_ROW: dict[str, Any] = {
    "id": _TENANT_B_ID,
    "slug": "tenant-b",
    "enabled": True,
    "allowed_origins": ["https://b.example.com"],
}

_TENANT_DISABLED_ROW: dict[str, Any] = {
    "id": "tenant-disabled",
    "slug": "tenant-disabled",
    "enabled": False,
    "allowed_origins": ["http://localhost:3000"],
}

_CLIENT_KEY_DB: dict[str, dict[str, Any]] = {
    _CLIENT_KEY_A: _TENANT_A_ROW,
    _CLIENT_KEY_B: _TENANT_B_ROW,
    "pk_disabled": _TENANT_DISABLED_ROW,
}


class _StubDatabase:
    """Database double for gateway queries (lookup by client_key)."""

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        if args:
            client_key = str(args[0])
            return _CLIENT_KEY_DB.get(client_key)
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


def _build_app() -> Any:
    """Create app with test doubles."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app
        app = create_app()

    app.state.db = _StubDatabase()
    app.state.redis = _StubRedis()
    return app


def _mint_visitor_token(
    *,
    tenant_id: str = _TENANT_A_ID,
    role: Role = Role.VISITOR,
    ttl_seconds: int = 300,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    """Create a signed JWT for use as a bearer token."""
    claims = AuthClaims(
        subject="visitor-1",
        role=role,
        tenant_id=tenant_id,
    )
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    return token


# ==============================================================================
# POST /widget/session
# ==============================================================================


async def test_widget_session_valid_key_and_origin() -> None:
    """Valid key + allowed Origin -> 200 with visitor_token + expires_at."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY_A},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "visitor_token" in body
    assert "expires_at" in body

    # Decode the token to verify role and tenant_id
    from api.auth.tokens import decode_access_token
    payload = decode_access_token(body["visitor_token"], secret=_TEST_JWT_SECRET)
    assert payload["role"] == "VISITOR"
    assert payload["tenant_id"] == _TENANT_A_ID


async def test_widget_session_unknown_key() -> None:
    """Unknown client key -> 422 INVALID_CLIENT_KEY."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": "pk_does_not_exist"},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_CLIENT_KEY"


async def test_widget_session_disallowed_origin() -> None:
    """Valid key + disallowed Origin -> 403 ORIGIN_NOT_ALLOWED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY_A},
            headers={"Origin": "http://evil.example"},
        )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


async def test_widget_session_missing_origin() -> None:
    """Valid key + no Origin header -> 403 ORIGIN_NOT_ALLOWED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY_A},
        )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


async def test_widget_session_disabled_tenant() -> None:
    """Valid key + disabled tenant -> 403 TENANT_DISABLED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": "pk_disabled"},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "TENANT_DISABLED"


# ==============================================================================
# Multi-tenant isolation
# ==============================================================================


async def test_widget_session_multi_tenant_isolation() -> None:
    """Key for tenant A + A's origin -> token carries A's tenant_id, never B's."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY_A},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 200
    body = resp.json()

    from api.auth.tokens import decode_access_token
    payload = decode_access_token(body["visitor_token"], secret=_TEST_JWT_SECRET)
    assert payload["tenant_id"] == _TENANT_A_ID
    assert payload["tenant_id"] != _TENANT_B_ID


async def test_widget_session_wrong_origin_for_tenant() -> None:
    """Tenant B's key + tenant A's origin -> 403 (A's origin not in B's allowlist)."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/widget/session",
            json={"client_key": _CLIENT_KEY_B},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


# ==============================================================================
# GET /widget/whoami
# ==============================================================================


async def test_widget_whoami_valid_visitor_bearer() -> None:
    """Valid visitor bearer -> 200 with visitor_id, tenant_id, role=VISITOR."""
    app = _build_app()
    token = _mint_visitor_token(tenant_id=_TENANT_A_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/widget/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "VISITOR"
    assert body["tenant_id"] == _TENANT_A_ID
    assert body["visitor_id"] == "visitor-1"


async def test_widget_whoami_no_authorization_header() -> None:
    """No Authorization header -> 401 UNAUTHENTICATED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/widget/whoami")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_widget_whoami_non_visitor_token() -> None:
    """CLIENT_ADMIN token as bearer -> 403 NOT_A_VISITOR."""
    app = _build_app()
    token = _mint_visitor_token(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/widget/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "NOT_A_VISITOR"


async def test_widget_whoami_tampered_token() -> None:
    """Tampered bearer -> 401 UNAUTHENTICATED."""
    app = _build_app()
    token = _mint_visitor_token()
    tampered = token[:-4] + "XXXX"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/widget/whoami",
            headers={"Authorization": f"Bearer {tampered}"},
        )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_widget_whoami_expired_token() -> None:
    """Expired bearer -> 401 UNAUTHENTICATED."""
    app = _build_app()
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=2)
    with patch("api.auth.tokens._dt") as mock_dt:
        mock_dt.UTC = _dt.UTC
        mock_dt.datetime.now.return_value = past
        mock_dt.timedelta = _dt.timedelta
        token = _mint_visitor_token(ttl_seconds=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/widget/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"
