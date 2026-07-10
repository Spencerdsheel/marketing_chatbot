"""Unit tests for api.scheduling.calendar (CalendarProvider Protocol + impls).

Covers:
- StubCalendarProvider.free_busy returns the configured intervals verbatim.
- StubCalendarProvider.create_event returns a deterministic CalendarRef.
- StubCalendarProvider.update_event raises NotImplementedError (not wired
  this sprint).
- GoogleCalendarProvider.free_busy parses a mocked freeBusy.query response
  into a Busy list and sends Authorization: Bearer <token>.
- GoogleCalendarProvider.create_event POSTs events.insert and maps the
  response id -> CalendarRef.
- GoogleCalendarProvider non-2xx / network error -> raises.
- calendar_provider_for: unknown provider -> deterministic CalendarConfigError
  (a ValidationError), no network call.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from common.errors import ValidationError

from api.scheduling.calendar import (
    Busy,
    CalendarConfigError,
    CalendarEvent,
    CalendarRef,
    GoogleCalendarProvider,
    StubCalendarProvider,
    calendar_provider_for,
)
from api.scheduling.calendar_config_repository import CalendarConfig

_WINDOW = (
    datetime(2026, 7, 15, 0, 0, tzinfo=UTC),
    datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
)


class _StubTransport(httpx.AsyncBaseTransport):
    """httpx transport double that records the request and returns a canned response."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        json_body: dict[str, Any] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.json_body = json_body or {}
        self.raise_exc = raise_exc
        self.captured_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        if self.raise_exc is not None:
            raise self.raise_exc
        return httpx.Response(
            status_code=self.status_code, json=self.json_body, request=request
        )


async def _post_via_stub(monkeypatch: pytest.MonkeyPatch, transport: _StubTransport) -> None:
    """Patch httpx.AsyncClient construction inside api.scheduling.calendar."""
    import api.scheduling.calendar as calendar_mod

    original_client = httpx.AsyncClient

    def _client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return original_client(transport=transport, timeout=5.0)

    monkeypatch.setattr(calendar_mod.httpx, "AsyncClient", _client_factory)


# ==============================================================================
# StubCalendarProvider
# ==============================================================================


async def test_stub_free_busy_returns_configured_intervals() -> None:
    provider = StubCalendarProvider(
        calendar_id="dev",
        busy=[
            {"start": "2026-07-15T14:00:00+00:00", "end": "2026-07-15T14:30:00+00:00"},
        ],
    )

    result = await provider.free_busy(None, _WINDOW)  # type: ignore[arg-type]

    assert result == [
        Busy(
            start=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
            end=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        )
    ]


async def test_stub_free_busy_empty_config_returns_empty_list() -> None:
    provider = StubCalendarProvider(calendar_id="dev", busy=[])

    result = await provider.free_busy(None, _WINDOW)  # type: ignore[arg-type]

    assert result == []


async def test_stub_create_event_returns_deterministic_calendar_ref() -> None:
    provider = StubCalendarProvider(calendar_id="dev", busy=[])
    event = CalendarEvent(
        event_id="evt-1",
        starts_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        timezone="UTC",
    )

    ref = await provider.create_event(None, event)  # type: ignore[arg-type]

    assert isinstance(ref, CalendarRef)
    assert ref.provider == "stub"
    assert ref.external_id == "stub-evt-1"


async def test_stub_update_event_raises_not_implemented() -> None:
    provider = StubCalendarProvider(calendar_id="dev", busy=[])
    ref = CalendarRef(provider="stub", external_id="stub-evt-1")
    event = CalendarEvent(
        event_id="evt-1",
        starts_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        timezone="UTC",
    )

    with pytest.raises(NotImplementedError):
        await provider.update_event(None, ref, event)  # type: ignore[arg-type]


# ==============================================================================
# GoogleCalendarProvider
# ==============================================================================


async def test_google_free_busy_parses_response_and_sends_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _StubTransport(
        status_code=200,
        json_body={
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-07-15T14:00:00Z", "end": "2026-07-15T14:30:00Z"},
                    ]
                }
            }
        },
    )
    await _post_via_stub(monkeypatch, transport)

    provider = GoogleCalendarProvider(
        calendar_id="primary", access_token="tok-abc123", timeout=5.0
    )

    result = await provider.free_busy(None, _WINDOW)  # type: ignore[arg-type]

    assert len(result) == 1
    assert result[0].start == datetime.fromisoformat("2026-07-15T14:00:00+00:00")

    assert transport.captured_request is not None
    auth_header = transport.captured_request.headers.get("authorization")
    assert auth_header == "Bearer tok-abc123"
    assert "freeBusy" in str(transport.captured_request.url)


async def test_google_free_busy_non_2xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(status_code=500)
    await _post_via_stub(monkeypatch, transport)

    provider = GoogleCalendarProvider(calendar_id="primary", access_token="tok", timeout=5.0)

    with pytest.raises(Exception):  # noqa: B017 -- surfaces as CALENDAR_SYNC_FAILED at the route
        await provider.free_busy(None, _WINDOW)  # type: ignore[arg-type]


async def test_google_free_busy_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(raise_exc=httpx.ConnectError("boom"))
    await _post_via_stub(monkeypatch, transport)

    provider = GoogleCalendarProvider(calendar_id="primary", access_token="tok", timeout=5.0)

    with pytest.raises(Exception):  # noqa: B017
        await provider.free_busy(None, _WINDOW)  # type: ignore[arg-type]


async def test_google_create_event_posts_and_maps_id(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(status_code=200, json_body={"id": "google-evt-999"})
    await _post_via_stub(monkeypatch, transport)

    provider = GoogleCalendarProvider(
        calendar_id="primary", access_token="tok-xyz", timeout=5.0
    )
    event = CalendarEvent(
        event_id="evt-1",
        starts_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        timezone="UTC",
    )

    ref = await provider.create_event(None, event)  # type: ignore[arg-type]

    assert ref == CalendarRef(provider="google", external_id="google-evt-999")
    assert transport.captured_request is not None
    auth_header = transport.captured_request.headers.get("authorization")
    assert auth_header == "Bearer tok-xyz"
    assert "/calendars/primary/events" in str(transport.captured_request.url)


async def test_google_create_event_non_2xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(status_code=503)
    await _post_via_stub(monkeypatch, transport)

    provider = GoogleCalendarProvider(calendar_id="primary", access_token="tok", timeout=5.0)
    event = CalendarEvent(
        event_id="evt-1",
        starts_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        timezone="UTC",
    )

    with pytest.raises(Exception):  # noqa: B017
        await provider.create_event(None, event)  # type: ignore[arg-type]


async def test_google_update_event_raises_not_implemented() -> None:
    provider = GoogleCalendarProvider(calendar_id="primary", access_token="tok", timeout=5.0)
    ref = CalendarRef(provider="google", external_id="google-evt-999")
    event = CalendarEvent(
        event_id="evt-1",
        starts_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 15, 14, 30, tzinfo=UTC),
        timezone="UTC",
    )

    with pytest.raises(NotImplementedError):
        await provider.update_event(None, ref, event)  # type: ignore[arg-type]


# ==============================================================================
# calendar_provider_for
# ==============================================================================


def test_calendar_provider_for_stub_returns_stub_provider() -> None:
    config = CalendarConfig(
        provider="stub", calendar_id="dev", credentials="tok", busy=[], enabled=True
    )
    provider = calendar_provider_for(config, timeout=5.0)
    assert isinstance(provider, StubCalendarProvider)


def test_calendar_provider_for_google_returns_google_provider() -> None:
    config = CalendarConfig(
        provider="google", calendar_id="primary", credentials="tok", busy=[], enabled=True
    )
    provider = calendar_provider_for(config, timeout=5.0)
    assert isinstance(provider, GoogleCalendarProvider)


def test_calendar_provider_for_unknown_provider_raises_deterministic_error() -> None:
    config = CalendarConfig(
        provider="outlook", calendar_id=None, credentials="tok", busy=[], enabled=True
    )
    with pytest.raises(ValidationError):
        calendar_provider_for(config, timeout=5.0)

    with pytest.raises(CalendarConfigError):
        calendar_provider_for(config, timeout=5.0)
