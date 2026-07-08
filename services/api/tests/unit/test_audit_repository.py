"""Unit tests for the audit repository.

Covers:
- record_audit issues a tenant-scoped INSERT (positional params, metadata bound,
  event_id uuid4, actor=claims.subject).
- list_audit tenant-scoped + ORDER BY created_at DESC + limit clamped.
- Cross-tenant isolation (tenant A's list_audit never returns tenant B's rows).
- Global caller (tenant_id=None) → ValidationError for both methods.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

from api.audit.repository import (
    list_audit,
    record_audit,
)


class _RecordingDatabase:
    """Database double that records SQL + params and returns canned rows."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()
        self._rows = rows or []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return self._rows[0] if self._rows else None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        return self._rows

    async def execute(self, query: str, *args: Any) -> str:
        self.last_sql = query
        self.last_params = args
        return "INSERT 1"

    async def close(self) -> None:
        pass


def _claims(tenant_id: str | None, role: Role, subject: str = "user-1") -> AuthClaims:
    return AuthClaims(subject=subject, role=role, tenant_id=tenant_id)


# -- record_audit --------------------------------------------------------------


async def test_record_audit_inserts_with_callers_tenant_id() -> None:
    """record_audit INSERT carries claims.tenant_id, not from any argument."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    event_id = await record_audit(
        db, claims,
        action="auth.login",
        target_type="user",
        target_id="user-1",
        metadata={"ip": "10.0.0.1"},
    )

    assert re.fullmatch(r"[0-9a-f]{32}", event_id), f"Expected 32-char hex, got {event_id}"
    assert "tenant_id" in db.last_sql
    # tenant_id is $1
    assert db.last_params[0] == "tenant-a"


async def test_record_audit_binds_actor_as_subject() -> None:
    """record_audit stores actor=claims.subject."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN, subject="admin-42")

    await record_audit(db, claims, action="auth.login")

    assert "admin-42" in db.last_params


async def test_record_audit_binds_metadata_as_param() -> None:
    """record_audit binds metadata dict as a parameter (jsonb)."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)
    meta = {"key": "value"}

    await record_audit(db, claims, action="test.action", metadata=meta)

    assert meta in db.last_params


async def test_record_audit_allows_null_metadata() -> None:
    """record_audit works with metadata=None."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    event_id = await record_audit(db, claims, action="test.action")

    assert re.fullmatch(r"[0-9a-f]{32}", event_id)


# -- list_audit ----------------------------------------------------------------


async def test_list_audit_filters_by_tenant_id() -> None:
    """list_audit SELECT binds WHERE tenant_id = caller's tenant."""
    now = datetime.now(UTC)
    row = {
        "event_id": "evt-1",
        "actor": "user-1",
        "action": "auth.login",
        "target_type": "user",
        "target_id": "user-1",
        "metadata": {},
        "created_at": now,
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    events = await list_audit(db, claims, limit=10, offset=0)

    assert len(events) == 1
    assert events[0].event_id == "evt-1"
    assert events[0].action == "auth.login"
    assert "tenant_id" in db.last_sql
    assert db.last_params[0] == "tenant-a"


async def test_list_audit_orders_by_created_at_desc() -> None:
    """list_audit SELECT includes ORDER BY created_at DESC."""
    db = _RecordingDatabase(rows=[])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await list_audit(db, claims, limit=10, offset=0)

    assert "ORDER BY created_at DESC" in db.last_sql


async def test_list_audit_clamps_limit() -> None:
    """list_audit clamps limit to [1, 200]."""
    db = _RecordingDatabase(rows=[])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    # limit=0 → clamped to 1
    await list_audit(db, claims, limit=0, offset=0)
    assert db.last_params[1] == 1

    # limit=500 → clamped to 200
    await list_audit(db, claims, limit=500, offset=0)
    assert db.last_params[1] == 200

    # limit=-5 → clamped to 1
    await list_audit(db, claims, limit=-5, offset=0)
    assert db.last_params[1] == 1


async def test_list_audit_respects_offset() -> None:
    """list_audit passes offset as a param."""
    db = _RecordingDatabase(rows=[])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await list_audit(db, claims, limit=10, offset=25)

    assert db.last_params[2] == 25


# -- Cross-tenant isolation ----------------------------------------------------


async def test_tenant_a_cannot_read_tenant_b_audit_rows() -> None:
    """Tenant A's list_audit → SELECT bound to A's id; tenant B's rows never returned."""
    db = _RecordingDatabase(rows=[])  # No rows for tenant A
    claims_a = _claims("tenant-a", Role.CLIENT_ADMIN)

    events = await list_audit(db, claims_a, limit=10, offset=0)

    assert events == []
    assert db.last_params[0] == "tenant-a"


# -- Global caller rejected ----------------------------------------------------


async def test_platform_admin_rejected_on_record() -> None:
    """PLATFORM_ADMIN (tenant_id=None) → ValidationError on record_audit."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await record_audit(db, claims, action="auth.login")


async def test_platform_admin_rejected_on_list() -> None:
    """PLATFORM_ADMIN (tenant_id=None) → ValidationError on list_audit."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await list_audit(db, claims, limit=10, offset=0)
