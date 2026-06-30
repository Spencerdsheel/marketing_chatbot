"""Unit tests for debug conversation routes.

Covers:
- POST /debug/conversations → 200 {conversation_id, status}.
- POST /debug/conversations/{id}/messages → 200 {message_id}.
- GET /debug/conversations/{id} → 200 with messages, no tenant_id in body.
- Missing conversation → 404 CONVERSATION_NOT_FOUND.
- CLIENT_AGENT on create/append → 403.
- No cookie → 401.
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
    """Database double that can return canned rows."""

    def __init__(self, *, conv_row: dict[str, Any] | None = None, message_rows: list[dict[str, Any]] | None = None) -> None:
        self._conv_row = conv_row
        self._message_rows = message_rows or []
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return self._conv_row

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        return self._message_rows

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
# POST /debug/conversations
# ==============================================================================


async def test_create_conversation_returns_200() -> None:
    """CLIENT_ADMIN → 200 {conversation_id, status}."""
    db = _StubDatabase()
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations",
            json={"channel": "widget"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "conversation_id" in body
    assert body["status"] == "active"


async def test_create_conversation_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403 on create."""
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations",
            json={"channel": "widget"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_create_conversation_no_cookie_returns_401() -> None:
    """No cookie → 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations",
            json={"channel": "widget"},
        )
    assert resp.status_code == 401


# ==============================================================================
# POST /debug/conversations/{id}/messages
# ==============================================================================


async def test_append_message_returns_200() -> None:
    """CLIENT_ADMIN → 200 {message_id}."""
    db = _StubDatabase(conv_row={"conversation_id": "conv-1", "status": "active"})
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations/conv-1/messages",
            json={"role": "user", "content": "Hello"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "message_id" in body


async def test_append_message_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403 on append."""
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations/conv-1/messages",
            json={"role": "user", "content": "Hello"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_append_message_no_cookie_returns_401() -> None:
    """No cookie → 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations/conv-1/messages",
            json={"role": "user", "content": "Hello"},
        )
    assert resp.status_code == 401


# ==============================================================================
# GET /debug/conversations/{id}
# ==============================================================================


async def test_get_conversation_returns_200_with_messages() -> None:
    """Present conversation → 200 with messages, no tenant_id in body."""
    now = datetime.now(UTC).isoformat()
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": now,
        "ended_at": None,
        "metadata": {},
    }
    message_rows = [
        {
            "message_id": "msg-1",
            "role": "user",
            "content": "Hello",
            "intent": None,
            "confidence": None,
            "tokens": None,
            "created_at": now,
        },
    ]
    db = _StubDatabase(conv_row=conv_row, message_rows=message_rows)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1",
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "conv-1"
    assert body["status"] == "active"
    assert "tenant_id" not in body
    assert len(body["messages"]) == 1
    assert body["messages"][0]["message_id"] == "msg-1"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"
    assert "tenant_id" not in body["messages"][0]


async def test_get_conversation_not_found_returns_404() -> None:
    """Missing conversation → 404 CONVERSATION_NOT_FOUND."""
    db = _StubDatabase(conv_row=None)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/nonexistent",
            cookies={"access_token": token},
        )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONVERSATION_NOT_FOUND"


async def test_create_no_trailing_slash_returns_200() -> None:
    """POST /debug/conversations (no trailing slash) → 200, not 307."""
    db = _StubDatabase()
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/conversations",
            json={"channel": "widget"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "conversation_id" in body
    assert body["status"] == "active"


# ==============================================================================
# GET /debug/conversations/{id}/window
# ==============================================================================


async def test_window_by_limit_returns_200() -> None:
    """GET /{id}/window?limit=2 → 200 {conversation_id, count, messages}."""
    now = datetime.now(UTC).isoformat()
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": now,
        "ended_at": None,
        "metadata": {},
    }
    message_rows = [
        {
            "message_id": "msg-2",
            "role": "bot",
            "content": "Hello back",
            "intent": None,
            "confidence": None,
            "tokens": None,
            "created_at": now,
        },
        {
            "message_id": "msg-1",
            "role": "user",
            "content": "Hello",
            "intent": None,
            "confidence": None,
            "tokens": None,
            "created_at": now,
        },
    ]
    db = _StubDatabase(conv_row=conv_row, message_rows=message_rows)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1/window?limit=2",
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == "conv-1"
    assert body["count"] == 2
    assert len(body["messages"]) == 2
    assert "tenant_id" not in body


async def test_window_by_token_budget_returns_200() -> None:
    """GET /{id}/window?token_budget=50 → 200."""
    now = datetime.now(UTC).isoformat()
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": now,
        "ended_at": None,
        "metadata": {},
    }
    message_rows = [
        {
            "message_id": "msg-1",
            "role": "user",
            "content": "Hello",
            "intent": None,
            "confidence": None,
            "tokens": 5,
            "created_at": now,
        },
    ]
    db = _StubDatabase(conv_row=conv_row, message_rows=message_rows)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1/window?token_budget=50",
            cookies={"access_token": token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1


async def test_window_neither_param_returns_422() -> None:
    """GET /{id}/window with neither limit nor token_budget → 422 INVALID_WINDOW_ARGS."""
    conv_row = {"conversation_id": "conv-1", "status": "active"}
    db = _StubDatabase(conv_row=conv_row)
    app = _build_app(db=db)
    token = _mint_cookie(role=Role.CLIENT_ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1/window",
            cookies={"access_token": token},
        )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_WINDOW_ARGS"


async def test_window_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403 on window."""
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1/window?limit=2",
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_window_no_cookie_returns_401() -> None:
    """No cookie → 401."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/debug/conversations/conv-1/window?limit=2",
        )
    assert resp.status_code == 401
