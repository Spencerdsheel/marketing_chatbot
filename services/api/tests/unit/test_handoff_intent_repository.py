"""Unit tests for api.scheduling.handoff_intent_repository (SR-6).

Covers:
- create_handoff_intent: tenant-scoped INSERT, _reject_global.
- find_handoff_visitor (MANDATORY): tenant isolation -- a same-email intent
  under a DIFFERENT tenant is NEVER returned; expired intents are never
  returned; the most-recent non-expired intent wins on a tie.
- The lookup SQL always binds tenant_id (a query missing the tenant
  predicate would fail these tests).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _claims(tenant_id: str = "tenant-abc", role: Role = Role.VISITOR) -> AuthClaims:
    return AuthClaims(subject="visitor-123", role=role, tenant_id=tenant_id)


class _StubDatabase:
    """In-memory stub database for the handoff-intent repository."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        q = query.strip().upper()
        if q.startswith("INSERT INTO CALENDLY_HANDOFF_INTENTS"):
            tenant_id, visitor_id, email, ttl_seconds = args
            created_at = _NOW
            self._rows.append(
                {
                    "tenant_id": tenant_id,
                    "visitor_id": visitor_id,
                    "email": email,
                    "created_at": created_at,
                    "expires_at": created_at + timedelta(seconds=ttl_seconds),
                }
            )
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        q = query.strip().upper()
        if "FROM CALENDLY_HANDOFF_INTENTS" in q:
            tenant_id, email, now = args
            matches = [
                row
                for row in self._rows
                if row["tenant_id"] == tenant_id
                and row["email"].lower() == email.lower()
                and row["expires_at"] > now
            ]
            if not matches:
                return None
            matches.sort(key=lambda r: r["created_at"], reverse=True)
            return matches[0]
        return None


@pytest.fixture
def stub_db() -> _StubDatabase:
    return _StubDatabase()


# ---------------------------------------------------------------------------
# create_handoff_intent
# ---------------------------------------------------------------------------


async def test_create_handoff_intent_inserts_tenant_scoped_row(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import create_handoff_intent

    claims = _claims(tenant_id="tenant-abc")
    await create_handoff_intent(
        stub_db, claims, visitor_id="visitor-123", email="a@example.com", ttl_seconds=3600
    )

    query, args = stub_db.execute_calls[-1]
    assert "calendly_handoff_intents" in query.lower()
    assert "$1" in query
    assert ":" not in query
    assert args[0] == "tenant-abc"
    assert args[1] == "visitor-123"
    assert args[2] == "a@example.com"


async def test_create_handoff_intent_rejects_global_caller(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import create_handoff_intent

    global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

    with pytest.raises(ValidationError):
        await create_handoff_intent(
            stub_db, global_claims, visitor_id="visitor-1", email="a@example.com", ttl_seconds=3600
        )
    assert stub_db.execute_calls == []


# ---------------------------------------------------------------------------
# find_handoff_visitor (MANDATORY tenant isolation)
# ---------------------------------------------------------------------------


async def test_find_handoff_visitor_returns_matching_visitor(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import (
        create_handoff_intent,
        find_handoff_visitor,
    )

    claims = _claims(tenant_id="tenant-abc")
    await create_handoff_intent(
        stub_db, claims, visitor_id="visitor-123", email="a@example.com", ttl_seconds=3600
    )

    result = await find_handoff_visitor(stub_db, "tenant-abc", "a@example.com", _NOW)

    assert result == "visitor-123"


async def test_find_handoff_visitor_case_insensitive_email(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import (
        create_handoff_intent,
        find_handoff_visitor,
    )

    claims = _claims(tenant_id="tenant-abc")
    await create_handoff_intent(
        stub_db, claims, visitor_id="visitor-123", email="A@Example.com", ttl_seconds=3600
    )

    result = await find_handoff_visitor(stub_db, "tenant-abc", "a@example.com", _NOW)

    assert result == "visitor-123"


async def test_find_handoff_visitor_tenant_isolation_mandatory(stub_db: _StubDatabase) -> None:
    """MANDATORY: a same-email intent under a DIFFERENT tenant is NEVER returned."""
    from api.scheduling.handoff_intent_repository import (
        create_handoff_intent,
        find_handoff_visitor,
    )

    claims_a = _claims(tenant_id="tenant-a")
    await create_handoff_intent(
        stub_db, claims_a, visitor_id="visitor-a", email="shared@example.com", ttl_seconds=3600
    )

    result = await find_handoff_visitor(stub_db, "tenant-b", "shared@example.com", _NOW)

    assert result is None


async def test_find_handoff_visitor_expired_intent_never_returned(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import (
        create_handoff_intent,
        find_handoff_visitor,
    )

    claims = _claims(tenant_id="tenant-abc")
    await create_handoff_intent(
        stub_db, claims, visitor_id="visitor-123", email="a@example.com", ttl_seconds=60
    )

    later = _NOW + timedelta(seconds=120)
    result = await find_handoff_visitor(stub_db, "tenant-abc", "a@example.com", later)

    assert result is None


async def test_find_handoff_visitor_most_recent_non_expired_wins(stub_db: _StubDatabase) -> None:
    """Two intents share an email -- the most-recent non-expired visitor_id wins."""
    from api.scheduling.handoff_intent_repository import find_handoff_visitor

    stub_db._rows = [
        {
            "tenant_id": "tenant-abc",
            "visitor_id": "visitor-old",
            "email": "a@example.com",
            "created_at": _NOW - timedelta(minutes=30),
            "expires_at": _NOW + timedelta(hours=1),
        },
        {
            "tenant_id": "tenant-abc",
            "visitor_id": "visitor-new",
            "email": "a@example.com",
            "created_at": _NOW - timedelta(minutes=5),
            "expires_at": _NOW + timedelta(hours=1),
        },
    ]

    result = await find_handoff_visitor(stub_db, "tenant-abc", "a@example.com", _NOW)

    assert result == "visitor-new"


async def test_find_handoff_visitor_no_match_returns_none(stub_db: _StubDatabase) -> None:
    from api.scheduling.handoff_intent_repository import find_handoff_visitor

    result = await find_handoff_visitor(stub_db, "tenant-abc", "nobody@example.com", _NOW)

    assert result is None


async def test_find_handoff_visitor_binds_tenant_id_predicate(stub_db: _StubDatabase) -> None:
    """The lookup SQL always binds tenant_id -- a query missing the tenant
    predicate would fail this test (regression guard for the mandatory
    isolation requirement)."""
    from api.scheduling.handoff_intent_repository import find_handoff_visitor

    await find_handoff_visitor(stub_db, "tenant-abc", "a@example.com", _NOW)

    query, args = stub_db.fetchrow_calls[-1]
    assert "tenant_id = $1" in query.lower()
    assert ":" not in query
    assert args[0] == "tenant-abc"
