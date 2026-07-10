"""Unit tests for PUT /admin/schedule/availability.

Covers:
- CLIENT_ADMIN -> 200, availability upserted.
- CLIENT_AGENT / VISITOR -> 403.
- No auth -> 401.
- Invalid IANA timezone -> 422, nothing persisted.
- Invalid rules shape (bad HH:MM, start>=end, slot_minutes<=0,
  buffer_minutes<0, unknown weekday key) -> 422.
- Tenant-scoped: two tenants' availability never collide.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"
_OTHER_TENANT_ID = "tenant-xyz-999"

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

_VALID_BODY = {
    "timezone": "America/New_York",
    "rules": {
        "slot_minutes": 30,
        "buffer_minutes": 0,
        "weekly_hours": {
            "mon": [["09:00", "17:00"]], "tue": [["09:00", "17:00"]],
            "wed": [["09:00", "17:00"]], "thu": [["09:00", "17:00"]],
            "fri": [["09:00", "17:00"]], "sat": [], "sun": [],
        },
    },
}


class _StubDatabase:
    def __init__(self) -> None:
        self._availability: dict[str, dict[str, Any]] = {}

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip().upper()
        if q.startswith("INSERT INTO AVAILABILITY"):
            tenant_id, timezone, rules = args
            self._availability[tenant_id] = {
                "tenant_id": tenant_id, "timezone": timezone, "rules": rules,
            }
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.strip().upper()
        if "FROM AVAILABILITY" in q:
            tenant_id = args[0]
            row = self._availability.get(tenant_id)
            if row is None:
                return None
            from datetime import UTC, datetime

            return {**row, "updated_at": datetime(2026, 1, 1, tzinfo=UTC)}
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return []

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


def _reset_settings() -> None:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _build_app(db: _StubDatabase) -> Any:
    _reset_settings()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = db
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    return app


def _token(role: Role, tenant_id: str | None = _TENANT_ID) -> str:
    claims = AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=_TEST_JWT_SECRET, ttl_seconds=300)
    return token


async def test_client_admin_can_set_availability() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/schedule/availability", json=_VALID_BODY, cookies={"access_token": token}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["timezone"] == "America/New_York"
    assert "tenant_id" not in data
    assert db._availability[_TENANT_ID]["timezone"] == "America/New_York"


async def test_client_agent_forbidden() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT)
        response = await client.put(
            "/admin/schedule/availability", json=_VALID_BODY, cookies={"access_token": token}
        )

    assert response.status_code == 403


async def test_visitor_forbidden() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.VISITOR)
        response = await client.put(
            "/admin/schedule/availability", json=_VALID_BODY, cookies={"access_token": token}
        )

    assert response.status_code == 403


async def test_no_auth_returns_401() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/admin/schedule/availability", json=_VALID_BODY)

    assert response.status_code == 401


async def test_invalid_timezone_returns_422_and_nothing_persisted() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {**_VALID_BODY, "timezone": "Not/A_Real_Zone"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/schedule/availability", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 422
    assert db._availability == {}


@pytest.mark.parametrize(
    "rules_override",
    [
        pytest.param({"slot_minutes": 0}, id="slot_minutes_zero"),
        pytest.param({"slot_minutes": -5}, id="slot_minutes_negative"),
        pytest.param({"buffer_minutes": -1}, id="buffer_minutes_negative"),
        pytest.param(
            {"weekly_hours": {"mon": [["9:00", "17:00"]]}},
            id="bad_hhmm_format",
        ),
        pytest.param(
            {"weekly_hours": {"mon": [["17:00", "09:00"]]}},
            id="start_after_end",
        ),
        pytest.param(
            {"weekly_hours": {"monday": [["09:00", "17:00"]]}},
            id="unknown_weekday_key",
        ),
    ],
)
async def test_invalid_rules_shape_returns_422(rules_override: dict[str, Any]) -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {
        "timezone": "America/New_York",
        "rules": {**_VALID_BODY["rules"], **rules_override},
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/schedule/availability", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 422
    assert db._availability == {}


async def test_tenant_scoped_no_cross_tenant_collision() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body_b = {**_VALID_BODY, "timezone": "UTC"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token_a = _token(Role.CLIENT_ADMIN, tenant_id=_TENANT_ID)
        token_b = _token(Role.CLIENT_ADMIN, tenant_id=_OTHER_TENANT_ID)
        await client.put(
            "/admin/schedule/availability", json=_VALID_BODY, cookies={"access_token": token_a}
        )
        await client.put(
            "/admin/schedule/availability", json=body_b, cookies={"access_token": token_b}
        )

    assert db._availability[_TENANT_ID]["timezone"] == "America/New_York"
    assert db._availability[_OTHER_TENANT_ID]["timezone"] == "UTC"
