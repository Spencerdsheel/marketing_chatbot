"""Audit repository — tenant-scoped async SQL for the audit trail.

Every method:
- Takes ``AuthClaims`` as its first positional argument.
- Calls ``_reject_global(claims)`` to reject PLATFORM_ADMIN (no global scope).
- Uses positional placeholders numbered by position (``$1``, ``$2``, …).
- Never returns or accepts ``tenant_id`` in its public return types; that is
  an internal filter only.

Data model (migration 0017):
- ``audit_events(tenant_id PK, event_id PK, actor, action, target_type,
  target_id, metadata jsonb, created_at)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError


@dataclass(frozen=True)
class AuditEvent:
    """A single audit event row."""

    event_id: str
    actor: str | None
    action: str
    target_type: str | None
    target_id: str | None
    metadata: dict[str, Any] | None
    created_at: datetime


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Audit is always tenant-scoped; a global caller has no tenant_id
    and therefore cannot be filtered to a tenant's rows.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Audit repository is tenant-scoped; PLATFORM_ADMIN callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def record_audit(
    db: Database,
    claims: AuthClaims,
    *,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Insert a new ``audit_events`` row.

    Returns the ``event_id`` (uuid4().hex). The ``metadata`` dict is stored
    as jsonb (the default codec handles dict→jsonb conversion).
    """
    _reject_global(claims)

    new_event_id = uuid4().hex
    params: list[Any] = [
        claims.tenant_id,
        new_event_id,
        claims.subject,  # actor
        action,
        target_type,
        target_id,
        metadata,  # jsonb
    ]
    await db.execute(
        "INSERT INTO audit_events "
        "(tenant_id, event_id, actor, action, target_type, target_id, metadata) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        *params,
    )
    return new_event_id


async def list_audit(
    db: Database,
    claims: AuthClaims,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Fetch audit events for the caller's tenant, newest first.

    ``limit`` is clamped to ``[1, 200]``.
    """
    _reject_global(claims)

    clamped_limit = max(1, min(limit, 200))

    rows = await db.fetch(
        "SELECT event_id, actor, action, target_type, target_id, metadata, "
        "created_at "
        "FROM audit_events "
        "WHERE tenant_id = $1 "
        "ORDER BY created_at DESC "
        "LIMIT $2 OFFSET $3",
        claims.tenant_id,
        clamped_limit,
        offset,
    )
    return [_row_to_event(row) for row in rows]


def _row_to_event(row: Any) -> AuditEvent:
    return AuditEvent(
        event_id=str(row["event_id"]),
        actor=row["actor"],
        action=str(row["action"]),
        target_type=row["target_type"],
        target_id=row["target_id"],
        metadata=row["metadata"],
        created_at=row["created_at"],
    )
