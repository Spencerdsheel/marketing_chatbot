"""Unit tests for api.scheduling.repository.

Covers:
- upsert_availability / get_availability: tenant-scoped, rules+tz as jsonb/params.
- list_booked: tenant-scoped + windowed.
- create_event: tenant-scoped INSERT, uuid4().hex event_id.
- A simulated unique-violation (asyncpg.UniqueViolationError) on create_event ->
  ValidationError code SLOT_UNAVAILABLE.
- Cross-tenant isolation.
- Global caller (PLATFORM_ADMIN) -> ValidationError for every method.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import asyncpg
import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_RULES = {
    "slot_minutes": 30,
    "buffer_minutes": 0,
    "weekly_hours": {"mon": [["09:00", "17:00"]], "tue": [], "wed": [], "thu": [],
                      "fri": [], "sat": [], "sun": []},
}


def _reset_settings() -> None:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _claims(tenant_id: str = "tenant-abc", role: Role = Role.VISITOR) -> AuthClaims:
    return AuthClaims(subject="visitor-123", role=role, tenant_id=tenant_id)


class _StubDatabase:
    """In-memory stub database for testing the scheduling repository."""

    def __init__(self) -> None:
        self._availability: dict[str, dict[str, Any]] = {}
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        # When set, the next INSERT INTO schedule_events raises this exception.
        self.raise_on_insert_event: Exception | None = None

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        q = query.strip().upper()

        if q.startswith("INSERT INTO AVAILABILITY"):
            # args: tenant_id, timezone, rules
            tenant_id, timezone, rules = args
            self._availability[tenant_id] = {
                "tenant_id": tenant_id,
                "timezone": timezone,
                "rules": rules,
                "updated_at": _NOW,
            }
            return "INSERT 0 1"

        if q.startswith("INSERT INTO SCHEDULE_EVENTS"):
            if self.raise_on_insert_event is not None:
                exc = self.raise_on_insert_event
                self.raise_on_insert_event = None
                raise exc
            # args: tenant_id, event_id, lead_id, visitor_id, starts_at, ends_at,
            #       timezone, status, calendar_ref, consent
            (tenant_id, event_id, lead_id, visitor_id, starts_at, ends_at,
             timezone, status, calendar_ref, consent) = args
            key = (tenant_id, event_id)
            for (t_id, _e_id), existing in self._events.items():
                if (
                    t_id == tenant_id
                    and existing["starts_at"] == starts_at
                    and existing["status"] == "booked"
                    and status == "booked"
                ):
                    raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
            self._events[key] = {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "lead_id": lead_id,
                "visitor_id": visitor_id,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "timezone": timezone,
                "status": status,
                "calendar_ref": calendar_ref,
                "consent": consent,
                "created_at": _NOW,
            }
            return "INSERT 0 1"

        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        q = query.strip().upper()

        if "FROM AVAILABILITY" in q:
            tenant_id = args[0]
            return self._availability.get(tenant_id)

        if "FROM SCHEDULE_EVENTS" in q:
            tenant_id, event_id = args
            return self._events.get((tenant_id, event_id))

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        q = query.strip().upper()

        if "FROM SCHEDULE_EVENTS" in q:
            tenant_id = args[0]
            rows = [
                row
                for row in self._events.values()
                if row["tenant_id"] == tenant_id and row["status"] == "booked"
            ]
            if len(args) >= 3:
                window_start, window_end = args[1], args[2]
                rows = [r for r in rows if window_start <= r["starts_at"] <= window_end]
            rows.sort(key=lambda r: r["starts_at"])
            return rows

        return []


@pytest.fixture
def stub_db() -> _StubDatabase:
    return _StubDatabase()


# ---------------------------------------------------------------------------
# upsert_availability / get_availability
# ---------------------------------------------------------------------------


async def test_upsert_and_get_availability_round_trip(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import Availability, get_availability, upsert_availability

        claims = _claims(tenant_id="tenant-abc")

        result = await upsert_availability(stub_db, claims, timezone="America/New_York", rules=_RULES)
        assert isinstance(result, Availability)
        assert result.timezone == "America/New_York"
        assert result.rules == _RULES

        fetched = await get_availability(stub_db, claims)
        assert isinstance(fetched, Availability)
        assert fetched.timezone == "America/New_York"
        assert fetched.rules == _RULES


async def test_upsert_availability_uses_positional_placeholders(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import upsert_availability

        claims = _claims(tenant_id="tenant-abc")
        await upsert_availability(stub_db, claims, timezone="UTC", rules=_RULES)

        query, args = stub_db.execute_calls[-1]
        assert "$1" in query
        assert "$2" in query
        assert "$3" in query
        assert ":" not in query
        assert args[0] == "tenant-abc"


async def test_get_availability_returns_none_when_unset(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_availability

        claims = _claims(tenant_id="tenant-abc")
        result = await get_availability(stub_db, claims)

        assert result is None


async def test_availability_cross_tenant_isolation(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_availability, upsert_availability

        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        await upsert_availability(stub_db, claims_a, timezone="UTC", rules=_RULES)
        result = await get_availability(stub_db, claims_b)

        assert result is None


async def test_upsert_availability_rejects_global_caller(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import upsert_availability

        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await upsert_availability(stub_db, global_claims, timezone="UTC", rules=_RULES)


async def test_get_availability_rejects_global_caller(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_availability

        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await get_availability(stub_db, global_claims)


# ---------------------------------------------------------------------------
# list_booked
# ---------------------------------------------------------------------------


async def test_list_booked_tenant_scoped_and_windowed(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event, list_booked

        claims = _claims(tenant_id="tenant-abc")
        starts_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        await create_event(
            stub_db, claims,
            starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id=None,
            consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
        )

        booked = await list_booked(
            stub_db, claims,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 10, tzinfo=UTC),
        )

        assert booked == [(starts_at, ends_at)]


async def test_list_booked_excludes_outside_window(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event, list_booked

        claims = _claims(tenant_id="tenant-abc")
        starts_at = datetime(2026, 6, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        await create_event(
            stub_db, claims,
            starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id=None,
            consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
        )

        booked = await list_booked(
            stub_db, claims,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 10, tzinfo=UTC),
        )

        assert booked == []


async def test_list_booked_cross_tenant_isolation(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event, list_booked

        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")
        starts_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        await create_event(
            stub_db, claims_a,
            starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id=None,
            consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
        )

        booked = await list_booked(
            stub_db, claims_b,
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 10, tzinfo=UTC),
        )

        assert booked == []


async def test_list_booked_rejects_global_caller(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import list_booked

        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await list_booked(
                stub_db, global_claims,
                window_start=datetime(2026, 1, 1, tzinfo=UTC),
                window_end=datetime(2026, 1, 10, tzinfo=UTC),
            )


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


async def test_create_event_inserts_tenant_scoped_row_with_uuid_event_id(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import ScheduleEvent, create_event

        claims = _claims(tenant_id="tenant-abc")
        starts_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        consent = {"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"}

        event = await create_event(
            stub_db, claims,
            starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id="lead-1", consent=consent,
        )

        assert isinstance(event, ScheduleEvent)
        assert isinstance(event.event_id, str)
        assert len(event.event_id) == 32
        assert event.status == "booked"
        assert event.starts_at == starts_at
        assert event.ends_at == ends_at
        assert event.calendar_ref is None

        insert_query, insert_args = stub_db.execute_calls[-1]
        assert "insert into schedule_events" in insert_query.lower()
        assert "$1" in insert_query
        assert ":" not in insert_query
        assert insert_args[0] == "tenant-abc"


async def test_create_event_unique_violation_raises_slot_unavailable(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event

        claims = _claims(tenant_id="tenant-abc")
        starts_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        consent = {"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"}

        await create_event(
            stub_db, claims,
            starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id=None, consent=consent,
        )

        with pytest.raises(ValidationError) as exc_info:
            await create_event(
                stub_db, claims,
                starts_at=starts_at, ends_at=ends_at, timezone="UTC",
                visitor_id="visitor-2", lead_id=None, consent=consent,
            )

        assert exc_info.value.code == "SLOT_UNAVAILABLE"


async def test_create_event_simulated_unique_violation_via_injection(stub_db: _StubDatabase) -> None:
    """A directly-injected asyncpg.UniqueViolationError is also caught -> SLOT_UNAVAILABLE."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event

        claims = _claims(tenant_id="tenant-abc")
        stub_db.raise_on_insert_event = asyncpg.UniqueViolationError("dup")

        with pytest.raises(ValidationError) as exc_info:
            await create_event(
                stub_db, claims,
                starts_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
                ends_at=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
                timezone="UTC", visitor_id="visitor-1", lead_id=None,
                consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
            )

        assert exc_info.value.code == "SLOT_UNAVAILABLE"


async def test_create_event_cross_tenant_no_conflict(stub_db: _StubDatabase) -> None:
    """The same starts_at can be booked independently by two different tenants."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event

        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")
        starts_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
        ends_at = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        consent = {"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"}

        event_a = await create_event(
            stub_db, claims_a, starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-1", lead_id=None, consent=consent,
        )
        event_b = await create_event(
            stub_db, claims_b, starts_at=starts_at, ends_at=ends_at, timezone="UTC",
            visitor_id="visitor-2", lead_id=None, consent=consent,
        )

        assert event_a.event_id != event_b.event_id


async def test_create_event_rejects_global_caller(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event

        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await create_event(
                stub_db, global_claims,
                starts_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
                ends_at=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
                timezone="UTC", visitor_id="visitor-1", lead_id=None,
                consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
            )


# ---------------------------------------------------------------------------
# get_event_contact (S9.2, Scope §6)
# ---------------------------------------------------------------------------


async def test_get_event_contact_returns_contact_fields(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import EventContact, create_event, get_event_contact

        claims = _claims(tenant_id="tenant-abc")
        event = await create_event(
            stub_db, claims,
            starts_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            timezone="America/New_York", visitor_id="visitor-1", lead_id="lead-1",
            consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
        )

        contact = await get_event_contact(stub_db, claims, event.event_id)

        assert isinstance(contact, EventContact)
        assert contact.lead_id == "lead-1"
        assert contact.visitor_id == "visitor-1"
        assert contact.timezone == "America/New_York"
        assert contact.status == "booked"


async def test_get_event_contact_missing_event_returns_none(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_event_contact

        claims = _claims(tenant_id="tenant-abc")
        result = await get_event_contact(stub_db, claims, "event-does-not-exist")

        assert result is None


async def test_get_event_contact_cross_tenant_isolation(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import create_event, get_event_contact

        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")
        event = await create_event(
            stub_db, claims_a,
            starts_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            timezone="UTC", visitor_id="visitor-1", lead_id=None,
            consent={"granted": True, "purpose": "booking", "text": "OK", "captured_at": "x"},
        )

        result = await get_event_contact(stub_db, claims_b, event.event_id)

        assert result is None


async def test_get_event_contact_uses_positional_placeholders(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_event_contact

        claims = _claims(tenant_id="tenant-abc")
        await get_event_contact(stub_db, claims, "event-1")

        query, args = stub_db.fetchrow_calls[-1]
        assert "$1" in query
        assert "$2" in query
        assert ":" not in query
        assert args[0] == "tenant-abc"


async def test_get_event_contact_rejects_global_caller(stub_db: _StubDatabase) -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.scheduling.repository import get_event_contact

        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await get_event_contact(stub_db, global_claims, "event-1")
