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
