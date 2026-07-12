"""Unit tests for api.notifications.config_repository + PUT /admin/notifications/config.

Covers:
- upsert_notification_config encrypts the SMTP password (ciphertext != plaintext).
- get_notification_config decrypts it back.
- PUT /admin/notifications/config is CLIENT_ADMIN only (agent/visitor -> 403).
- Response echoes provider/from/host/port/use_tls/username/enabled but NEVER
  the password/ciphertext.
- Tenant-scoped; global caller -> ValidationError.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from common.errors import ValidationError
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token
from api.notifications.config_repository import (
    get_notification_config,
    upsert_notification_config,
)

_TEST_JWT_SECRET = "x" * 48
_SECRET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
_TENANT_ID = "tenant-abc-123"
_OTHER_TENANT_ID = "tenant-xyz-999"

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": _SECRET_KEY,
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _reset_settings() -> None:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _claims(tenant_id: str | None = _TENANT_ID, role: Role = Role.CLIENT_ADMIN) -> AuthClaims:
    return AuthClaims(subject="admin-1", role=role, tenant_id=tenant_id)


class _StubDatabase:
    """In-memory stub database for the notification config repository.

    Keyed by ``(tenant_id, channel)`` -- S9.3 re-keys
    ``tenant_notification_configs`` to a per-channel composite PK.
    """

    def __init__(self) -> None:
        self._configs: dict[tuple[str, str], dict[str, Any]] = {}

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip().upper()
        if q.startswith("INSERT INTO TENANT_NOTIFICATION_CONFIGS"):
            (
                tenant_id, channel, provider, from_address, from_name, smtp_host, smtp_port,
                smtp_use_tls, smtp_username, twilio_account_sid, twilio_from,
                credentials_ciphertext, enabled,
            ) = args
            self._configs[(tenant_id, channel)] = {
                "provider": provider, "from_address": from_address, "from_name": from_name,
                "smtp_host": smtp_host, "smtp_port": smtp_port, "smtp_use_tls": smtp_use_tls,
                "smtp_username": smtp_username, "twilio_account_sid": twilio_account_sid,
                "twilio_from": twilio_from, "credentials_ciphertext": credentials_ciphertext,
                "enabled": enabled,
            }
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "FROM TENANT_NOTIFICATION_CONFIGS" in query.upper():
            tenant_id, channel = args
            return self._configs.get((tenant_id, channel))
        return None

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

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


def _token(role: Role, tenant_id: str | None = _TENANT_ID) -> str:
    claims = AuthClaims(subject="admin-1", role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=_TEST_JWT_SECRET, ttl_seconds=300)
    return token


# ==============================================================================
# Repository -- encryption round trip
# ==============================================================================


async def test_upsert_encrypts_password_and_get_decrypts() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        claims = _claims()

        await upsert_notification_config(
            db,
            claims,
            channel="email",
            provider="smtp",
            from_address="bot@dev.local",
            from_name="Chatbot",
            smtp_host="localhost",
            smtp_port=1025,
            smtp_use_tls=False,
            smtp_username="bot",
            twilio_account_sid=None,
            twilio_from=None,
            credentials="s3cret-password",
            enabled=True,
        )

        stored_ciphertext = db._configs[(_TENANT_ID, "email")]["credentials_ciphertext"]
        assert stored_ciphertext != "s3cret-password"
        assert stored_ciphertext is not None

        config = await get_notification_config(db, claims, "email")
        assert config is not None
        assert config.credentials == "s3cret-password"
        assert config.provider == "smtp"
        assert config.smtp_host == "localhost"
        assert config.channel == "email"


async def test_get_returns_none_when_unset() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        config = await get_notification_config(db, _claims(), "email")
        assert config is None


async def test_global_caller_raises_validation_error() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        global_claims = AuthClaims(subject="root", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await get_notification_config(db, global_claims, "email")

        with pytest.raises(ValidationError):
            await upsert_notification_config(
                db,
                global_claims,
                channel="email",
                provider="log",
                from_address=None,
                from_name=None,
                smtp_host=None,
                smtp_port=None,
                smtp_use_tls=True,
                smtp_username=None,
                twilio_account_sid=None,
                twilio_from=None,
                credentials="",
                enabled=True,
            )


async def test_tenant_scoped_no_cross_tenant_read() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        claims_a = _claims(_TENANT_ID)
        claims_b = _claims(_OTHER_TENANT_ID)

        await upsert_notification_config(
            db, claims_a, channel="email", provider="log", from_address=None, from_name=None,
            smtp_host=None, smtp_port=None, smtp_use_tls=True, smtp_username=None,
            twilio_account_sid=None, twilio_from=None, credentials="", enabled=True,
        )

        config_b = await get_notification_config(db, claims_b, "email")
        assert config_b is None


# ==============================================================================
# Multi-channel per tenant (S9.3)
# ==============================================================================


async def test_tenant_may_hold_both_email_and_sms_rows() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        claims = _claims()

        await upsert_notification_config(
            db, claims, channel="email", provider="smtp", from_address="bot@dev.local",
            from_name="Chatbot", smtp_host="localhost", smtp_port=1025, smtp_use_tls=False,
            smtp_username="bot", twilio_account_sid=None, twilio_from=None,
            credentials="email-secret-val", enabled=True,
        )
        await upsert_notification_config(
            db, claims, channel="sms", provider="twilio", from_address=None, from_name=None,
            smtp_host=None, smtp_port=None, smtp_use_tls=True, smtp_username=None,
            twilio_account_sid="ACxxxx", twilio_from="+15550001111",
            credentials="sms-secret-val", enabled=True,
        )

        email_config = await get_notification_config(db, claims, "email")
        sms_config = await get_notification_config(db, claims, "sms")

        assert email_config is not None
        assert email_config.provider == "smtp"
        assert email_config.channel == "email"
        assert sms_config is not None
        assert sms_config.provider == "twilio"
        assert sms_config.channel == "sms"
        assert sms_config.twilio_account_sid == "ACxxxx"
        assert sms_config.twilio_from == "+15550001111"
        assert sms_config.credentials == "sms-secret-val"


async def test_email_row_shape_unchanged_after_rekey() -> None:
    _reset_settings()
    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        db = _StubDatabase()
        claims = _claims()

        await upsert_notification_config(
            db, claims, channel="email", provider="log", from_address=None, from_name=None,
            smtp_host=None, smtp_port=None, smtp_use_tls=True, smtp_username=None,
            twilio_account_sid=None, twilio_from=None, credentials="", enabled=True,
        )

        config = await get_notification_config(db, claims, "email")
        assert config is not None
        assert config.provider == "log"
        assert config.twilio_account_sid is None
        assert config.twilio_from is None


# ==============================================================================
# Route -- PUT /admin/notifications/config
# ==============================================================================


async def test_client_admin_can_set_config() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {
        "provider": "smtp",
        "from_address": "bot@dev.local",
        "from_name": "Chatbot",
        "smtp_host": "localhost",
        "smtp_port": 1025,
        "smtp_use_tls": False,
        "smtp_username": "bot",
        "credentials": "s3cret-password",
        "enabled": True,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/notifications/config", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "smtp"
    assert data["from_address"] == "bot@dev.local"
    assert data["smtp_host"] == "localhost"
    assert data["channel"] == "email"  # back-compat: no channel in body -> email row
    assert "credentials" not in data
    assert "credentials_ciphertext" not in data
    assert "password" not in data
    assert "s3cret-password" not in response.text


async def test_put_with_no_channel_still_targets_email_row() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {"provider": "log", "enabled": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/notifications/config", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 200
    assert response.json()["channel"] == "email"
    assert (_TENANT_ID, "email") in db._configs


async def test_put_sms_channel_echoes_channel_and_twilio_fields_not_token() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {
        "channel": "sms",
        "provider": "twilio",
        "twilio_account_sid": "ACxxxx",
        "twilio_from": "+15550001111",
        "credentials": "sms-secret-val",
        "enabled": True,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_ADMIN)
        response = await client.put(
            "/admin/notifications/config", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "sms"
    assert data["provider"] == "twilio"
    assert data["twilio_account_sid"] == "ACxxxx"
    assert data["twilio_from"] == "+15550001111"
    assert "credentials" not in data
    assert "credentials_ciphertext" not in data
    assert "sms-secret-val" not in response.text

    # The email row (if any) is untouched -- sms upserts its OWN row.
    assert (_TENANT_ID, "sms") in db._configs
    assert (_TENANT_ID, "email") not in db._configs


async def test_client_agent_forbidden() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {"provider": "log", "enabled": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.CLIENT_AGENT)
        response = await client.put(
            "/admin/notifications/config", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 403


async def test_visitor_forbidden() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {"provider": "log", "enabled": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = _token(Role.VISITOR)
        response = await client.put(
            "/admin/notifications/config", json=body, cookies={"access_token": token}
        )

    assert response.status_code == 403


async def test_no_auth_returns_401() -> None:
    db = _StubDatabase()
    app = _build_app(db)

    body = {"provider": "log", "enabled": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/admin/notifications/config", json=body)

    assert response.status_code == 401
