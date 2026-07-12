"""Leads repository — tenant-scoped async SQL for visitor lead capture.

Every method:
- Takes ``AuthClaims`` as its first positional argument.
- Calls ``_reject_global(claims)`` to reject PLATFORM_ADMIN (no global scope).
- Uses positional placeholders numbered by position (``$1``, ``$2``, …).
- Never returns or accepts ``tenant_id`` in its public return types; that is
  an internal filter only.

Data model (migration 0014):
- ``leads(tenant_id PK, lead_id PK, visitor_id, name, email, phone, status,
  stage, qualification_score, consent jsonb, assigned_agent_id, source,
  created_at, updated_at)``.
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
class Lead:
    """A single captured lead row."""

    lead_id: str
    visitor_id: str | None
    name: str
    email: str
    phone: str | None
    status: str
    stage: str
    qualification_score: int | None
    consent: dict[str, Any]
    assigned_agent_id: str | None
    source: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LeadActivity:
    """A single append-only timeline event for a lead."""

    activity_id: str
    lead_id: str
    type: str
    payload: dict[str, Any] | None
    actor: str | None
    created_at: datetime


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Lead capture is always tenant-scoped; a global caller has no tenant_id
    and therefore cannot be filtered to a tenant's rows.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Lead repository is tenant-scoped; PLATFORM_ADMIN callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def create_lead(
    db: Database,
    claims: AuthClaims,
    *,
    visitor_id: str,
    name: str,
    email: str,
    phone: str | None,
    consent: dict[str, Any],
    source: str,
) -> str:
    """Insert a new ``leads`` row with ``status='new'``, ``stage='captured'``.

    Returns the ``lead_id`` (uuid4().hex). The ``consent`` dict is stored as
    jsonb (the default codec handles dict→jsonb conversion).
    """
    _reject_global(claims)

    new_lead_id = uuid4().hex
    params: list[Any] = [
        claims.tenant_id,
        new_lead_id,
        visitor_id,
        name,
        email,
        phone,
        "new",  # status (default)
        "captured",  # stage (default)
        None,  # qualification_score (NULL)
        consent,  # jsonb
        None,  # assigned_agent_id (NULL)
        source,
    ]
    await db.execute(
        "INSERT INTO leads "
        "(tenant_id, lead_id, visitor_id, name, email, phone, status, stage, "
        " qualification_score, consent, assigned_agent_id, source) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        *params,
    )
    return new_lead_id


async def get_lead(
    db: Database,
    claims: AuthClaims,
    lead_id: str,
) -> Lead | None:
    """Fetch a lead by ``lead_id`` scoped to the caller's tenant, or ``None``."""
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT lead_id, visitor_id, name, email, phone, status, stage, "
        "qualification_score, consent, assigned_agent_id, source, "
        "created_at, updated_at "
        "FROM leads "
        "WHERE tenant_id = $1 AND lead_id = $2",
        claims.tenant_id,
        lead_id,
    )
    return _row_to_lead(row) if row is not None else None


async def get_lead_email_by_visitor_id(
    db: Database,
    claims: AuthClaims,
    visitor_id: str,
) -> str | None:
    """Fetch the most-recent lead's email for a visitor, tenant-scoped.

    Used by ``api.notifications.recipients.resolve_event_recipient`` (S9.2,
    Scope §7) when a scheduled event has no ``lead_id`` but does have a
    ``visitor_id`` -- an anonymous booking that later (or earlier) captured a
    lead. Returns ``None`` if no lead exists for that visitor in this tenant.
    """
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT email FROM leads "
        "WHERE tenant_id = $1 AND visitor_id = $2 "
        "ORDER BY created_at DESC LIMIT 1",
        claims.tenant_id,
        visitor_id,
    )
    return str(row["email"]) if row is not None else None


async def update_lead_stage(
    db: Database,
    claims: AuthClaims,
    lead_id: str,
    *,
    stage: str,
    status: str,
    qualification_score: int,
) -> Lead | None:
    """Update a lead's ``stage``/``status``/``qualification_score``, tenant-scoped.

    ``status`` and ``qualification_score`` must already be derived (see
    ``api.leads.pipeline``) -- this method persists them as-is; it does not
    validate the transition itself.

    Returns the updated ``Lead``, or ``None`` if no row matched (missing
    ``lead_id`` or cross-tenant access -- callers cannot distinguish the two,
    which is the point: no cross-tenant existence leak).
    """
    _reject_global(claims)

    result = await db.execute(
        "UPDATE leads SET stage = $1, status = $2, qualification_score = $3, "
        "updated_at = now() "
        "WHERE tenant_id = $4 AND lead_id = $5",
        stage,
        status,
        qualification_score,
        claims.tenant_id,
        lead_id,
    )
    if _rows_affected(result) == 0:
        return None

    return await get_lead(db, claims, lead_id)


async def add_activity(
    db: Database,
    claims: AuthClaims,
    lead_id: str,
    *,
    type: str,
    payload: dict[str, Any] | None,
    actor: str,
) -> str:
    """Append a timeline event for a lead. Returns the new ``activity_id``.

    Tenant-scoped INSERT; ``payload`` is bound as jsonb (default codec).
    This does not verify the lead exists -- callers (routes) are expected to
    have already resolved the lead via ``get_lead`` before appending.
    """
    _reject_global(claims)

    new_activity_id = uuid4().hex
    await db.execute(
        "INSERT INTO lead_activities "
        "(tenant_id, activity_id, lead_id, type, payload, actor) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        claims.tenant_id,
        new_activity_id,
        lead_id,
        type,
        payload,
        actor,
    )
    return new_activity_id


async def list_activities(
    db: Database,
    claims: AuthClaims,
    lead_id: str,
) -> list[LeadActivity]:
    """Fetch a lead's timeline, tenant-scoped, newest first."""
    _reject_global(claims)

    rows = await db.fetch(
        "SELECT activity_id, lead_id, type, payload, actor, created_at "
        "FROM lead_activities "
        "WHERE tenant_id = $1 AND lead_id = $2 "
        "ORDER BY created_at DESC",
        claims.tenant_id,
        lead_id,
    )
    return [_row_to_activity(row) for row in rows]


async def assign_lead(
    db: Database,
    claims: AuthClaims,
    lead_id: str,
    *,
    agent_id: str,
) -> Lead | None:
    """Assign a lead to an agent, tenant-scoped.

    Persists ``assigned_agent_id`` as-is -- callers (routes) are expected to
    have already validated the assignee via ``auth.repository.get_user_by_id``
    before calling this. Returns the updated ``Lead``, or ``None`` if no row
    matched (missing ``lead_id`` or cross-tenant access).
    """
    _reject_global(claims)

    result = await db.execute(
        "UPDATE leads SET assigned_agent_id = $1, updated_at = now() "
        "WHERE tenant_id = $2 AND lead_id = $3",
        agent_id,
        claims.tenant_id,
        lead_id,
    )
    if _rows_affected(result) == 0:
        return None

    return await get_lead(db, claims, lead_id)


async def list_leads_for_export(
    db: Database,
    claims: AuthClaims,
) -> list[Lead]:
    """Fetch all of the caller's tenant leads, newest first, for CSV export.

    Tenant-scoped (S7.4 decision 5) -- other tenants' leads are never
    returned. Raises ``ValidationError`` for global callers (PLATFORM_ADMIN).
    """
    _reject_global(claims)

    rows = await db.fetch(
        "SELECT lead_id, visitor_id, name, email, phone, status, stage, "
        "qualification_score, consent, assigned_agent_id, source, "
        "created_at, updated_at "
        "FROM leads "
        "WHERE tenant_id = $1 "
        "ORDER BY created_at DESC",
        claims.tenant_id,
    )
    return [_row_to_lead(row) for row in rows]


def _rows_affected(command_tag: str) -> int:
    """Parse the row count from an asyncpg-style command tag (e.g. 'UPDATE 1')."""
    parts = command_tag.strip().split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_lead(row: Any) -> Lead:
    return Lead(
        lead_id=str(row["lead_id"]),
        visitor_id=row["visitor_id"],
        name=str(row["name"]),
        email=str(row["email"]),
        phone=row["phone"],
        status=str(row["status"]),
        stage=str(row["stage"]),
        qualification_score=row["qualification_score"],
        consent=row["consent"],
        assigned_agent_id=row["assigned_agent_id"],
        source=str(row["source"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_activity(row: Any) -> LeadActivity:
    return LeadActivity(
        activity_id=str(row["activity_id"]),
        lead_id=str(row["lead_id"]),
        type=str(row["type"]),
        payload=row["payload"],
        actor=row["actor"],
        created_at=row["created_at"],
    )
