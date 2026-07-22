"""Unit tests for POST /public/calendly/webhook/{tenant_id} (SR-6).

SECURITY-CRITICAL, MANDATORY suite (per the sprint spec). Covers:
- Valid signature -> 200, event processed.
- Invalid/tampered/missing/malformed/stale signature -> 401
  CALENDLY_SIGNATURE_INVALID, NOTHING written.
- Cross-tenant rejection (MANDATORY).
- Unknown / non-Calendly tenant -> 404/401, nothing written, no secret/PII leaked.
- Idempotent re-delivery (MANDATORY): same invitee.created UUID twice -> ONE row.
- invitee.canceled: status flip; unknown UUID -> 200 no-op, no row created.
- Email correlation: match / no-match (honest, not dropped) / expired / most-recent-wins.
- Raw-body HMAC: verification uses the raw bytes, not re-serialized JSON.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from common.cache import InMemoryCache
from common.crypto import SecretBox
from httpx import ASGITransport, AsyncClient

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"
_OTHER_TENANT_ID = "tenant-xyz-999"
_SIGNING_SECRET = "calendly" + "-" + "signing" + "-" + "secret"  # not a real credential
_OTHER_SIGNING_SECRET = "other" + "-" + "tenant" + "-" + "secret"

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


def _reset_settings() -> None:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


class _StubDatabase:
    """In-memory stub backing the webhook receiver's downstream repos."""

    def __init__(self) -> None:
        self._calendar_configs: dict[str, dict[str, Any]] = {}
        self._events: dict[tuple[str, str], dict[str, Any]] = {}
        self._handoff_intents: list[dict[str, Any]] = []
        self._reminder_jobs: dict[str, dict[str, Any]] = {}

    def seed_calendly(self, tenant_id: str, *, secret: str, enabled: bool = True) -> None:
        with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
            _reset_settings()
            from api.config import get_api_settings

            box = SecretBox(get_api_settings().secret_encryption_key)
        self._calendar_configs[tenant_id] = {
            "provider": "calendly",
            "calendar_id": None,
            "credentials_ciphertext": box.encrypt(secret),
            "busy": [],
            "enabled": enabled,
            "scheduling_url": "https://calendly.com/acme/intro",
        }

    def seed_handoff_intent(
        self, *, tenant_id: str, visitor_id: str, email: str, ttl_seconds: int = 3600,
        created_at: datetime | None = None,
    ) -> None:
        created = created_at or datetime.now(UTC)
        self._handoff_intents.append(
            {
                "tenant_id": tenant_id,
                "visitor_id": visitor_id,
                "email": email,
                "created_at": created,
                "expires_at": created + timedelta(seconds=ttl_seconds),
            }
        )

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip().upper()
        if q.startswith("UPDATE SCHEDULE_EVENTS SET STATUS = 'CANCELLED'"):
            tenant_id, calendar_ref = args
            for (t_id, _e_id), row in self._events.items():
                if t_id == tenant_id and row["calendar_ref"] == calendar_ref and row.get("source") == "calendly":
                    row["status"] = "cancelled"
            return "UPDATE 1"
        if q.startswith("INSERT INTO REMINDER_JOBS"):
            job_id, tenant_id, event_id, offset, run_at, status = args
            existing = next(
                (
                    j for j in self._reminder_jobs.values()
                    if (j["tenant_id"], j["event_id"], j["offset"]) == (tenant_id, event_id, offset)
                ),
                None,
            )
            if existing is not None:
                return "INSERT 0 0"
            self._reminder_jobs[job_id] = {
                "job_id": job_id, "tenant_id": tenant_id, "event_id": event_id, "offset": offset,
                "run_at": run_at, "status": status, "attempts": 0, "last_error": None,
                "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
            }
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.strip().upper()

        if "FROM TENANT_CALENDAR_CONFIGS" in q:
            tenant_id = args[0]
            return self._calendar_configs.get(tenant_id)

        if "FROM CALENDLY_HANDOFF_INTENTS" in q:
            tenant_id, email, now = args
            matches = [
                row for row in self._handoff_intents
                if row["tenant_id"] == tenant_id
                and row["email"].lower() == email.lower()
                and row["expires_at"] > now
            ]
            if not matches:
                return None
            matches.sort(key=lambda r: r["created_at"], reverse=True)
            return {"visitor_id": matches[0]["visitor_id"]}

        if q.startswith("INSERT INTO SCHEDULE_EVENTS"):
            (tenant_id, event_id, lead_id, visitor_id, email, name, starts_at, ends_at,
             timezone, status, calendar_ref, consent, source) = args
            existing_key = next(
                (
                    key for key, row in self._events.items()
                    if key[0] == tenant_id and row["calendar_ref"] == calendar_ref and row.get("source") == "calendly"
                ),
                None,
            )
            if existing_key is not None:
                row = self._events[existing_key]
                row["starts_at"] = starts_at
                row["ends_at"] = ends_at
                row["timezone"] = timezone
                row["email"] = email
                row["name"] = name
                row["status"] = "booked"
                if row.get("visitor_id") is None:
                    row["visitor_id"] = visitor_id
                return dict(row)
            new_row = {
                "tenant_id": tenant_id, "event_id": event_id, "lead_id": lead_id,
                "visitor_id": visitor_id, "email": email, "name": name,
                "starts_at": starts_at, "ends_at": ends_at, "timezone": timezone,
                "status": status, "calendar_ref": calendar_ref, "consent": consent,
                "created_at": datetime.now(UTC), "source": source,
            }
            self._events[(tenant_id, event_id)] = new_row
            return dict(new_row)

        if "FROM SCHEDULE_EVENTS" in q:
            # get_event_contact (recipient resolution) -- no lead/email match by default
            return None

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = query.strip().upper()
        if "FROM REMINDER_JOBS" in q:
            tenant_id, event_id = args
            return [
                j for j in self._reminder_jobs.values()
                if j["tenant_id"] == tenant_id and j["event_id"] == event_id
            ]
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


def _build_app(db: _StubDatabase) -> Any:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()
    app.state.db = db
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    return app


def _sign(secret: str, body: bytes, *, t: int | None = None) -> tuple[str, bytes]:
    ts = t if t is not None else int(datetime.now(UTC).timestamp())
    signed_payload = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}", body


def _invitee_created_body(
    *, uuid: str = "calendly-uuid-1", email: str = "a@example.com", name: str = "A Visitor",
) -> bytes:
    payload = {
        "event": "invitee.created",
        "payload": {
            "uri": uuid,
            "email": email,
            "name": name,
            "scheduled_event": {
                "start_time": "2099-06-01T09:00:00Z",
                "end_time": "2099-06-01T09:30:00Z",
            },
            "timezone": "UTC",
        },
    }
    return json.dumps(payload).encode("utf-8")


def _invitee_canceled_body(*, uuid: str = "calendly-uuid-1") -> bytes:
    payload = {"event": "invitee.canceled", "payload": {"uri": uuid}}
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Valid signature -> 200
# ---------------------------------------------------------------------------


async def test_valid_signature_processes_event() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = [r for r in db._events.values() if r["calendar_ref"] == "calendly:calendly-uuid-1"]
    assert len(stored) == 1
    assert stored[0]["status"] == "booked"
    assert stored[0]["source"] == "calendly"


# ---------------------------------------------------------------------------
# Invalid / tampered / missing / malformed / stale signature -> 401, nothing written
# ---------------------------------------------------------------------------


async def test_tampered_body_returns_401_nothing_written() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    header, _raw = _sign(_SIGNING_SECRET, body)
    tampered = _invitee_created_body(email="attacker@example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=tampered,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


async def test_missing_signature_header_returns_401_nothing_written() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=_invitee_created_body(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


async def test_malformed_signature_header_returns_401_nothing_written() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=_invitee_created_body(),
            headers={"Calendly-Webhook-Signature": "not-a-valid-header", "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


async def test_wrong_secret_returns_401_nothing_written() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    header, raw = _sign("wrong-secret-value", body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


async def test_stale_timestamp_returns_401_nothing_written() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    stale_t = int(datetime.now(UTC).timestamp()) - 3600  # 1 hour ago, default tolerance is 300s
    header, raw = _sign(_SIGNING_SECRET, body, t=stale_t)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


# ---------------------------------------------------------------------------
# Cross-tenant rejection (MANDATORY)
# ---------------------------------------------------------------------------


async def test_cross_tenant_signature_rejected_nothing_written_either_tenant() -> None:
    """Tenant A's signature POSTed to tenant B's path is verified against B's
    (different) secret and MUST fail -- never writes to either tenant."""
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    db.seed_calendly(_OTHER_TENANT_ID, secret=_OTHER_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    header_for_a, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_OTHER_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header_for_a, "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "CALENDLY_SIGNATURE_INVALID"
    assert db._events == {}


# ---------------------------------------------------------------------------
# Unknown / non-Calendly tenant -> reject, no secret/PII leaked
# ---------------------------------------------------------------------------


async def test_unknown_tenant_rejected_no_secret_or_pii_in_response() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = _invitee_created_body()
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/public/calendly/webhook/unknown-tenant",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code in (401, 404)
    body_text = response.text
    assert _SIGNING_SECRET not in body_text
    assert "a@example.com" not in body_text
    assert db._events == {}


async def test_non_calendly_tenant_rejected() -> None:
    """A tenant configured for a different provider (not Calendly) is rejected."""
    db = _StubDatabase()
    db._calendar_configs[_TENANT_ID] = {
        "provider": "google", "calendar_id": "primary",
        "credentials_ciphertext": None, "busy": [], "enabled": True,
        "scheduling_url": None,
    }
    app = _build_app(db)

    body = _invitee_created_body()
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 401
    assert db._events == {}


# ---------------------------------------------------------------------------
# Idempotent re-delivery (MANDATORY)
# ---------------------------------------------------------------------------


async def test_idempotent_redelivery_exactly_one_row() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body()
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )
        header2, raw2 = _sign(_SIGNING_SECRET, body)
        second = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw2,
            headers={"Calendly-Webhook-Signature": header2, "Content-Type": "application/json"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    stored = [r for r in db._events.values() if r["calendar_ref"] == "calendly:calendly-uuid-1"]
    assert len(stored) == 1
    reminders_for_event = [
        j for j in db._reminder_jobs.values() if j["event_id"] == stored[0]["event_id"]
    ]
    # Reminder creation is itself idempotent (ON CONFLICT DO NOTHING) -- no
    # double reminder set even across two full webhook deliveries.
    assert len({j["offset"] for j in reminders_for_event}) == len(reminders_for_event)


# ---------------------------------------------------------------------------
# invitee.canceled
# ---------------------------------------------------------------------------


async def test_invitee_canceled_flips_status() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    created_body = _invitee_created_body()
    created_header, created_raw = _sign(_SIGNING_SECRET, created_body)

    cancel_body = _invitee_canceled_body()
    cancel_header, cancel_raw = _sign(_SIGNING_SECRET, cancel_body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=created_raw,
            headers={"Calendly-Webhook-Signature": created_header, "Content-Type": "application/json"},
        )
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=cancel_raw,
            headers={"Calendly-Webhook-Signature": cancel_header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = [r for r in db._events.values() if r["calendar_ref"] == "calendly:calendly-uuid-1"]
    assert len(stored) == 1
    assert stored[0]["status"] == "cancelled"


async def test_invitee_canceled_unknown_uuid_noop_no_row_created() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    cancel_body = _invitee_canceled_body(uuid="never-existed")
    cancel_header, cancel_raw = _sign(_SIGNING_SECRET, cancel_body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=cancel_raw,
            headers={"Calendly-Webhook-Signature": cancel_header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert db._events == {}


# ---------------------------------------------------------------------------
# Email correlation
# ---------------------------------------------------------------------------


async def test_email_correlation_match_backfills_visitor_id() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    db.seed_handoff_intent(tenant_id=_TENANT_ID, visitor_id="visitor-123", email="a@example.com")
    app = _build_app(db)

    body = _invitee_created_body(email="a@example.com")
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = next(iter(db._events.values()))
    assert stored["visitor_id"] == "visitor-123"


async def test_email_correlation_no_match_ingests_with_visitor_id_null() -> None:
    """Honest no-match (decision 5b): booking still ingested, never dropped."""
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    body = _invitee_created_body(email="nobody-matched@example.com")
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = next(iter(db._events.values()))
    assert stored["visitor_id"] is None
    assert stored["status"] == "booked"


async def test_email_correlation_expired_intent_treated_as_no_match() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    db.seed_handoff_intent(
        tenant_id=_TENANT_ID, visitor_id="visitor-123", email="a@example.com",
        ttl_seconds=1, created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    app = _build_app(db)

    body = _invitee_created_body(email="a@example.com")
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = next(iter(db._events.values()))
    assert stored["visitor_id"] is None


async def test_email_correlation_most_recent_non_expired_wins() -> None:
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    now = datetime.now(UTC)
    db.seed_handoff_intent(
        tenant_id=_TENANT_ID, visitor_id="visitor-old", email="a@example.com",
        created_at=now - timedelta(minutes=30),
    )
    db.seed_handoff_intent(
        tenant_id=_TENANT_ID, visitor_id="visitor-new", email="a@example.com",
        created_at=now - timedelta(minutes=5),
    )
    app = _build_app(db)

    body = _invitee_created_body(email="a@example.com")
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = next(iter(db._events.values()))
    assert stored["visitor_id"] == "visitor-new"


async def test_email_correlation_tenant_isolation() -> None:
    """A same-email intent under a DIFFERENT tenant never backfills this tenant's row."""
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    db.seed_handoff_intent(tenant_id=_OTHER_TENANT_ID, visitor_id="visitor-other-tenant", email="a@example.com")
    app = _build_app(db)

    body = _invitee_created_body(email="a@example.com")
    header, raw = _sign(_SIGNING_SECRET, body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = next(iter(db._events.values()))
    assert stored["visitor_id"] is None


# ---------------------------------------------------------------------------
# Raw-body HMAC
# ---------------------------------------------------------------------------


async def test_signature_verified_against_raw_bytes_not_reserialized_json() -> None:
    """A body with non-canonical JSON formatting (extra whitespace) still
    verifies correctly IF the signature was computed over those exact raw
    bytes -- proving the handler signs over request.body(), not a
    re-serialized/re-parsed form."""
    db = _StubDatabase()
    db.seed_calendly(_TENANT_ID, secret=_SIGNING_SECRET)
    app = _build_app(db)

    # Deliberately non-canonical formatting (extra spaces, different key
    # order) -- if the handler re-serialized the parsed JSON before
    # verifying, this raw-byte signature would still need to match because
    # verification happens BEFORE parsing.
    raw = (
        b'{  "event":   "invitee.created",  "payload": {'
        b'"uri":"calendly-uuid-raw", "email":"a@example.com", "name":"A",'
        b'"scheduled_event": {"start_time":"2099-06-01T09:00:00Z","end_time":"2099-06-01T09:30:00Z"},'
        b'"timezone":"UTC"} }'
    )
    header, _ = _sign(_SIGNING_SECRET, raw)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/public/calendly/webhook/{_TENANT_ID}",
            content=raw,
            headers={"Calendly-Webhook-Signature": header, "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    stored = [r for r in db._events.values() if r["calendar_ref"] == "calendly:calendly-uuid-raw"]
    assert len(stored) == 1
