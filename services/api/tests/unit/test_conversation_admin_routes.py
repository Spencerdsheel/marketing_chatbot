"""Unit tests for GET /admin/conversations (list) and
GET /admin/conversations/{conversation_id} (transcript detail).

Covers (S12.4):
- Happy path (CLIENT_ADMIN + CLIENT_AGENT) -> 200 with {items, total, limit, offset}.
- RBAC negatives: VISITOR -> 403, no cookie -> 401, PLATFORM_ADMIN -> 403.
- Filter validation: status=bogus -> 422 INVALID_CONVERSATION_FILTER;
  escalated=true/false both 200; from>=to -> 422 INVALID_LIST_WINDOW.
- Transcript detail: visible conversation -> 200 with messages, no tenant_id;
  missing/cross-tenant -> 404 CONVERSATION_NOT_FOUND; VISITOR/no-cookie -> 403/401.
- Leak-free: no tenant_id anywhere in list items or transcript body.
- MANDATORY tenant isolation: an agent sees only their own tenant's conversations.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _StubDatabase:
    """In-memory stub database backing /admin/conversations for these tests."""

    def __init__(self) -> None:
        self._conversations: dict[tuple[str, str], dict[str, Any]] = {}
        self._messages: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def seed_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        status: str = "active",
        channel: str = "widget",
        visitor_id: str | None = "visitor-1",
        started_at: datetime = _NOW,
        ended_at: datetime | None = None,
        summary: str | None = None,
    ) -> None:
        self._conversations[(tenant_id, conversation_id)] = {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "status": status,
            "channel": channel,
            "visitor_id": visitor_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "metadata": {},
            "summary": summary,
            "summary_message_count": 0,
        }
        self._messages.setdefault((tenant_id, conversation_id), [])

    def seed_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        message_id: str,
        role: str = "user",
        content: str = "hello",
        decision: str | None = None,
        created_at: datetime = _NOW,
    ) -> None:
        self._messages.setdefault((tenant_id, conversation_id), []).append(
            {
                "message_id": message_id,
                "role": role,
                "content": content,
                "intent": None,
                "confidence": None,
                "tokens": None,
                "created_at": created_at,
                "decision": decision,
            }
        )

    def _has_escalate(self, tenant_id: str, conversation_id: str) -> bool:
        return any(
            m["role"] == "bot" and m["decision"] == "escalate"
            for m in self._messages.get((tenant_id, conversation_id), [])
        )

    def _filtered_conversations(
        self, query: str, args: tuple[Any, ...],
    ) -> tuple[list[dict[str, Any]], int]:
        q = query.upper()
        idx = 0
        tenant_id = args[idx]
        idx += 1
        rows = [c for c in self._conversations.values() if c["tenant_id"] == tenant_id]

        if "STARTED_AT >= $" in q:
            rows = [r for r in rows if r["started_at"] >= args[idx]]
            idx += 1
        if "STARTED_AT < $" in q:
            rows = [r for r in rows if r["started_at"] < args[idx]]
            idx += 1
        if "C.STATUS = $" in q:
            rows = [r for r in rows if r["status"] == args[idx]]
            idx += 1
        if "C.CHANNEL = $" in q:
            rows = [r for r in rows if r["channel"] == args[idx]]
            idx += 1
        if "NOT EXISTS" in q:
            rows = [r for r in rows if not self._has_escalate(r["tenant_id"], r["conversation_id"])]
        elif "EXISTS" in q:
            rows = [r for r in rows if self._has_escalate(r["tenant_id"], r["conversation_id"])]

        rows.sort(key=lambda r: (r["started_at"], r["conversation_id"]), reverse=True)
        total = len(rows)

        if "LIMIT $" in q:
            limit = args[idx]
            idx += 1
            offset = args[idx] if idx < len(args) else 0
            rows = rows[offset : offset + limit]

        return rows, total

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.strip().upper()
        if "COUNT(*)" in q and "FROM CONVERSATIONS" in q:
            _, total = self._filtered_conversations(query, args)
            return {"count": total}
        if "SELECT 1 FROM CONVERSATIONS" in q:
            tenant_id, conversation_id = args[0], args[1]
            return self._conversations.get((tenant_id, conversation_id))
        if "FROM CONVERSATIONS" in q and "WHERE TENANT_ID" in q:
            tenant_id, conversation_id = args[0], args[1]
            return self._conversations.get((tenant_id, conversation_id))
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = query.strip().upper()
        if "FROM CONVERSATIONS C" in q and "LIMIT $" in q:
            rows, _ = self._filtered_conversations(query, args)
            return [
                {
                    **r,
                    "message_count": len(self._messages.get((r["tenant_id"], r["conversation_id"]), [])),
                }
                for r in rows
            ]
        if "FROM MESSAGES" in q:
            tenant_id, conversation_id = args[0], args[1]
            msgs = list(self._messages.get((tenant_id, conversation_id), []))
            msgs.sort(key=lambda m: (m["created_at"], m["message_id"]))
            return msgs
        return []

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"

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
    import os

    old_env = {k: os.environ.get(k) for k in _TEST_SETTINGS_ENV}
    os.environ.update(_TEST_SETTINGS_ENV)
    try:
        from api.app import create_app

        app = create_app()
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    app.state.db = db
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    return app


def _token(role: Role, tenant_id: str | None = _TENANT_ID, subject: str = "user-1") -> str:
    claims = AuthClaims(subject=subject, role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=_TEST_JWT_SECRET, ttl_seconds=300)
    return token


@pytest.fixture
def db() -> _StubDatabase:
    return _StubDatabase()


@pytest.fixture
def app(db: _StubDatabase) -> Any:
    return _build_app(db)


# ---------------------------------------------------------------------------
# GET /admin/conversations -- happy path + RBAC
# ---------------------------------------------------------------------------


async def test_list_conversations_happy_path_client_admin(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-1")
    db.seed_message(tenant_id=_TENANT_ID, conversation_id="conv-1", message_id="m1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get("/admin/conversations", cookies={"access_token": token})

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}
    assert data["total"] == 1
    item = data["items"][0]
    assert item["conversation_id"] == "conv-1"
    assert item["message_count"] == 1
    assert "tenant_id" not in item


async def test_list_conversations_client_agent_allowed(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-2")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT)
        response = await client.get("/admin/conversations", cookies={"access_token": token})

    assert response.status_code == 200


async def test_list_conversations_visitor_forbidden(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.VISITOR)
        response = await client.get("/admin/conversations", cookies={"access_token": token})

    assert response.status_code == 403


async def test_list_conversations_no_auth_returns_401(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/conversations")

    assert response.status_code == 401


async def test_list_conversations_platform_admin_forbidden(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.PLATFORM_ADMIN, tenant_id=None)
        response = await client.get("/admin/conversations", cookies={"access_token": token})

    assert response.status_code == 403
    assert response.json()["error_code"] == "ROLE_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# GET /admin/conversations -- filter validation
# ---------------------------------------------------------------------------


async def test_list_conversations_invalid_status_returns_422(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations?status=bogus", cookies={"access_token": token},
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_CONVERSATION_FILTER"


async def test_list_conversations_escalated_true_filters(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-escalated")
    db.seed_message(
        tenant_id=_TENANT_ID, conversation_id="conv-escalated", message_id="m1",
        role="bot", decision="escalate",
    )
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-clean")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations?escalated=true", cookies={"access_token": token},
        )

    assert response.status_code == 200
    ids = [item["conversation_id"] for item in response.json()["items"]]
    assert ids == ["conv-escalated"]


async def test_list_conversations_escalated_false_filters(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-escalated")
    db.seed_message(
        tenant_id=_TENANT_ID, conversation_id="conv-escalated", message_id="m1",
        role="bot", decision="escalate",
    )
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-clean")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations?escalated=false", cookies={"access_token": token},
        )

    assert response.status_code == 200
    ids = [item["conversation_id"] for item in response.json()["items"]]
    assert ids == ["conv-clean"]


async def test_list_conversations_from_gte_to_returns_422(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations?from=2026-06-01T00:00:00Z&to=2026-01-01T00:00:00Z",
            cookies={"access_token": token},
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_LIST_WINDOW"


async def test_list_conversations_status_and_channel_filter_200(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-3", status="ended", channel="widget")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations?status=ended&channel=widget", cookies={"access_token": token},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["conversation_id"] == "conv-3"


# ---------------------------------------------------------------------------
# GET /admin/conversations/{conversation_id} -- transcript detail
# ---------------------------------------------------------------------------


async def test_get_conversation_detail_returns_200_with_messages(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-detail")
    db.seed_message(tenant_id=_TENANT_ID, conversation_id="conv-detail", message_id="m1", content="hi there")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations/conv-detail", cookies={"access_token": token},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "conv-detail"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["content"] == "hi there"
    assert "tenant_id" not in data


async def test_get_conversation_detail_client_agent_allowed(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-detail2")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT)
        response = await client.get(
            "/admin/conversations/conv-detail2", cookies={"access_token": token},
        )

    assert response.status_code == 200


async def test_get_conversation_detail_missing_returns_404(app: Any, db: _StubDatabase) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.get(
            "/admin/conversations/does-not-exist", cookies={"access_token": token},
        )

    assert response.status_code == 404
    assert response.json()["error_code"] == "CONVERSATION_NOT_FOUND"


async def test_get_conversation_detail_cross_tenant_returns_404(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-cross")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT, tenant_id=_OTHER_TENANT_ID)
        response = await client.get(
            "/admin/conversations/conv-cross", cookies={"access_token": token},
        )

    assert response.status_code == 404


async def test_get_conversation_detail_visitor_forbidden(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-4")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.VISITOR)
        response = await client.get(
            "/admin/conversations/conv-4", cookies={"access_token": token},
        )

    assert response.status_code == 403


async def test_get_conversation_detail_no_auth_returns_401(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-5")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/conversations/conv-5")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# MANDATORY: cross-tenant isolation on the list surface
# ---------------------------------------------------------------------------


async def test_list_conversations_agent_sees_only_own_tenant(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-mine")
    db.seed_conversation(tenant_id=_OTHER_TENANT_ID, conversation_id="conv-other")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT, tenant_id=_TENANT_ID)
        response = await client.get("/admin/conversations", cookies={"access_token": token})

    assert response.status_code == 200
    ids = [item["conversation_id"] for item in response.json()["items"]]
    assert ids == ["conv-mine"]


# ---------------------------------------------------------------------------
# Leak-free
# ---------------------------------------------------------------------------


async def test_list_and_detail_never_leak_tenant_id(app: Any, db: _StubDatabase) -> None:
    db.seed_conversation(tenant_id=_TENANT_ID, conversation_id="conv-leak")
    db.seed_message(tenant_id=_TENANT_ID, conversation_id="conv-leak", message_id="m1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        list_response = await client.get("/admin/conversations", cookies={"access_token": token})
        detail_response = await client.get(
            "/admin/conversations/conv-leak", cookies={"access_token": token},
        )

    assert "tenant_id" not in list_response.text
    assert "tenant_id" not in detail_response.text
