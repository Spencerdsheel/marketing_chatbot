"""Unit tests for GET /public/schedule/slots + POST /public/schedule/book.

Covers:
- GET /slots returns open slots for the tenant (visitor session).
- No availability configured -> [] (200, not an error).
- POST /book valid + consent -> 201 event status:"booked".
- Consent false/omitted -> 422 CONSENT_REQUIRED, nothing stored.
- Booking a non-open time -> 422 SLOT_UNAVAILABLE.
- Double-book (second book of the same start) -> 422 SLOT_UNAVAILABLE.
- tenant_id/visitor_id come from the session, never the body.
- No bearer -> 401.
- Tenant isolation: tenant A's slots/events never reflect tenant B.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import asyncpg
from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"
_OTHER_TENANT_ID = "tenant-xyz-999"


def _next_monday_iso() -> str:
    """A Monday at least a week in the future, so slots are never in the past."""
    today = datetime.now(UTC).date()
    days_ahead = (7 - today.weekday()) % 7 or 7  # next Monday, at least 1 day out
    days_ahead += 7  # push another week out for safety margin
    monday = today + timedelta(days=days_ahead)
    return monday.isoformat()


_MONDAY = _next_monday_iso()

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}

_RULES = {
    "slot_minutes": 30,
    "buffer_minutes": 0,
    "weekly_hours": {
        "mon": [["09:00", "17:00"]], "tue": [["09:00", "17:00"]],
        "wed": [["09:00", "17:00"]], "thu": [["09:00", "17:00"]],
        "fri": [["09:00", "17:00"]], "sat": [], "sun": [],
    },
}


class _StubDatabase:
    """In-memory stub database backing the scheduling routes for these tests."""

    def __init__(self) -> None:
        self._availability: dict[str, dict[str, Any]] = {}
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self._calendar_configs: dict[str, dict[str, Any]] = {}
        self._reminder_jobs: dict[str, dict[str, Any]] = {}

    def seed_availability(self, *, tenant_id: str, timezone: str = "UTC", rules: dict[str, Any] = _RULES) -> None:
        self._availability[tenant_id] = {
            "tenant_id": tenant_id,
            "timezone": timezone,
            "rules": rules,
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip().upper()

        if q.startswith("INSERT INTO AVAILABILITY"):
            tenant_id, timezone, rules = args
            self._availability[tenant_id] = {
                "tenant_id": tenant_id, "timezone": timezone, "rules": rules,
                "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
            return "INSERT 0 1"

        if q.startswith("INSERT INTO SCHEDULE_EVENTS"):
            (tenant_id, event_id, lead_id, visitor_id, starts_at, ends_at,
             timezone, status, calendar_ref, consent) = args
            for (t_id, _e_id), existing in self._events.items():
                if t_id == tenant_id and existing["starts_at"] == starts_at and existing["status"] == "booked":
                    raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
            self._events[(tenant_id, event_id)] = {
                "tenant_id": tenant_id, "event_id": event_id, "lead_id": lead_id,
                "visitor_id": visitor_id, "starts_at": starts_at, "ends_at": ends_at,
                "timezone": timezone, "status": status, "calendar_ref": calendar_ref,
                "consent": consent, "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
            return "INSERT 0 1"

        if q.startswith("INSERT INTO TENANT_CALENDAR_CONFIGS"):
            tenant_id, provider, calendar_id, credentials_ciphertext, busy, enabled = args
            self._calendar_configs[tenant_id] = {
                "provider": provider, "calendar_id": calendar_id,
                "credentials_ciphertext": credentials_ciphertext, "busy": busy,
                "enabled": enabled,
            }
            return "INSERT 0 1"

        if q.startswith("UPDATE SCHEDULE_EVENTS"):
            tenant_id, event_id, calendar_ref = args
            key = (tenant_id, event_id)
            if key in self._events:
                self._events[key]["calendar_ref"] = calendar_ref
            return "UPDATE 1"

        if q.startswith("DELETE FROM SCHEDULE_EVENTS"):
            tenant_id, event_id = args
            self._events.pop((tenant_id, event_id), None)
            # Simulate the real FK ON DELETE CASCADE (migration 0020): deleting
            # an event removes its reminder_jobs rows too.
            for job_id in [
                jid for jid, job in self._reminder_jobs.items()
                if job["tenant_id"] == tenant_id and job["event_id"] == event_id
            ]:
                del self._reminder_jobs[job_id]
            return "DELETE 1"

        if q.startswith("INSERT INTO REMINDER_JOBS"):
            job_id, tenant_id, event_id, offset, run_at, status = args
            key = (tenant_id, event_id, offset)
            existing = next(
                (j for j in self._reminder_jobs.values()
                 if (j["tenant_id"], j["event_id"], j["offset"]) == key),
                None,
            )
            if existing is not None:
                return "INSERT 0 0"
            self._reminder_jobs[job_id] = {
                "job_id": job_id, "tenant_id": tenant_id, "event_id": event_id,
                "offset": offset, "run_at": run_at, "status": status, "attempts": 0,
                "last_error": None, "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
            return "INSERT 0 1"

        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.strip().upper()
        if "FROM AVAILABILITY" in q:
            tenant_id = args[0]
            return self._availability.get(tenant_id)
        if "FROM TENANT_CALENDAR_CONFIGS" in q:
            tenant_id = args[0]
            return self._calendar_configs.get(tenant_id)
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = query.strip().upper()
        if "FROM SCHEDULE_EVENTS" in q:
            tenant_id = args[0]
            rows = [
                row for row in self._events.values()
                if row["tenant_id"] == tenant_id and row["status"] == "booked"
            ]
            if len(args) >= 3:
                window_start, window_end = args[1], args[2]
                rows = [r for r in rows if window_start <= r["starts_at"] <= window_end]
            rows.sort(key=lambda r: r["starts_at"])
            return rows
        if "FROM REMINDER_JOBS" in q:
            tenant_id, event_id = args
            rows = [
                j for j in self._reminder_jobs.values()
                if j["tenant_id"] == tenant_id and j["event_id"] == event_id
            ]
            rows.sort(key=lambda j: j["run_at"])
            return rows
        return []

    async def close(self) -> None:
        pass


class _StubRedis:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def getdel(self, key: str) -> str | None:
        return None

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def _reset_settings() -> None:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _build_app(db: _StubDatabase) -> Any:
    _reset_settings()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = db
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    return app


def _visitor_token(tenant_id: str = _TENANT_ID, visitor_id: str = "visitor-123") -> str:
    claims = AuthClaims(subject=visitor_id, role=Role.VISITOR, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=_TEST_JWT_SECRET, ttl_seconds=300)
    return token


def _admin_token(tenant_id: str = _TENANT_ID) -> str:
    claims = AuthClaims(subject="admin-1", role=Role.CLIENT_ADMIN, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=_TEST_JWT_SECRET, ttl_seconds=300)
    return token


async def _configure_calendar(client: AsyncClient, token: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "provider": "stub",
        "calendar_id": "dev",
        "credentials": "stub-token-value",
        "enabled": True,
        "busy": [],
    }
    body.update(overrides)
    response = await client.put(
        "/admin/schedule/calendar", json=body, cookies={"access_token": token}
    )
    assert response.status_code == 200
    return response


# ---------------------------------------------------------------------------
# GET /public/schedule/slots
# ---------------------------------------------------------------------------


async def test_get_slots_returns_open_slots_for_tenant() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 16
    assert data[0]["starts_at"].startswith(f"{_MONDAY}T09:00:00")


async def test_get_slots_no_availability_returns_empty_list() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.get(
            "/public/schedule/slots",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == []


async def test_get_slots_no_bearer_returns_401() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/public/schedule/slots")

    assert response.status_code == 401


async def test_get_slots_tenant_isolation() -> None:
    """Tenant A's slots do not reflect tenant B's availability/bookings."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    # tenant B has no availability configured
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token_b = _visitor_token(tenant_id=_OTHER_TENANT_ID)
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {token_b}"},
        )

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# POST /public/schedule/book
# ---------------------------------------------------------------------------


def _book_body(starts_at: str = f"{_MONDAY}T09:00:00+00:00") -> dict[str, Any]:
    return {
        "starts_at": starts_at,
        "timezone": "UTC",
        "consent": {"granted": True, "purpose": "booking", "text": "I agree."},
    }


async def test_post_book_valid_consent_returns_201_booked() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book",
            json=_book_body(),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "booked"
    assert "event_id" in data
    assert "tenant_id" not in data
    assert "visitor_id" not in data


async def test_post_book_consent_false_returns_422_and_nothing_stored() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    body = _book_body()
    body["consent"] = {"granted": False, "purpose": "booking", "text": "no"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "CONSENT_REQUIRED"
    assert db._events == {}


async def test_post_book_consent_omitted_returns_422() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    body = {"starts_at": f"{_MONDAY}T09:00:00+00:00", "timezone": "UTC"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "CONSENT_REQUIRED"
    assert db._events == {}


async def test_post_book_non_open_time_returns_slot_unavailable() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    # 09:15 is not a slot boundary for a 30-minute grid starting at 09:00.
    body = _book_body(starts_at=f"{_MONDAY}T09:15:00+00:00")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "SLOT_UNAVAILABLE"


async def test_post_book_no_availability_returns_slot_unavailable() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "SLOT_UNAVAILABLE"


async def test_post_book_double_book_returns_slot_unavailable() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        first = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )
        second = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )

    assert first.status_code == 201
    assert second.status_code == 422
    assert second.json()["error_code"] == "SLOT_UNAVAILABLE"


async def test_post_book_uses_claims_visitor_and_tenant_not_body() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    body = _book_body()
    body["tenant_id"] = "tenant-fake"
    body["visitor_id"] = "visitor-fake"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token(tenant_id=_TENANT_ID, visitor_id="visitor-real")
        response = await client.post(
            "/public/schedule/book", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 201
    stored = next(iter(db._events.values()))
    assert stored["tenant_id"] == _TENANT_ID
    assert stored["visitor_id"] == "visitor-real"


async def test_post_book_no_bearer_returns_401() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/public/schedule/book", json=_book_body())

    assert response.status_code == 401


async def test_post_book_cross_tenant_slot_independent() -> None:
    """Tenant A booking a start does not block tenant B from booking the same start."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    db.seed_availability(tenant_id=_OTHER_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token_a = _visitor_token(tenant_id=_TENANT_ID)
        token_b = _visitor_token(tenant_id=_OTHER_TENANT_ID)
        first = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token_a}"}
        )
        second = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token_b}"}
        )

    assert first.status_code == 201
    assert second.status_code == 201


# ---------------------------------------------------------------------------
# Calendar sync (S8.2)
# ---------------------------------------------------------------------------


async def test_get_slots_excludes_calendar_busy_interval() -> None:
    """A StubCalendarProvider busy interval is subtracted like a booked event."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        await _configure_calendar(
            client, admin_token,
            busy=[{"start": f"{_MONDAY}T09:00:00Z", "end": f"{_MONDAY}T09:30:00Z"}],
        )

        visitor_token = _visitor_token()
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {visitor_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert not any(slot["starts_at"].startswith(f"{_MONDAY}T09:00:00") for slot in data)
    assert len(data) == 15  # 16 native slots minus the one excluded by free-busy


async def test_get_slots_freebusy_error_degrades_to_native_200() -> None:
    """An unusable calendar config (unknown provider) degrades to native slots, not a 500."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        await _configure_calendar(client, admin_token, provider="not-a-real-provider")

        visitor_token = _visitor_token()
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {visitor_token}"},
        )

    assert response.status_code == 200
    assert len(response.json()) == 16  # native slots, unaffected by the broken calendar config


async def test_get_slots_no_calendar_configured_is_native_s81_behavior() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert len(response.json()) == 16


async def test_post_book_with_calendar_creates_and_persists_calendar_ref() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        await _configure_calendar(client, admin_token)

        visitor_token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {visitor_token}"}
        )

    assert response.status_code == 201
    stored = next(iter(db._events.values()))
    assert stored["status"] == "booked"
    assert stored["calendar_ref"] == f"stub:stub-{response.json()['event_id']}"


async def test_post_book_calendar_sync_failure_compensates_no_orphan() -> None:
    """A calendar create_event failure deletes the row and raises CALENDAR_SYNC_FAILED."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        # An unknown provider makes calendar_provider_for raise inside the
        # booking route's calendar-sync try block (S8.2 decision 4).
        await _configure_calendar(client, admin_token, provider="not-a-real-provider")

        visitor_token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {visitor_token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "CALENDAR_SYNC_FAILED"
    assert db._events == {}  # no orphan row


async def test_post_book_no_calendar_configured_native_path_calendar_ref_none() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 201
    stored = next(iter(db._events.values()))
    assert stored["calendar_ref"] is None


async def test_post_book_calendar_disabled_skips_sync_calendar_ref_none() -> None:
    """A configured-but-disabled calendar is not synced (calendar_ref stays null)."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        await _configure_calendar(client, admin_token, enabled=False)

        visitor_token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {visitor_token}"}
        )

    assert response.status_code == 201
    stored = next(iter(db._events.values()))
    assert stored["calendar_ref"] is None


async def test_calendar_config_tenant_isolation_freebusy() -> None:
    """Tenant A's calendar busy interval never affects tenant B's slots."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    db.seed_availability(tenant_id=_OTHER_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token_a = _admin_token(tenant_id=_TENANT_ID)
        await _configure_calendar(
            client, admin_token_a,
            busy=[{"start": f"{_MONDAY}T09:00:00Z", "end": f"{_MONDAY}T09:30:00Z"}],
        )

        visitor_token_b = _visitor_token(tenant_id=_OTHER_TENANT_ID)
        response = await client.get(
            f"/public/schedule/slots?date_from={_MONDAY}&date_to={_MONDAY}",
            headers={"Authorization": f"Bearer {visitor_token_b}"},
        )

    assert response.status_code == 200
    assert len(response.json()) == 16  # tenant B has no calendar configured -- unaffected


async def test_calendar_config_tenant_isolation_booking() -> None:
    """Tenant A's calendar config never syncs tenant B's booking."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    db.seed_availability(tenant_id=_OTHER_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token_a = _admin_token(tenant_id=_TENANT_ID)
        await _configure_calendar(client, admin_token_a)

        visitor_token_b = _visitor_token(tenant_id=_OTHER_TENANT_ID)
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {visitor_token_b}"}
        )

    assert response.status_code == 201
    stored = next(iter(db._events.values()))
    assert stored["calendar_ref"] is None  # tenant B has no calendar -- native booking


# ---------------------------------------------------------------------------
# Reminder jobs (S8.3)
# ---------------------------------------------------------------------------


async def test_post_book_creates_three_reminder_jobs() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 201
    event_id = response.json()["event_id"]
    reminders = [j for j in db._reminder_jobs.values() if j["event_id"] == event_id]
    assert len(reminders) == 3
    assert {j["offset"] for j in reminders} == {"3d", "24h", "1h"}
    assert all(j["tenant_id"] == _TENANT_ID for j in reminders)


async def test_post_book_reminder_creation_happens_before_calendar_sync() -> None:
    """create_reminder_jobs is called with the event's event_id + starts_at,
    before the S8.2 calendar sync step (spy on call order)."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    call_order: list[str] = []

    async def _spy_create_reminder_jobs(db_: Any, claims_: Any, **kwargs: Any) -> list[Any]:
        call_order.append("create_reminder_jobs")
        assert "event_id" in kwargs
        assert "starts_at" in kwargs
        from api.scheduling.reminder_repository import create_reminder_jobs as _real

        return await _real(db_, claims_, **kwargs)

    def _spy_calendar_provider_for(*args: Any, **kwargs: Any) -> Any:
        call_order.append("calendar_provider_for")
        from api.scheduling.calendar import calendar_provider_for as _real

        return _real(*args, **kwargs)

    with (
        patch("api.scheduling.routes.create_reminder_jobs", side_effect=_spy_create_reminder_jobs),
        patch("api.scheduling.routes.calendar_provider_for", side_effect=_spy_calendar_provider_for),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = _admin_token()
            await _configure_calendar(client, admin_token)

            visitor_token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(),
                headers={"Authorization": f"Bearer {visitor_token}"},
            )

    assert response.status_code == 201
    assert call_order == ["create_reminder_jobs", "calendar_provider_for"]


async def test_post_book_calendar_sync_failure_cascades_reminder_rows() -> None:
    """A CALENDAR_SYNC_FAILED compensation (delete_event) leaves no reminder rows."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = _admin_token()
        await _configure_calendar(client, admin_token, provider="not-a-real-provider")

        visitor_token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {visitor_token}"}
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == "CALENDAR_SYNC_FAILED"
    assert db._events == {}
    assert db._reminder_jobs == {}  # cascaded away with the compensated event


async def test_post_book_no_calendar_configured_still_creates_three_reminder_rows() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _visitor_token()
        response = await client.post(
            "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 201
    event_id = response.json()["event_id"]
    reminders = [j for j in db._reminder_jobs.values() if j["event_id"] == event_id]
    assert len(reminders) == 3


# ---------------------------------------------------------------------------
# Booking confirmation enqueue (S9.2, Scope §8)
# ---------------------------------------------------------------------------


async def test_post_book_resolvable_recipient_enqueues_confirmation_and_delays_once() -> None:
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    with (
        patch(
            "api.scheduling.routes.resolve_event_recipient",
            new=AsyncMock(return_value="lead@example.com"),
        ) as mock_resolve,
        patch(
            "api.scheduling.routes.enqueue_notification",
            new=AsyncMock(return_value="job-confirm-1"),
        ) as mock_enqueue,
        patch("api.scheduling.routes.send_notification") as mock_task,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
            )

    assert response.status_code == 201
    event_id = response.json()["event_id"]
    mock_resolve.assert_awaited_once()
    mock_enqueue.assert_awaited_once()
    _, kwargs = mock_enqueue.call_args
    assert kwargs["dedupe_key"] == f"booking_confirm:{event_id}"
    assert kwargs["channel"] == "email"
    mock_task.delay.assert_called_once()
    _, delay_kwargs = mock_task.delay.call_args
    assert delay_kwargs["job_id"] == "job-confirm-1"


async def test_post_book_no_recipient_skips_enqueue_still_201() -> None:
    """No resolvable recipient (default stub DB) -> no enqueue, booking still 201."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    with patch("api.scheduling.routes.enqueue_notification") as mock_enqueue:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
            )

    assert response.status_code == 201
    mock_enqueue.assert_not_called()


async def test_post_book_enqueue_raises_degrades_still_201() -> None:
    """An enqueue that raises is best-effort -- booking still 201 (never 500)."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    with (
        patch(
            "api.scheduling.routes.resolve_event_recipient",
            new=AsyncMock(return_value="lead@example.com"),
        ),
        patch(
            "api.scheduling.routes.enqueue_notification",
            new=AsyncMock(side_effect=RuntimeError("db unavailable")),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
            )

    assert response.status_code == 201


async def test_post_book_calendar_sync_failure_enqueues_no_confirmation() -> None:
    """A CALENDAR_SYNC_FAILED compensation path enqueues NO confirmation."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    with patch("api.scheduling.routes.enqueue_notification") as mock_enqueue:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin_token = _admin_token()
            await _configure_calendar(client, admin_token, provider="not-a-real-provider")

            visitor_token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(),
                headers={"Authorization": f"Bearer {visitor_token}"},
            )

    assert response.status_code == 422
    assert response.json()["error_code"] == "CALENDAR_SYNC_FAILED"
    mock_enqueue.assert_not_called()


async def test_post_book_repeat_dedupe_key_does_not_double_delay() -> None:
    """Idempotency (MANDATORY): a repeat with the same dedupe target
    (enqueue_notification -> None) results in NO second .delay()."""
    db = _StubDatabase()
    db.seed_availability(tenant_id=_TENANT_ID)
    app = _build_app(db)

    with (
        patch(
            "api.scheduling.routes.resolve_event_recipient",
            new=AsyncMock(return_value="lead@example.com"),
        ),
        patch("api.scheduling.routes.enqueue_notification", new=AsyncMock(return_value=None)),
        patch("api.scheduling.routes.send_notification") as mock_task,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = _visitor_token()
            response = await client.post(
                "/public/schedule/book", json=_book_body(), headers={"Authorization": f"Bearer {token}"}
            )

    assert response.status_code == 201
    mock_task.delay.assert_not_called()
