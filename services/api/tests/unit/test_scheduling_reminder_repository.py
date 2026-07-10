"""Unit tests for api.scheduling.reminder_repository.

Covers:
- create_reminder_jobs inserts 3 rows with correct run_ats (tenant-scoped,
  positional params, "offset" quoted).
- An offset with run_at <= now -> skipped.
- Re-run (same event) -> ON CONFLICT DO NOTHING, still 3 rows (idempotent).
- claim_due_reminders issues the atomic pending -> queued ... RETURNING SQL
  (flips status + filters run_at <= now + joins e.status='booked').
- get_reminder_job / mark_reminder tenant-scoped.
- Global caller -> ValidationError on the tenant-scoped ops.
- The dispatcher (claim_due_reminders) is system-scoped (no claims).
- Exactly-once: a second claim of an already-queued/sent job returns it 0 times.
- Tenant isolation: tenant A's reminder jobs never returned under tenant B's claims.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)


def _claims(tenant_id: str = "tenant-abc", role: Role = Role.VISITOR) -> AuthClaims:
    return AuthClaims(subject="visitor-123", role=role, tenant_id=tenant_id)


class _StubDatabase:
    """In-memory stub database for testing the reminder repository."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: dict[tuple[str, str], str] = {}  # (tenant_id, event_id) -> status
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    def seed_event(self, tenant_id: str, event_id: str, status: str = "booked") -> None:
        self._events[(tenant_id, event_id)] = status

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        q = query.strip().upper()

        if q.startswith("INSERT INTO REMINDER_JOBS"):
            job_id, tenant_id, event_id, offset, run_at, status = args
            key = (tenant_id, event_id, offset)
            existing = next(
                (j for j in self._jobs.values()
                 if (j["tenant_id"], j["event_id"], j["offset"]) == key),
                None,
            )
            if existing is not None:
                return "INSERT 0 0"  # ON CONFLICT DO NOTHING
            self._jobs[job_id] = {
                "job_id": job_id, "tenant_id": tenant_id, "event_id": event_id,
                "offset": offset, "run_at": run_at, "status": status, "attempts": 0,
                "last_error": None, "created_at": _NOW, "updated_at": _NOW,
            }
            return "INSERT 0 1"

        if q.startswith("UPDATE REMINDER_JOBS SET STATUS = $3"):
            tenant_id, job_id, status, last_error = args
            for job in self._jobs.values():
                if job["tenant_id"] == tenant_id and job["job_id"] == job_id:
                    job["status"] = status
                    job["last_error"] = last_error
            return "UPDATE 1"

        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        q = query.strip().upper()

        if q.startswith("UPDATE REMINDER_JOBS SET STATUS = 'QUEUED'"):
            (limit,) = args
            candidates = [
                j for j in self._jobs.values()
                if j["status"] == "pending"
                and j["run_at"] <= _NOW
                and self._events.get((j["tenant_id"], j["event_id"])) == "booked"
            ]
            candidates.sort(key=lambda j: j["run_at"])
            claimed = candidates[:limit]
            for job in claimed:
                job["status"] = "queued"
                job["attempts"] += 1
            return [
                {
                    "job_id": j["job_id"], "tenant_id": j["tenant_id"],
                    "event_id": j["event_id"], "offset": j["offset"],
                }
                for j in claimed
            ]

        if "FROM REMINDER_JOBS" in q:
            tenant_id, event_id = args
            rows = [
                j for j in self._jobs.values()
                if j["tenant_id"] == tenant_id and j["event_id"] == event_id
            ]
            rows.sort(key=lambda j: j["run_at"])
            return rows

        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        q = query.strip().upper()

        if "FROM REMINDER_JOBS" in q:
            tenant_id, job_id = args
            return next(
                (j for j in self._jobs.values()
                 if j["tenant_id"] == tenant_id and j["job_id"] == job_id),
                None,
            )

        return None


@pytest.fixture
def stub_db() -> _StubDatabase:
    return _StubDatabase()


# ---------------------------------------------------------------------------
# create_reminder_jobs
# ---------------------------------------------------------------------------


async def test_create_reminder_jobs_inserts_three_rows_with_correct_run_ats(
    stub_db: _StubDatabase,
) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)

    jobs = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )

    assert len(jobs) == 3
    by_offset = {j.offset: j for j in jobs}
    assert by_offset["3d"].run_at == starts_at - timedelta(days=3)
    assert by_offset["24h"].run_at == starts_at - timedelta(hours=24)
    assert by_offset["1h"].run_at == starts_at - timedelta(hours=1)


async def test_create_reminder_jobs_uses_positional_params_and_quotes_offset(
    stub_db: _StubDatabase,
) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)

    await create_reminder_jobs(stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW)

    insert_query, insert_args = stub_db.execute_calls[0]
    assert "insert into reminder_jobs" in insert_query.lower()
    assert '"offset"' in insert_query
    assert "$1" in insert_query
    assert ":" not in insert_query
    assert insert_args[1] == "tenant-abc"


async def test_create_reminder_jobs_past_offset_is_skipped(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    # starts_at only 30 minutes out -- all three offsets are already past "now".
    starts_at = _NOW + timedelta(minutes=30)

    jobs = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )

    assert len(jobs) == 3
    assert {j.status for j in jobs} == {"skipped"}


async def test_create_reminder_jobs_mixed_past_and_future_offsets(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    # starts_at 2 hours out: 1h offset's run_at is in the future (pending),
    # but 24h and 3d offsets' run_at is already past (skipped).
    starts_at = _NOW + timedelta(hours=2)

    jobs = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )

    by_offset = {j.offset: j.status for j in jobs}
    assert by_offset["1h"] == "pending"
    assert by_offset["24h"] == "skipped"
    assert by_offset["3d"] == "skipped"


async def test_create_reminder_jobs_idempotent_rerun_still_three_rows(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)

    first = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )
    second = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )

    assert len(second) == 3
    assert {j.job_id for j in first} == {j.job_id for j in second}


async def test_create_reminder_jobs_rejects_global_caller(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs

    global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

    with pytest.raises(ValidationError):
        await create_reminder_jobs(
            stub_db, global_claims,
            event_id="event-1", starts_at=datetime(2026, 7, 20, 14, 0, tzinfo=UTC), now=_NOW,
        )


# ---------------------------------------------------------------------------
# claim_due_reminders (system-scoped, no claims)
# ---------------------------------------------------------------------------


async def test_claim_due_reminders_is_system_scoped_no_claims_param() -> None:
    import inspect

    from api.scheduling.reminder_repository import claim_due_reminders

    sig = inspect.signature(claim_due_reminders)
    assert "claims" not in sig.parameters


async def test_claim_due_reminders_issues_atomic_pending_to_queued_returning_sql(
    stub_db: _StubDatabase,
) -> None:
    from api.scheduling.reminder_repository import claim_due_reminders, create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    stub_db.seed_event("tenant-abc", "event-1", status="booked")
    # Booked far in the past relative to "now" (_NOW): at booking time the 1h
    # offset's run_at was still in the future (-> status='pending'); by the
    # time claim_due_reminders runs (using the stub's fixed _NOW), that
    # run_at is long past -> due for claim.
    booking_now = datetime(2020, 1, 1, tzinfo=UTC)
    starts_at = booking_now + timedelta(hours=2)
    await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=booking_now
    )

    claimed = await claim_due_reminders(stub_db, limit=10)

    query, args = stub_db.fetch_calls[-1]
    assert "UPDATE reminder_jobs SET status = 'queued'" in query
    assert "status = 'pending'" in query
    assert "run_at <= now()" in query
    assert "e.status = 'booked'" in query
    assert "SKIP LOCKED" in query
    assert "RETURNING" in query
    assert "$1" in query
    assert args == (10,)
    assert len(claimed) >= 1
    assert all(c.tenant_id == "tenant-abc" for c in claimed)


async def test_claim_due_reminders_exactly_once_second_claim_returns_zero(
    stub_db: _StubDatabase,
) -> None:
    from api.scheduling.reminder_repository import claim_due_reminders, create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    stub_db.seed_event("tenant-abc", "event-1", status="booked")
    booking_now = datetime(2020, 1, 1, tzinfo=UTC)
    starts_at = booking_now + timedelta(hours=2)
    await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=booking_now
    )

    first_claim = await claim_due_reminders(stub_db, limit=10)
    second_claim = await claim_due_reminders(stub_db, limit=10)

    claimed_job_ids = {c.job_id for c in first_claim}
    assert claimed_job_ids  # sanity: something was claimed
    assert second_claim == []  # the second tick claims nothing more (already queued)


async def test_claim_due_reminders_excludes_not_yet_due(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import claim_due_reminders, create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    stub_db.seed_event("tenant-abc", "event-1", status="booked")
    starts_at = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)  # far future -- nothing due yet
    await create_reminder_jobs(stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW)

    claimed = await claim_due_reminders(stub_db, limit=10)

    assert claimed == []


async def test_claim_due_reminders_excludes_non_booked_event(stub_db: _StubDatabase) -> None:
    """A future-cancelled event's reminders are never claimed (defensive guard)."""
    from api.scheduling.reminder_repository import claim_due_reminders, create_reminder_jobs

    claims = _claims(tenant_id="tenant-abc")
    stub_db.seed_event("tenant-abc", "event-1", status="cancelled")
    starts_at = _NOW + timedelta(minutes=30)
    await create_reminder_jobs(stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW)

    claimed = await claim_due_reminders(stub_db, limit=10)

    assert claimed == []


# ---------------------------------------------------------------------------
# get_reminder_job / mark_reminder (tenant-scoped)
# ---------------------------------------------------------------------------


async def test_get_reminder_job_and_mark_reminder_round_trip(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import (
        create_reminder_jobs,
        get_reminder_job,
        mark_reminder,
    )

    claims = _claims(tenant_id="tenant-abc")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    jobs = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )
    job_id = jobs[0].job_id

    fetched = await get_reminder_job(stub_db, claims, job_id)
    assert fetched is not None
    assert fetched.job_id == job_id

    await mark_reminder(stub_db, claims, job_id, status="sent")

    updated = await get_reminder_job(stub_db, claims, job_id)
    assert updated is not None
    assert updated.status == "sent"


async def test_mark_reminder_records_last_error_on_failure(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import (
        create_reminder_jobs,
        get_reminder_job,
        mark_reminder,
    )

    claims = _claims(tenant_id="tenant-abc")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    jobs = await create_reminder_jobs(
        stub_db, claims, event_id="event-1", starts_at=starts_at, now=_NOW
    )
    job_id = jobs[0].job_id

    await mark_reminder(stub_db, claims, job_id, status="failed", last_error="config error")

    updated = await get_reminder_job(stub_db, claims, job_id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.last_error == "config error"


async def test_get_reminder_job_tenant_isolation(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import create_reminder_jobs, get_reminder_job

    claims_a = _claims(tenant_id="tenant-a")
    claims_b = _claims(tenant_id="tenant-b")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    jobs = await create_reminder_jobs(
        stub_db, claims_a, event_id="event-1", starts_at=starts_at, now=_NOW
    )
    job_id = jobs[0].job_id

    result = await get_reminder_job(stub_db, claims_b, job_id)

    assert result is None


async def test_mark_reminder_tenant_isolation_no_cross_tenant_write(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import (
        create_reminder_jobs,
        get_reminder_job,
        mark_reminder,
    )

    claims_a = _claims(tenant_id="tenant-a")
    claims_b = _claims(tenant_id="tenant-b")
    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    jobs = await create_reminder_jobs(
        stub_db, claims_a, event_id="event-1", starts_at=starts_at, now=_NOW
    )
    job_id = jobs[0].job_id

    await mark_reminder(stub_db, claims_b, job_id, status="sent")

    unchanged = await get_reminder_job(stub_db, claims_a, job_id)
    assert unchanged is not None
    assert unchanged.status != "sent"


async def test_get_reminder_job_rejects_global_caller(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import get_reminder_job

    global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

    with pytest.raises(ValidationError):
        await get_reminder_job(stub_db, global_claims, "job-1")


async def test_mark_reminder_rejects_global_caller(stub_db: _StubDatabase) -> None:
    from api.scheduling.reminder_repository import mark_reminder

    global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

    with pytest.raises(ValidationError):
        await mark_reminder(stub_db, global_claims, "job-1", status="sent")
