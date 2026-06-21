"""Unit tests for RBAC route-level enforcement.

Covers the full role matrix against the two reference probe endpoints:
- GET /debug/rbac/admin: CLIENT_ADMIN or PLATFORM_ADMIN → 200; CLIENT_AGENT → 403; no cookie → 401
- GET /debug/rbac/platform: PLATFORM_ADMIN → 200; CLIENT_ADMIN/CLIENT_AGENT → 403; no cookie → 401
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"


# -- Test doubles --------------------------------------------------------------


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

    app.state.db = None  # Not needed for RBAC tests
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None
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
# GET /debug/rbac/admin — CLIENT_ADMIN or PLATFORM_ADMIN
# ==============================================================================


async def test_rbac_admin_no_cookie_returns_401() -> None:
    """No cookie → 401 UNAUTHENTICATED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/admin")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_rbac_admin_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403 ROLE_NOT_PERMITTED (excluded from admin tier)."""
    app = _build_app()
    token = _mint_cookie(subject="agent-1", role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/admin", cookies={"access_token": token})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ROLE_NOT_PERMITTED"


async def test_rbac_admin_client_admin_returns_200() -> None:
    """CLIENT_ADMIN → 200 (body echoes role + tenant)."""
    app = _build_app()
    token = _mint_cookie(subject="ca-1", role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/admin", cookies={"access_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "CLIENT_ADMIN"
    assert body["tenant_id"] == _TENANT_ID


async def test_rbac_admin_platform_admin_returns_200() -> None:
    """PLATFORM_ADMIN → 200 (included in admin tier)."""
    app = _build_app()
    token = _mint_cookie(
        subject="pa-1",
        role=Role.PLATFORM_ADMIN,
        tenant_id=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/admin", cookies={"access_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "PLATFORM_ADMIN"
    assert body["tenant_id"] is None


# ==============================================================================
# GET /debug/rbac/platform — PLATFORM_ADMIN only
# ==============================================================================


async def test_rbac_platform_no_cookie_returns_401() -> None:
    """No cookie → 401 UNAUTHENTICATED."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/platform")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


async def test_rbac_platform_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403 ROLE_NOT_PERMITTED."""
    app = _build_app()
    token = _mint_cookie(subject="agent-1", role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/platform", cookies={"access_token": token})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ROLE_NOT_PERMITTED"


async def test_rbac_platform_client_admin_returns_403() -> None:
    """CLIENT_ADMIN → 403 ROLE_NOT_PERMITTED (excluded from platform tier)."""
    app = _build_app()
    token = _mint_cookie(subject="ca-1", role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/platform", cookies={"access_token": token})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ROLE_NOT_PERMITTED"


async def test_rbac_platform_platform_admin_returns_200() -> None:
    """PLATFORM_ADMIN → 200 (tenant_id=null)."""
    app = _build_app()
    token = _mint_cookie(
        subject="pa-1",
        role=Role.PLATFORM_ADMIN,
        tenant_id=None,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/debug/rbac/platform", cookies={"access_token": token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "PLATFORM_ADMIN"
    assert body["tenant_id"] is None
