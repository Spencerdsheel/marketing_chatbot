"""Scheduling repository — tenant-scoped async SQL for availability + booking.

Every method:
- Takes ``AuthClaims`` as its first positional argument.
- Calls ``_reject_global(claims)`` to reject PLATFORM_ADMIN (no global scope).
- Uses positional placeholders numbered by position (``$1``, ``$2``, …).
- Never returns or accepts ``tenant_id`` in its public return types; that is
  an internal filter only.

Data model (migration 0018):
- ``availability(tenant_id PK, timezone, rules jsonb, updated_at)`` — one row
  per tenant, upserted via ``ON CONFLICT``.
- ``schedule_events(tenant_id, event_id, lead_id, visitor_id, starts_at,
  ends_at, timezone, status, calendar_ref, consent jsonb, created_at)`` —
  composite PK ``(tenant_id, event_id)``. A partial unique index on
  ``(tenant_id, starts_at) WHERE status = 'booked'`` is the DB-enforced
  no-double-booking guard (S8.1 decision 4); ``create_event`` catches the
  resulting ``asyncpg.UniqueViolationError`` and raises ``ValidationError``
  code ``SLOT_UNAVAILABLE``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import asyncpg
from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError


@dataclass(frozen=True)
class Availability:
    """A tenant's availability rules + timezone."""

    timezone: str
    rules: dict[str, Any]
    updated_at: datetime


@dataclass(frozen=True)
class EventContact:
    """A single event's contact-resolution fields (S9.2, Scope §6).

    Used by ``api.notifications.recipients.resolve_event_recipient`` --
    intentionally narrow (no consent/calendar_ref) since it exists only to
    resolve an outbound recipient.
    """

    lead_id: str | None
    visitor_id: str | None
    timezone: str
    starts_at: datetime
    status: str


@dataclass(frozen=True)
class ScheduleEvent:
    """A single booked/cancelled/completed/no-show call."""

    event_id: str
    lead_id: str | None
    visitor_id: str | None
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: str
    calendar_ref: str | None
    consent: dict[str, Any]
    created_at: datetime


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Scheduling is always tenant-scoped; a global caller has no tenant_id and
    therefore cannot be filtered to a tenant's rows.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Scheduling repository is tenant-scoped; PLATFORM_ADMIN callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def get_availability(db: Database, claims: AuthClaims) -> Availability | None:
    """Fetch the caller's tenant availability, or ``None`` if unset."""
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT timezone, rules, updated_at FROM availability WHERE tenant_id = $1",
        claims.tenant_id,
    )
    return _row_to_availability(row) if row is not None else None


async def upsert_availability(
    db: Database,
    claims: AuthClaims,
    *,
    timezone: str,
    rules: dict[str, Any],
) -> Availability:
    """Insert or update the caller's tenant availability. Returns the stored row.

    ``rules`` is bound as jsonb (the default codec handles dict<->jsonb).
    """
    _reject_global(claims)

    await db.execute(
        "INSERT INTO availability (tenant_id, timezone, rules, updated_at) "
        "VALUES ($1, $2, $3, now()) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "timezone = EXCLUDED.timezone, rules = EXCLUDED.rules, updated_at = now()",
        claims.tenant_id,
        timezone,
        rules,
    )

    result = await get_availability(db, claims)
    assert result is not None  # noqa: S101  # we just wrote the row
    return result


async def list_booked(
    db: Database,
    claims: AuthClaims,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Fetch ``(starts_at, ends_at)`` for the tenant's ``status='booked'``
    events whose ``starts_at`` falls within ``[window_start, window_end]``.
    """
    _reject_global(claims)

    rows = await db.fetch(
        "SELECT starts_at, ends_at FROM schedule_events "
        "WHERE tenant_id = $1 AND status = 'booked' "
        "AND starts_at >= $2 AND starts_at <= $3 "
        "ORDER BY starts_at",
        claims.tenant_id,
        window_start,
        window_end,
    )
    return [(row["starts_at"], row["ends_at"]) for row in rows]


async def create_event(
    db: Database,
    claims: AuthClaims,
    *,
    starts_at: datetime,
    ends_at: datetime,
    timezone: str,
    visitor_id: str | None,
    lead_id: str | None,
    consent: dict[str, Any],
) -> ScheduleEvent:
    """Insert a new ``schedule_events`` row with ``status='booked'``.

    Returns the created ``ScheduleEvent`` (``event_id = uuid4().hex``,
    ``calendar_ref = None`` — S8.2 wires calendar sync). If the partial
    unique index ``schedule_events_no_double_book`` rejects the insert
    (``asyncpg.UniqueViolationError``, i.e. the tenant already has a booked
    event at this ``starts_at``), raises ``ValidationError`` code
    ``SLOT_UNAVAILABLE`` — nothing is persisted.
    """
    _reject_global(claims)

    new_event_id = uuid4().hex
    try:
        await db.execute(
            "INSERT INTO schedule_events "
            "(tenant_id, event_id, lead_id, visitor_id, starts_at, ends_at, "
            " timezone, status, calendar_ref, consent) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            claims.tenant_id,
            new_event_id,
            lead_id,
            visitor_id,
            starts_at,
            ends_at,
            timezone,
            "booked",
            None,  # calendar_ref (S8.2)
            consent,
        )
    except asyncpg.UniqueViolationError as exc:
        raise ValidationError(
            "The requested time is no longer available.",
            code="SLOT_UNAVAILABLE",
        ) from exc

    # The DB stamps created_at server-side via DEFAULT now(); populate the
    # returned object without a round-trip SELECT.
    return ScheduleEvent(
        event_id=new_event_id,
        lead_id=lead_id,
        visitor_id=visitor_id,
        starts_at=starts_at,
        ends_at=ends_at,
        timezone=timezone,
        status="booked",
        calendar_ref=None,
        consent=consent,
        created_at=datetime.now(UTC),
    )


async def update_event_calendar_ref(
    db: Database,
    claims: AuthClaims,
    event_id: str,
    calendar_ref: str,
) -> None:
    """Persist a ``CalendarProvider.create_event`` result onto a booked event.

    Called after a successful calendar sync (S8.2 decision 4). Tenant-scoped
    -- the ``WHERE`` clause filters by ``tenant_id`` so this can never touch
    another tenant's row even if ``event_id`` were guessed.
    """
    _reject_global(claims)

    await db.execute(
        "UPDATE schedule_events SET calendar_ref = $3 "
        "WHERE tenant_id = $1 AND event_id = $2",
        claims.tenant_id,
        event_id,
        calendar_ref,
    )


async def delete_event(db: Database, claims: AuthClaims, event_id: str) -> None:
    """Delete a ``schedule_events`` row.

    Compensation for a calendar sync failure right after ``create_event``
    (S8.2 decision 4) -- never leaves an orphaned booked row without its
    calendar event when a calendar is enabled. Tenant-scoped.
    """
    _reject_global(claims)

    await db.execute(
        "DELETE FROM schedule_events WHERE tenant_id = $1 AND event_id = $2",
        claims.tenant_id,
        event_id,
    )


async def get_event_contact(
    db: Database, claims: AuthClaims, event_id: str
) -> EventContact | None:
    """Fetch a single event's contact-resolution fields, tenant-scoped.

    Used by ``api.notifications.recipients.resolve_event_recipient`` (S9.2,
    Decision 3) -- never exposes ``calendar_ref``/``consent``. Returns
    ``None`` if the event is missing or belongs to another tenant.
    """
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT lead_id, visitor_id, timezone, starts_at, status "
        "FROM schedule_events WHERE tenant_id = $1 AND event_id = $2",
        claims.tenant_id,
        event_id,
    )
    if row is None:
        return None
    return EventContact(
        lead_id=row["lead_id"],
        visitor_id=row["visitor_id"],
        timezone=str(row["timezone"]),
        starts_at=row["starts_at"],
        status=str(row["status"]),
    )


def _row_to_availability(row: Any) -> Availability:
    return Availability(
        timezone=str(row["timezone"]),
        rules=row["rules"],
        updated_at=row["updated_at"],
    )
