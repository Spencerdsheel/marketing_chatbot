"""Unit tests for the conversation store repository.

Covers:
- create_conversation inserts with the caller's tenant_id; returns 32-char hex id.
- Tenant isolation: get_conversation/get_messages/append_message bind WHERE tenant_id.
- VISITOR scoping: VISITOR binds extra visitor_id filter; CLIENT_ADMIN does not.
- Idempotent append: INSERT contains ON CONFLICT (message_id) DO NOTHING.
- Global caller (PLATFORM_ADMIN) → ValidationError on every method.
- Missing conversation → NotFoundError (CONVERSATION_NOT_FOUND).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.errors import NotFoundError, ValidationError

from api.conversation_store.repository import (
    append_message,
    create_conversation,
    get_conversation,
    get_messages,
)


class _RecordingDatabase:
    """Database double that records SQL + params and returns canned rows."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()
        self.all_sql: list[str] = []
        self.all_params: list[tuple[Any, ...]] = []
        self._rows = rows or []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        self.all_sql.append(query)
        self.all_params.append(args)
        return self._rows[0] if self._rows else None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        self.all_sql.append(query)
        self.all_params.append(args)
        return self._rows

    async def execute(self, query: str, *args: Any) -> str:
        self.last_sql = query
        self.last_params = args
        self.all_sql.append(query)
        self.all_params.append(args)
        return "INSERT 1"

    async def close(self) -> None:
        pass


def _claims(tenant_id: str | None, role: Role, subject: str = "user-1") -> AuthClaims:
    return AuthClaims(subject=subject, role=role, tenant_id=tenant_id)


# -- create_conversation -------------------------------------------------------


async def test_create_conversation_inserts_with_callers_tenant_id() -> None:
    """create_conversation INSERT carries claims.tenant_id, not from any argument."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    conv_id = await create_conversation(db, claims, channel="widget")

    assert re.fullmatch(r"[0-9a-f]{32}", conv_id), f"Expected 32-char hex, got {conv_id}"
    assert "tenant_id" in db.last_sql
    # conversation_id is $1, tenant_id is $2
    assert db.last_params[1] == "tenant-a"


async def test_create_conversation_sets_visitor_id_from_subject_for_visitor() -> None:
    """VISITOR caller: visitor_id defaults to claims.subject."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.VISITOR, subject="visitor-xyz")

    await create_conversation(db, claims)

    # visitor_id should be bound in the INSERT params
    assert "visitor-xyz" in db.last_params


async def test_create_conversation_returns_active_status() -> None:
    """create_conversation INSERT includes status='active'."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await create_conversation(db, claims)

    assert "active" in db.last_sql


# -- get_conversation ----------------------------------------------------------


async def test_get_conversation_filters_by_tenant_id() -> None:
    """get_conversation SELECT binds WHERE tenant_id = caller's tenant."""
    row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    result = await get_conversation(db, claims, "conv-1")

    assert result is not None
    assert result.conversation_id == "conv-1"
    assert "tenant_id" in db.last_sql
    assert db.last_params[0] == "tenant-a"


async def test_get_conversation_visitor_scopes_by_visitor_id() -> None:
    """VISITOR caller: SELECT additionally binds visitor_id = $3 as the 3rd param."""
    row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": "visitor-xyz",
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.VISITOR, subject="visitor-xyz")

    result = await get_conversation(db, claims, "conv-1")

    assert result is not None
    assert "visitor_id = $3" in db.last_sql
    assert db.last_params == ("tenant-a", "conv-1", "visitor-xyz")


async def test_get_conversation_client_admin_does_not_scope_visitor_id() -> None:
    """CLIENT_ADMIN caller: SELECT does NOT bind visitor_id filter."""
    row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": "visitor-xyz",
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    result = await get_conversation(db, claims, "conv-1")

    assert result is not None
    # visitor_id may appear in SELECT columns but not in WHERE clause
    assert "visitor_id =" not in db.last_sql


async def test_get_conversation_not_found_returns_none() -> None:
    """Missing conversation → None."""
    db = _RecordingDatabase(rows=[])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    result = await get_conversation(db, claims, "nonexistent")

    assert result is None


# -- get_messages --------------------------------------------------------------


async def test_get_messages_filters_by_tenant_and_conversation() -> None:
    """get_messages SELECT binds tenant_id + conversation_id."""
    now = datetime.now(UTC)
    rows = [
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
    db = _RecordingDatabase(rows=rows)
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    messages = await get_messages(db, claims, "conv-1")

    assert len(messages) == 1
    assert messages[0].message_id == "msg-1"
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert "tenant_id" in db.last_sql
    assert "conversation_id" in db.last_sql
    assert db.last_params[0] == "tenant-a"
    assert db.last_params[1] == "conv-1"


async def test_get_messages_visitor_scopes_by_visitor_id() -> None:
    """get_messages: VISITOR caller binds visitor_id = $3 as the 3rd param."""
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": "visitor-xyz",
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[conv_row])
    claims = _claims("tenant-a", Role.VISITOR, subject="visitor-xyz")

    # We need the visibility check to pass first, then get_messages does fetch
    # For simplicity, test the visibility check SQL directly
    from api.conversation_store.repository import _verify_conversation_visible

    await _verify_conversation_visible(db, claims, "conv-1")

    assert "visitor_id = $3" in db.last_sql
    assert db.last_params == ("tenant-a", "conv-1", "visitor-xyz")


async def test_get_messages_not_visible_raises_not_found() -> None:
    """get_messages: if conversation not visible to caller → NotFoundError."""
    db = _RecordingDatabase(rows=[])  # No conversation row
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    with pytest.raises(NotFoundError) as exc_info:
        await get_messages(db, claims, "conv-other")

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"


# -- append_message ------------------------------------------------------------


async def test_append_message_inserts_with_tenant_id() -> None:
    """append_message INSERT carries claims.tenant_id."""
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[conv_row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    msg_id = await append_message(db, claims, "conv-1", role="user", content="Hello")

    assert re.fullmatch(r"[0-9a-f]{32}", msg_id), f"Expected 32-char hex, got {msg_id}"
    assert "tenant_id" in db.last_sql
    # message_id is $1, tenant_id is $2
    assert db.last_params[1] == "tenant-a"


async def test_append_message_idempotent_with_supplied_id() -> None:
    """append_message with message_id: INSERT contains ON CONFLICT (message_id) DO NOTHING."""
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": None,
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[conv_row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    msg_id = await append_message(
        db, claims, "conv-1", role="user", content="Hello", message_id="m-1",
    )

    assert msg_id == "m-1"
    assert "ON CONFLICT" in db.last_sql.upper()
    assert "message_id" in db.last_sql


async def test_append_message_not_visible_raises_not_found() -> None:
    """append_message: if conversation not visible to caller → NotFoundError."""
    db = _RecordingDatabase(rows=[])  # No conversation row
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    with pytest.raises(NotFoundError) as exc_info:
        await append_message(db, claims, "conv-other", role="user", content="Hello")

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"


async def test_append_message_visitor_scopes_by_visitor_id() -> None:
    """append_message: VISITOR caller's visibility check binds visitor_id = $3."""
    conv_row = {
        "conversation_id": "conv-1",
        "status": "active",
        "channel": "widget",
        "visitor_id": "visitor-xyz",
        "started_at": datetime.now(UTC),
        "ended_at": None,
        "metadata": {},
    }
    db = _RecordingDatabase(rows=[conv_row])
    claims = _claims("tenant-a", Role.VISITOR, subject="visitor-xyz")

    await append_message(db, claims, "conv-1", role="user", content="Hello")

    # The visibility check (fetchrow) is the first SQL call
    assert "visitor_id = $3" in db.all_sql[0]
    assert db.all_params[0] == ("tenant-a", "conv-1", "visitor-xyz")


# -- PLATFORM_ADMIN rejected ---------------------------------------------------


async def test_platform_admin_rejected_on_create() -> None:
    """PLATFORM_ADMIN (tenant_id=None) → ValidationError on create_conversation."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await create_conversation(db, claims)


async def test_platform_admin_rejected_on_get() -> None:
    """PLATFORM_ADMIN → ValidationError on get_conversation."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await get_conversation(db, claims, "conv-1")


async def test_platform_admin_rejected_on_get_messages() -> None:
    """PLATFORM_ADMIN → ValidationError on get_messages."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await get_messages(db, claims, "conv-1")


async def test_platform_admin_rejected_on_append() -> None:
    """PLATFORM_ADMIN → ValidationError on append_message."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await append_message(db, claims, "conv-1", role="user", content="Hello")
