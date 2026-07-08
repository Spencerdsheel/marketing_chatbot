"""Unit tests for api.auth.repository.

Covers:
- get_user_by_id returns the full row for an existing user id.
- get_user_by_id returns None for an unknown id.
- The SQL uses a positional placeholder ($1), not named params.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _StubDatabase:
    """In-memory stub database for testing auth repository."""

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    def seed_user(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        email: str = "agent@example.com",
        role: str = "CLIENT_AGENT",
        active: bool = True,
        name: str = "Agent Smith",
    ) -> None:
        self._users[user_id] = {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "role": role,
            "password_hash": "hashed",
            "name": name,
            "active": active,
            "last_login_at": None,
        }

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        q = query.strip().upper()
        if "FROM USERS" in q and "WHERE ID" in q:
            user_id = args[0]
            return self._users.get(user_id)
        return None


async def test_get_user_by_id_returns_row() -> None:
    from api.auth.repository import get_user_by_id

    db = _StubDatabase()
    db.seed_user(user_id="agent-1", tenant_id="tenant-abc", role="CLIENT_AGENT")

    row = await get_user_by_id(db, "agent-1")

    assert row is not None
    assert row["id"] == "agent-1"
    assert row["tenant_id"] == "tenant-abc"
    assert row["role"] == "CLIENT_AGENT"
    assert row["active"] is True


async def test_get_user_by_id_returns_none_if_missing() -> None:
    from api.auth.repository import get_user_by_id

    db = _StubDatabase()

    row = await get_user_by_id(db, "nonexistent")

    assert row is None


async def test_get_user_by_id_uses_positional_placeholder() -> None:
    from api.auth.repository import get_user_by_id

    db = _StubDatabase()
    db.seed_user(user_id="agent-1", tenant_id="tenant-abc")

    await get_user_by_id(db, "agent-1")

    query, args = db.fetchrow_calls[0]
    assert "$1" in query
    assert ":" not in query
    assert args[0] == "agent-1"
