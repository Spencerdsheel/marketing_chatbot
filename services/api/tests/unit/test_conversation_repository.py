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
    get_window,
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
    """append_message with message_id: INSERT contains the composite ON CONFLICT
    target (tenant_id, conversation_id, message_id) DO NOTHING, scoping
    idempotency to the conversation (not globally across tenants/conversations)."""
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
    assert "ON CONFLICT (tenant_id, conversation_id, message_id) DO NOTHING" in db.last_sql


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


# -- get_window ----------------------------------------------------------------


def _msg_row(message_id: str, role: str, content: str, tokens: int | None, ts: datetime) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "role": role,
        "content": content,
        "intent": None,
        "confidence": None,
        "tokens": tokens,
        "created_at": ts,
    }


async def test_get_window_limit_returns_last_n_chronological() -> None:
    """get_window(limit=3) returns 3 messages oldest→newest."""
    now = datetime.now(UTC)
    rows = [
        _msg_row("m5", "user", "five", None, now),
        _msg_row("m4", "bot", "four", None, now),
        _msg_row("m3", "user", "three", None, now),
    ]
    db = _RecordingDatabase(rows=rows)
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    msgs = await get_window(db, claims, "conv-1", limit=3)

    assert len(msgs) == 3
    # Reversed from newest-first → oldest→newest
    assert msgs[0].content == "three"
    assert msgs[1].content == "four"
    assert msgs[2].content == "five"
    # Assert ORDER BY ... DESC ... LIMIT $3
    assert "ORDER BY created_at DESC, message_id DESC" in db.last_sql
    assert "LIMIT $3" in db.last_sql


async def test_get_window_visitor_param_numbering() -> None:
    """VISITOR get_window(limit=2): visitor_id = $3 AND LIMIT $4."""
    now = datetime.now(UTC)
    rows = [
        _msg_row("m2", "bot", "two", None, now),
        _msg_row("m1", "user", "one", None, now),
    ]
    db = _RecordingDatabase(rows=rows)
    claims = _claims("tenant-a", Role.VISITOR, subject="visitor-xyz")

    msgs = await get_window(db, claims, "conv-1", limit=2)

    assert len(msgs) == 2
    assert "visitor_id = $3" in db.last_sql
    assert "LIMIT $4" in db.last_sql
    assert db.last_params == ("tenant-a", "conv-1", "visitor-xyz", 2)


async def test_get_window_token_budget_with_stored_tokens() -> None:
    """token_budget includes messages that fit, newest-first, ≥1 always."""
    now = datetime.now(UTC)
    # newest first: m5(20tok), m4(15tok), m3(10tok), m2(5tok), m1(3tok)
    rows = [
        _msg_row("m5", "user", "five", 20, now),
        _msg_row("m4", "bot", "four", 15, now),
        _msg_row("m3", "user", "three", 10, now),
        _msg_row("m2", "bot", "two", 5, now),
        _msg_row("m1", "user", "one", 3, now),
    ]
    db = _RecordingDatabase(rows=rows)
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    # Budget 18: m5(20) exceeds alone → return just m5 (≥1 rule)
    msgs = await get_window(db, claims, "conv-1", token_budget=18)
    assert len(msgs) == 1
    assert msgs[0].message_id == "m5"

    # Budget 30: m5(20)+m4(15)=35 > 30, so just m5
    msgs = await get_window(db, claims, "conv-1", token_budget=30)
    assert len(msgs) == 1
    assert msgs[0].message_id == "m5"

    # Budget 35: m5(20)+m4(15)=35 fits → return [m4, m5] chronological
    msgs = await get_window(db, claims, "conv-1", token_budget=35)
    assert len(msgs) == 2
    assert msgs[0].message_id == "m4"
    assert msgs[1].message_id == "m5"


async def test_get_window_token_budget_null_tokens_estimate() -> None:
    """token_budget with tokens=None uses len(content)//4 estimate."""
    now = datetime.now(UTC)
    # "hello world" = 11 chars → 11//4 = 2 tokens
    # "short" = 5 chars → 5//4 = 1 token
    rows = [
        _msg_row("m2", "user", "hello world", None, now),  # est 2
        _msg_row("m1", "bot", "short", None, now),  # est 1
    ]
    db = _RecordingDatabase(rows=rows)
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    # Budget 1: m2(est 2) exceeds → return just m2 (≥1 rule)
    msgs = await get_window(db, claims, "conv-1", token_budget=1)
    assert len(msgs) == 1
    assert msgs[0].message_id == "m2"

    # Budget 3: m2(2)+m1(1)=3 fits → return [m1, m2] chronological
    msgs = await get_window(db, claims, "conv-1", token_budget=3)
    assert len(msgs) == 2
    assert msgs[0].message_id == "m1"
    assert msgs[1].message_id == "m2"


async def test_get_window_exactly_one_mode_validation() -> None:
    """Neither or both → ValidationError INVALID_WINDOW_ARGS."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    with pytest.raises(ValidationError) as exc_info:
        await get_window(db, claims, "conv-1")
    assert exc_info.value.code == "INVALID_WINDOW_ARGS"

    with pytest.raises(ValidationError) as exc_info:
        await get_window(db, claims, "conv-1", limit=2, token_budget=10)
    assert exc_info.value.code == "INVALID_WINDOW_ARGS"


async def test_get_window_invalid_limit_or_budget() -> None:
    """limit=0 or negative → ValidationError."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    with pytest.raises(ValidationError) as exc_info:
        await get_window(db, claims, "conv-1", limit=0)
    assert exc_info.value.code == "INVALID_WINDOW_ARGS"

    with pytest.raises(ValidationError) as exc_info:
        await get_window(db, claims, "conv-1", limit=-1)
    assert exc_info.value.code == "INVALID_WINDOW_ARGS"

    with pytest.raises(ValidationError) as exc_info:
        await get_window(db, claims, "conv-1", token_budget=0)
    assert exc_info.value.code == "INVALID_WINDOW_ARGS"


async def test_get_window_not_visible_raises_not_found() -> None:
    """get_window: if conversation not visible → NotFoundError."""
    db = _RecordingDatabase(rows=[])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    with pytest.raises(NotFoundError) as exc_info:
        await get_window(db, claims, "conv-other", limit=5)
    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"


async def test_get_window_global_caller_rejected() -> None:
    """PLATFORM_ADMIN → ValidationError on get_window."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await get_window(db, claims, "conv-1", limit=5)
