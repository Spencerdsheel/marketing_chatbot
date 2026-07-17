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

S12.7 (platform-admin super-user, D4): ``record_audit`` accepts an optional
``actor_context`` -- the ``api.auth.dependencies.PlatformAdminActor`` a
tenant-explicit-route caller stashes on ``request.state.platform_admin_actor``
when a PLATFORM_ADMIN reached tenant X via ``resolve_tenant_scope``. When
present, the row's ``metadata`` gains ``platform_admin: true`` and
``platform_admin_role`` -- an honest, invisible-to-the-operator marker that a
super-user (not tenant X's own admin) made this change. ``actor`` is left
UNCHANGED (``claims.subject`` -- already the real platform admin's own id,
because ``resolve_tenant_scope`` preserves the real ``subject`` on the
derived claims; D1's "no JWT/identity mutation" carries through for free).
For a normal ``CLIENT_ADMIN`` write, ``actor_context`` is ``None`` and no
marker is added -- behavior is byte-for-byte unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError

if TYPE_CHECKING:
    from api.auth.dependencies import PlatformAdminActor


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
    actor_context: PlatformAdminActor | None = None,
) -> str:
    """Insert a new ``audit_events`` row.

    Returns the ``event_id`` (uuid4().hex). The ``metadata`` dict is stored
    as jsonb (the default codec handles dict→jsonb conversion).

    ``actor_context`` (S12.7 D4): when the caller is a platform admin acting
    on a tenant-explicit route, pass the ``PlatformAdminActor`` stashed on
    ``request.state.platform_admin_actor``. The row's ``metadata`` then gains
    ``platform_admin: true`` and ``platform_admin_role`` -- merged in without
    overwriting any keys the caller already supplied. ``actor`` stays
    ``claims.subject`` either way (already the real actor id).
    """
    _reject_global(claims)

    new_event_id = uuid4().hex
    row_metadata: dict[str, Any] | None = metadata
    if actor_context is not None:
        row_metadata = {**(metadata or {}), "platform_admin": True,
                         "platform_admin_role": actor_context.role.value}

    params: list[Any] = [
        claims.tenant_id,
        new_event_id,
        claims.subject,  # actor
        action,
        target_type,
        target_id,
        row_metadata,  # jsonb
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
