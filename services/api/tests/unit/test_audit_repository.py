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
from api.auth.dependencies import PlatformAdminActor


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


# -- actor_context (S12.7 D4) ---------------------------------------------------


async def test_record_audit_actor_context_adds_platform_admin_marker() -> None:
    """actor_context set -> metadata gains platform_admin=True + role, actor
    stays claims.subject (the real platform admin's own id, unchanged)."""
    db = _RecordingDatabase()
    # The derived, tenant-scoped claims resolve_tenant_scope would build for
    # a platform admin reaching tenant X -- role=CLIENT_ADMIN, subject=the
    # real platform admin's own id.
    claims = _claims("tenant-x", Role.CLIENT_ADMIN, subject="pa-real-id")
    actor_context = PlatformAdminActor(subject="pa-real-id", role=Role.PLATFORM_ADMIN)

    await record_audit(
        db, claims,
        action="tenant_bot_settings_updated",
        actor_context=actor_context,
    )

    # metadata is the 7th positional param (index 6).
    metadata = db.last_params[6]
    assert metadata["platform_admin"] is True
    assert metadata["platform_admin_role"] == "PLATFORM_ADMIN"
    # actor (index 2) is unaffected -- still the real platform admin subject.
    assert db.last_params[2] == "pa-real-id"


async def test_record_audit_actor_context_merges_with_existing_metadata() -> None:
    """actor_context does not clobber caller-supplied metadata keys."""
    db = _RecordingDatabase()
    claims = _claims("tenant-x", Role.CLIENT_ADMIN, subject="pa-real-id")
    actor_context = PlatformAdminActor(subject="pa-real-id", role=Role.PLATFORM_ADMIN)

    await record_audit(
        db, claims,
        action="lead_stage_transitioned",
        metadata={"from_stage": "captured", "to_stage": "qualified"},
        actor_context=actor_context,
    )

    metadata = db.last_params[6]
    assert metadata["from_stage"] == "captured"
    assert metadata["to_stage"] == "qualified"
    assert metadata["platform_admin"] is True


async def test_record_audit_no_actor_context_no_marker() -> None:
    """A normal CLIENT_ADMIN write (no actor_context) -- metadata unchanged,
    no platform_admin key added."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN, subject="real-admin-1")

    await record_audit(db, claims, action="tenant_bot_settings_updated")

    metadata = db.last_params[6]
    assert metadata is None
