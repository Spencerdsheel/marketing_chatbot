"""CalendarProvider Protocol + Busy/CalendarRef/CalendarEvent + impls (S8.2).

``CalendarProvider`` is a ``typing.Protocol`` with two implementations this
sprint: ``StubCalendarProvider`` (config-driven, deterministic -- dev/live
testable without a real Google account) and ``GoogleCalendarProvider`` (raw
httpx against Google Calendar API v3; no google client library dependency).
``update_event`` is declared on the Protocol for the future (reschedule/
cancel sync) but is NOT wired by any route this sprint -- both impls raise
``NotImplementedError``.

``calendar_provider_for`` selects an implementation from a tenant's decrypted
``CalendarConfig`` (``api.scheduling.calendar_config_repository``). An
unknown ``provider`` value is a deterministic configuration error --
``CalendarConfigError`` (a ``ValidationError``) -- raised before any network
call, mirroring ``api.crm.sync.crm_sync_for``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from common.auth import AuthClaims
from common.errors import ValidationError

from api.scheduling.calendar_config_repository import CalendarConfig

_GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


@dataclass(frozen=True)
class Busy:
    """A single busy interval on a calendar, UTC."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarRef:
    """The result of a successful ``CalendarProvider.create_event`` call."""

    provider: str
    external_id: str


@dataclass(frozen=True)
class CalendarEvent:
    """The booking payload passed to ``CalendarProvider.create_event``."""

    event_id: str
    starts_at: datetime
    ends_at: datetime
    timezone: str


class CalendarProvider(Protocol):
    """Outbound calendar sync contract. Implementations are selected per tenant."""

    async def free_busy(
        self, claims: AuthClaims, window: tuple[datetime, datetime]
    ) -> list[Busy]: ...

    async def create_event(self, claims: AuthClaims, event: CalendarEvent) -> CalendarRef: ...

    async def update_event(
        self, claims: AuthClaims, ref: CalendarRef, event: CalendarEvent
    ) -> None: ...


class CalendarConfigError(ValidationError):
    """Deterministic calendar config error -- raised before any network call."""

    code = "CALENDAR_CONFIG_ERROR"


class StubCalendarProvider:
    """``CalendarProvider`` implementation: config-driven, deterministic.

    ``free_busy`` returns the tenant's configured ``busy`` intervals verbatim
    (S8.2 decision 1) -- no network I/O, fully dev/live-testable without a
    real calendar account. ``create_event`` returns a fake, deterministic
    ``CalendarRef`` derived from the booking's ``event_id``.
    """

    def __init__(self, *, calendar_id: str, busy: list[dict[str, object]]) -> None:
        self._calendar_id = calendar_id
        self._busy = busy

    async def free_busy(
        self, claims: AuthClaims, window: tuple[datetime, datetime]
    ) -> list[Busy]:
        return [
            Busy(
                start=datetime.fromisoformat(str(interval["start"])),
                end=datetime.fromisoformat(str(interval["end"])),
            )
            for interval in self._busy
        ]

    async def create_event(self, claims: AuthClaims, event: CalendarEvent) -> CalendarRef:
        return CalendarRef(provider="stub", external_id=f"stub-{event.event_id}")

    async def update_event(
        self, claims: AuthClaims, ref: CalendarRef, event: CalendarEvent
    ) -> None:
        raise NotImplementedError("StubCalendarProvider.update_event is not wired this sprint")


class GoogleCalendarProvider:
    """``CalendarProvider`` implementation: Google Calendar API v3 via raw httpx.

    Uses a decrypted, already-acquired OAuth access token
    (``Authorization: Bearer <token>``) -- the OAuth consent/refresh dance is
    out of scope for S8.2. Non-2xx responses and network errors raise (the
    caller -- the booking route -- surfaces this as ``CALENDAR_SYNC_FAILED``
    with compensation; the slots route degrades to native slots).
    """

    def __init__(self, *, calendar_id: str, access_token: str, timeout: float) -> None:
        self._calendar_id = calendar_id
        self._access_token = access_token
        self._timeout = timeout

    async def free_busy(
        self, claims: AuthClaims, window: tuple[datetime, datetime]
    ) -> list[Busy]:
        window_start, window_end = window
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    f"{_GOOGLE_CALENDAR_API_BASE}/freeBusy",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    json={
                        "timeMin": window_start.isoformat(),
                        "timeMax": window_end.isoformat(),
                        "items": [{"id": self._calendar_id}],
                    },
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Google freeBusy.query request failed: {exc}") from exc

        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"Google freeBusy.query returned non-2xx status: {response.status_code}"
            )

        data = response.json()
        busy_intervals = data.get("calendars", {}).get(self._calendar_id, {}).get("busy", [])
        return [
            Busy(
                start=datetime.fromisoformat(str(interval["start"])),
                end=datetime.fromisoformat(str(interval["end"])),
            )
            for interval in busy_intervals
        ]

    async def create_event(self, claims: AuthClaims, event: CalendarEvent) -> CalendarRef:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    f"{_GOOGLE_CALENDAR_API_BASE}/calendars/{self._calendar_id}/events",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    json={
                        "start": {"dateTime": event.starts_at.isoformat()},
                        "end": {"dateTime": event.ends_at.isoformat()},
                        "summary": "Scheduled call",
                    },
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Google events.insert request failed: {exc}") from exc

        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"Google events.insert returned non-2xx status: {response.status_code}"
            )

        data = response.json()
        return CalendarRef(provider="google", external_id=str(data["id"]))

    async def update_event(
        self, claims: AuthClaims, ref: CalendarRef, event: CalendarEvent
    ) -> None:
        raise NotImplementedError("GoogleCalendarProvider.update_event is not wired this sprint")


def calendar_provider_for(config: CalendarConfig, *, timeout: float) -> CalendarProvider:
    """Select a ``CalendarProvider`` implementation for the tenant's config.

    Raises ``CalendarConfigError`` (a ``ValidationError``) for an unknown
    ``provider`` value -- deterministic, never retried, never a network call.
    """
    if config.provider == "stub":
        return StubCalendarProvider(
            calendar_id=config.calendar_id or "stub", busy=config.busy
        )

    if config.provider == "google":
        return GoogleCalendarProvider(
            calendar_id=config.calendar_id or "primary",
            access_token=config.credentials,
            timeout=timeout,
        )

    raise CalendarConfigError(
        f"Unsupported calendar provider: {config.provider!r}.",
        code="CALENDAR_PROVIDER_NOT_SUPPORTED",
    )
