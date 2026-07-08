"""Unit tests for audit routes.

Covers:
- GET /admin/audit → 200 list for the tenant, tenant_id NOT in the response.
- RBAC — CLIENT_ADMIN ok, CLIENT_AGENT → 403, VISITOR → 403, no auth → 401.
- limit/offset respected.
"""
from __future__ import annotations

from datetime import UTC, datetime
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


class _StubDatabase:
    """Database double that can return canned audit rows."""

    def __init__(self, *, audit_rows: list[dict[str, Any]] | None = None) -> None:
        self._audit_rows = audit_rows or []
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return None

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        return self._audit_rows

    async def execute(self, query: str, *args: object) -> str:
        self.last_sql = query
        self.last_params = args
        return "INSERT 1"

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


def _build_app(db: Any = None) -> Any:
    """Create app with test doubles."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = db if db is not None else _StubDatabase()
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
    claims = AuthClaims(subject=subject, role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    return token


# ==============================================================================
# GET /admin/audit
# ==============================================================================


async def test_audit_list_returns_200_no_tenant_id() -> None:
    """CLIENT_ADMIN → 200 list, tenant_id NOT in the response."""
    now = datetime.now(UTC).isoformat()
    audit_rows = [
        {
            "event_id": "evt-1",
            "actor": "user-1",
            "action": "auth.login",
            "target_type": "user",
            "target_id": "user-1",
            "metadata": {},
            "created_at": now,
        },
    ]
    db = _StubDatabase(audit_rows=audit_rows)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/admin/audit?limit=10",
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["event_id"] == "evt-1"
    assert body[0]["action"] == "auth.login"
    assert "tenant_id" not in body[0]


async def test_audit_list_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403."""
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/admin/audit?limit=10",
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_audit_list_visitor_returns_403() -> None:
    """VISITOR → 403."""
    app = _build_app()
    token = _mint_cookie(role=Role.VISITOR)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/admin/audit?limit=10",
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_audit_list_no_cookie_returns_401() -> None:
    """No cookie → 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/admin/audit?limit=10",
        )
    assert resp.status_code == 401


async def test_audit_list_respects_limit_and_offset() -> None:
    """limit/offset are passed through to the repository."""
    db = _StubDatabase(audit_rows=[])
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/admin/audit?limit=5&offset=10",
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    assert db.last_params[1] == 5
    assert db.last_params[2] == 10
