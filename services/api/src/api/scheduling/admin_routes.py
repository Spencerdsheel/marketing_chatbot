"""Admin scheduling routes -- PUT /admin/schedule/availability (CLIENT_ADMIN only).

Sets a tenant's availability rules + IANA timezone (S8.1 decision 1).
``CLIENT_AGENT``/``VISITOR`` are forbidden (403) -- availability is
configuration, not review, and per CLAUDE.md RBAC CLIENT_AGENT cannot change
config. An invalid IANA timezone or malformed rules shape is rejected with
422 before anything is persisted.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from common.auth import AuthClaims, Role
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from api.auth.dependencies import require_roles
from api.scheduling.calendar_config_repository import upsert_calendar_config
from api.scheduling.repository import upsert_availability

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/schedule", tags=["scheduling"])

_WEEKDAY_KEYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class RulesPayload(BaseModel):
    """The ``rules`` jsonb shape (S8.1 decision 1)."""

    slot_minutes: int = Field(gt=0)
    buffer_minutes: int = Field(ge=0)
    weekly_hours: dict[str, list[list[str]]]

    @field_validator("weekly_hours")
    @classmethod
    def _validate_weekly_hours(
        cls, v: dict[str, list[list[str]]]
    ) -> dict[str, list[list[str]]]:
        unknown = set(v.keys()) - _WEEKDAY_KEYS
        if unknown:
            raise ValueError(f"weekly_hours has unknown weekday keys: {sorted(unknown)}")
        for windows in v.values():
            for window in windows:
                if len(window) != 2:
                    raise ValueError("each weekly_hours window must be [start, end]")
                start, end = window
                if not _HHMM_RE.match(start) or not _HHMM_RE.match(end):
                    raise ValueError("weekly_hours times must be 24h HH:MM")
                if start >= end:
                    raise ValueError("weekly_hours window start must be before end")
        return v


class AvailabilityUpsertRequest(BaseModel):
    """Body for PUT /admin/schedule/availability."""

    timezone: str
    rules: RulesPayload

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as exc:
            raise ValueError(f"invalid IANA timezone: {v}") from exc
        return v


class AvailabilityResponse(BaseModel):
    """Leak-free (no tenant_id) availability for the admin surface."""

    timezone: str
    rules: dict[str, Any]
    updated_at: datetime


@router.put("/availability")
async def put_availability(
    body: AvailabilityUpsertRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> AvailabilityResponse:
    """Set the caller's tenant availability. ``CLIENT_ADMIN`` only.

    Invalid timezone/rules are rejected by ``AvailabilityUpsertRequest``
    validation before this handler runs (422, nothing persisted).
    """
    db = request.app.state.db

    availability = await upsert_availability(
        db, claims, timezone=body.timezone, rules=body.rules.model_dump()
    )

    return AvailabilityResponse(
        timezone=availability.timezone,
        rules=availability.rules,
        updated_at=availability.updated_at,
    )


class BusyIntervalPayload(BaseModel):
    """A single ``StubCalendarProvider``-consumed busy interval (dev/test only)."""

    start: str
    end: str


class CalendarConfigRequest(BaseModel):
    """Body for PUT /admin/schedule/calendar."""

    provider: str
    calendar_id: str | None = None
    credentials: str
    enabled: bool = False
    busy: list[BusyIntervalPayload] = Field(default_factory=list)
    # SR-6: the tenant's Calendly hosted-scheduling page (link-out target).
    # Only meaningful for provider="calendly"; not a secret.
    scheduling_url: str | None = None


class CalendarConfigResponse(BaseModel):
    """Leak-free (no credentials) response for PUT /admin/schedule/calendar."""

    provider: str
    calendar_id: str | None
    enabled: bool
    # scheduling_url is NOT a secret (SR-6) -- safe to echo, unlike credentials.
    scheduling_url: str | None = None


@router.put("/calendar")
async def put_calendar_config(
    body: CalendarConfigRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> CalendarConfigResponse:
    """Set the calling tenant's calendar provider + credentials. ``CLIENT_ADMIN`` only.

    The OAuth access token / ``StubCalendarProvider`` secret is encrypted at
    rest (AES-256-GCM via ``SecretBox``) and never echoed back in the response
    (S8.2 decision 2).
    """
    await upsert_calendar_config(
        request.app.state.db,
        claims,
        provider=body.provider,
        calendar_id=body.calendar_id,
        credentials=body.credentials,
        busy=[interval.model_dump() for interval in body.busy],
        enabled=body.enabled,
        scheduling_url=body.scheduling_url,
    )

    _log.info(
        "calendar config updated",
        extra={
            "event": "calendar_config_set",
            "provider": body.provider,
            "tenant_id": claims.tenant_id,
            "enabled": body.enabled,
        },
    )

    return CalendarConfigResponse(
        provider=body.provider,
        calendar_id=body.calendar_id,
        enabled=body.enabled,
        scheduling_url=body.scheduling_url,
    )
