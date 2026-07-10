"""Visitor-authenticated scheduling routes -- open slots + native booking.

``GET /public/schedule/slots`` is read-only: it returns the tenant's open
slots (availability rules minus already-booked events), or ``[]`` if no
availability is configured (S8.1 decision 6 -- no silent fallback, but an
empty/unconfigured tenant is not an error).

``POST /public/schedule/book`` is consent-gated (GDPR) and re-validates the
requested start is an actually-open slot immediately before inserting, on top
of the DB-enforced partial-unique-index no-double-booking guard
(``api.scheduling.repository.create_event``). ``tenant_id``/``visitor_id``
always come from the visitor session (``get_visitor_claims``), never the
request body. The response is leak-free -- no ``tenant_id``/``visitor_id``.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from common.auth import AuthClaims
from common.errors import ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, field_validator

from api.config import ApiSettings, get_api_settings
from api.gateway.dependencies import get_visitor_claims
from api.scheduling.calendar import CalendarEvent, calendar_provider_for
from api.scheduling.calendar_config_repository import get_calendar_config
from api.scheduling.reminder_repository import create_reminder_jobs
from api.scheduling.repository import (
    Availability,
    create_event,
    delete_event,
    get_availability,
    list_booked,
    update_event_calendar_ref,
)
from api.scheduling.slots import Slot, compute_slots

_log = get_logger(__name__)

router = APIRouter(prefix="/public/schedule", tags=["scheduling"])


class SlotResponse(BaseModel):
    """A single open slot, UTC."""

    starts_at: datetime
    ends_at: datetime


class ConsentPayload(BaseModel):
    """Consent metadata provided by the visitor."""

    granted: bool
    purpose: str
    text: str


class BookRequest(BaseModel):
    """Body for POST /public/schedule/book."""

    starts_at: datetime
    timezone: str
    consent: ConsentPayload | None = None
    lead_id: str | None = None

    @field_validator("starts_at")
    @classmethod
    def _require_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("starts_at must be timezone-aware (UTC ISO 8601)")
        return v

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as exc:
            raise ValueError(f"invalid IANA timezone: {v}") from exc
        return v


class BookResponse(BaseModel):
    """Leak-free (no tenant_id/visitor_id) response for POST /public/schedule/book."""

    event_id: str
    starts_at: datetime
    ends_at: datetime
    status: str


def _resolve_window(
    settings: ApiSettings, date_from: date | None, date_to: date | None
) -> tuple[date, date]:
    """Resolve the query window, defaulting per S8.1 decision 2/6."""
    today = datetime.now(UTC).date()
    start = date_from or today
    end = date_to or (start + timedelta(days=settings.schedule_slot_window_days - 1))
    return start, end


def _day_bounds_utc(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC bounds for the local calendar day ``day`` in ``zone``."""
    start = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
    end = (datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(days=1)).astimezone(UTC)
    return start, end


async def _open_slots_for_window(
    db: object,
    claims: AuthClaims,
    availability: Availability,
    date_from: date,
    date_to: date,
    *,
    window_max_days: int,
    extra_busy: list[tuple[datetime, datetime]] | None = None,
) -> list[Slot]:
    zone = ZoneInfo(availability.timezone)
    window_start_utc, _ = _day_bounds_utc(date_from, zone)
    _, window_end_utc = _day_bounds_utc(date_to, zone)

    booked = await list_booked(
        db,  # type: ignore[arg-type]
        claims,
        window_start=window_start_utc,
        window_end=window_end_utc,
    )
    if extra_busy:
        booked = booked + extra_busy

    return compute_slots(
        availability.rules,
        availability.timezone,
        date_from,
        date_to,
        booked,
        now=datetime.now(UTC),
        window_max_days=window_max_days,
    )


async def _calendar_busy_for_window(
    db: object,
    claims: AuthClaims,
    window_start: datetime,
    window_end: datetime,
    settings: ApiSettings,
) -> list[tuple[datetime, datetime]]:
    """Best-effort free-busy fetch (S8.2 decision 3).

    No calendar configured (or configured but disabled) -> ``[]``, native
    slots exactly as S8.1. A provider error (config or network) does NOT fail
    the request -- it is logged as ``calendar_freebusy_degraded`` (warning)
    and native slots are returned; the authoritative double-booking check
    happens at commit (decision 4), not here.
    """
    calendar_config = await get_calendar_config(db, claims)  # type: ignore[arg-type]
    if calendar_config is None or not calendar_config.enabled:
        return []

    try:
        provider = calendar_provider_for(
            calendar_config, timeout=settings.calendar_http_timeout_seconds
        )
        busy = await provider.free_busy(claims, (window_start, window_end))
    except Exception:
        _log.warning(
            "calendar free-busy degraded to native slots",
            extra={
                "event": "calendar_freebusy_degraded",
                "tenant_id": claims.tenant_id,
                "provider": calendar_config.provider,
            },
        )
        return []

    return [(b.start, b.end) for b in busy]


@router.get("/slots")
async def get_slots(
    request: Request,
    date_from: date | None = Query(default=None),  # noqa: B008
    date_to: date | None = Query(default=None),  # noqa: B008
    claims: AuthClaims = Depends(get_visitor_claims),  # noqa: B008
) -> list[SlotResponse]:
    """Return the caller's tenant open slots for ``[date_from, date_to]``.

    Defaults/caps per ``schedule_slot_window_days``/``schedule_slot_window_max_days``.
    No availability configured -> ``[]`` (200, not an error -- S8.1 decision 6).
    """
    db = request.app.state.db
    settings = get_api_settings()

    availability = await get_availability(db, claims)
    if availability is None:
        return []

    start, end = _resolve_window(settings, date_from, date_to)

    zone = ZoneInfo(availability.timezone)
    window_start_utc, _ = _day_bounds_utc(start, zone)
    _, window_end_utc = _day_bounds_utc(end, zone)
    extra_busy = await _calendar_busy_for_window(
        db, claims, window_start_utc, window_end_utc, settings
    )

    slots = await _open_slots_for_window(
        db, claims, availability, start, end,
        window_max_days=settings.schedule_slot_window_max_days,
        extra_busy=extra_busy,
    )

    return [SlotResponse(starts_at=s.starts_at, ends_at=s.ends_at) for s in slots]


@router.post("/book", status_code=201)
async def book_slot(
    body: BookRequest,
    request: Request,
    claims: AuthClaims = Depends(get_visitor_claims),  # noqa: B008
) -> BookResponse:
    """Book an open slot for the caller's tenant.

    Consent gate (GDPR): ``consent.granted != True`` -> 422 ``CONSENT_REQUIRED``,
    nothing stored. Re-validates ``starts_at`` is an actually-open slot
    (recomputed for that local day) before inserting -> else 422
    ``SLOT_UNAVAILABLE``. The insert itself is additionally protected by the
    DB partial unique index (``create_event`` catches the race). ``tenant_id``/
    ``visitor_id`` come from the visitor session, never the body.
    """
    if body.consent is None or body.consent.granted is not True:
        raise ValidationError(
            "Consent to store contact information is required.",
            code="CONSENT_REQUIRED",
        )

    db = request.app.state.db
    settings = get_api_settings()

    availability = await get_availability(db, claims)
    if availability is None:
        raise ValidationError(
            "The requested time is no longer available.", code="SLOT_UNAVAILABLE"
        )

    zone = ZoneInfo(availability.timezone)
    starts_at_utc = body.starts_at.astimezone(UTC)
    local_date = starts_at_utc.astimezone(zone).date()

    open_slots = await _open_slots_for_window(
        db, claims, availability, local_date, local_date,
        window_max_days=settings.schedule_slot_window_max_days,
    )
    matching = next((s for s in open_slots if s.starts_at == starts_at_utc), None)
    if matching is None:
        raise ValidationError(
            "The requested time is no longer available.", code="SLOT_UNAVAILABLE"
        )

    consent_with_timestamp = {
        "granted": body.consent.granted,
        "purpose": body.consent.purpose,
        "text": body.consent.text,
        "captured_at": datetime.now(UTC).isoformat(),
    }

    event = await create_event(
        db,
        claims,
        starts_at=matching.starts_at,
        ends_at=matching.ends_at,
        timezone=body.timezone,
        visitor_id=claims.subject,
        lead_id=body.lead_id,
        consent=consent_with_timestamp,
    )

    _log.info(
        "schedule event booked",
        extra={
            "event": "schedule_event_booked",
            "event_id": event.event_id,
            "tenant_id": claims.tenant_id,
        },
    )

    # Create the 3 reminder rows (3d/24h/1h) immediately after the booking
    # insert and before calendar sync (S8.3 decision 1) -- so an S8.2
    # CALENDAR_SYNC_FAILED compensation (delete_event below) cascades them
    # away via the reminder_jobs FK, leaving no orphaned reminder rows.
    await create_reminder_jobs(
        db, claims, event_id=event.event_id, starts_at=event.starts_at, now=datetime.now(UTC)
    )

    calendar_config = await get_calendar_config(db, claims)
    if calendar_config is not None and calendar_config.enabled:
        try:
            provider = calendar_provider_for(
                calendar_config, timeout=settings.calendar_http_timeout_seconds
            )
            ref = await provider.create_event(
                claims,
                CalendarEvent(
                    event_id=event.event_id,
                    starts_at=event.starts_at,
                    ends_at=event.ends_at,
                    timezone=event.timezone,
                ),
            )
        except Exception as exc:
            # Never leave a booked row without its calendar event when a
            # calendar is enabled (S8.2 decision 4) -- compensate + fail loud.
            await delete_event(db, claims, event.event_id)
            _log.warning(
                "calendar sync failed, booking compensated",
                extra={
                    "event": "calendar_sync_failed",
                    "event_id": event.event_id,
                    "tenant_id": claims.tenant_id,
                    "provider": calendar_config.provider,
                },
            )
            raise ValidationError(
                "Failed to sync the booking to the calendar. Please try again.",
                code="CALENDAR_SYNC_FAILED",
            ) from exc

        calendar_ref = f"{ref.provider}:{ref.external_id}"
        await update_event_calendar_ref(db, claims, event.event_id, calendar_ref)

    return BookResponse(
        event_id=event.event_id,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        status=event.status,
    )
