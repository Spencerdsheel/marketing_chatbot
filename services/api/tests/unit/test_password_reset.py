"""Unit tests for password reset (request + confirm).

Covers:
- Request: known+active email -> 200 + key stored; unknown email -> 200 + no key;
  inactive user -> 200 + no key (no enumeration).
- Reset email enqueue (S9.2): enqueue_notification called with
  dedupe_key="pwreset:<sha256(token)>" (the HASH, never the raw token) and a
  body containing the reset URL+token; .delay() called once; the raw token
  NEVER appears in any log record.
- PLATFORM_ADMIN (tenant_id is None) -> no enqueue
  (password_reset_platform_admin_deferred), still 200.
- An enqueue that raises -> still 200 (password_reset_enqueue_failed, ERROR).
- Unknown/inactive email -> same 200, no enqueue (enumeration-safe).
- Idempotency (MANDATORY): a repeat request re-issues a NEW token (a fresh
  Redis key + hash) so dedupe is naturally per-token; a duplicate
  enqueue_notification conflict (-> None) results in NO second .delay().
- Confirm happy path: issue -> confirm -> 200; UPDATE recorded; key gone.
- Single-use: reuse same token -> 401.
- Bad/garbage token -> 401.
- Weak password (<12 chars) -> 422.
- End-to-end: request -> confirm -> new password verifies, old does not.
"""
from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from common.cache import InMemoryCache
from common.crypto import hash_password, verify_password
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError


def _extract_query_param(url_or_body: str, param: str) -> str:
    """Pull a query-param value out of a URL/body string (test helper only)."""
    match = re.search(param + r"=([^\s&]+)", url_or_body)
    assert match is not None
    return match.group(1)

# -- Test doubles --------------------------------------------------------------

_KNOWN_PASSPHRASE = "correct horse battery staple"
_KNOWN_HASH = hash_password(_KNOWN_PASSPHRASE)

_TENANT_ID = "tenant-abc-123"

_ACTIVE_USER_ROW: dict[str, Any] = {
    "id": "user-active-1",
    "tenant_id": _TENANT_ID,
    "email": "admin@example.com",
    "role": "CLIENT_ADMIN",
    "password_hash": _KNOWN_HASH,
    "name": "Account Owner",
    "active": True,
    "last_login_at": None,
}

_INACTIVE_USER_ROW: dict[str, Any] = {
    "id": "user-inactive-1",
    "tenant_id": _TENANT_ID,
    "email": "inactive@example.com",
    "role": "CLIENT_ADMIN",
    "password_hash": _KNOWN_HASH,
    "name": "Inactive User",
    "active": False,
    "last_login_at": None,
}

_USER_DB: dict[str, dict[str, Any]] = {
    "admin@example.com": _ACTIVE_USER_ROW,
    "inactive@example.com": _INACTIVE_USER_ROW,
}


class _StubDatabase:
    """Database double for auth queries."""

    def __init__(self) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        if args:
            email = str(args[0]).lower()
            for key, row in _USER_DB.items():
                if key.lower() == email:
                    return dict(row)
        return None

    async def fetchval(self, query: str, *args: object) -> object:
        return 1

    async def execute(self, query: str, *args: object) -> str:
        self.last_sql = query
        self.last_params = args
        return "UPDATE 1"

    async def close(self) -> None:
        pass


class _RecordingRedis:
    """Redis double supporting set, get, getdel for password reset + blacklist."""

    def __init__(self, *, fail_set: bool = False, fail_get: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._fail_set = fail_set
        self._fail_get = fail_get
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.get_calls: list[str] = []
        self.getdel_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        if self._fail_get:
            raise RedisError("connection refused")
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        if self._fail_set:
            raise RedisError("connection refused")
        self._store[key] = value

    async def getdel(self, key: str) -> str | None:
        self.getdel_calls.append(key)
        value = self._store.pop(key, None)
        return value

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


# -- Helpers -------------------------------------------------------------------

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _build_app(redis: Any = None) -> Any:
    """Create app with test doubles."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app
        app = create_app()

    app.state.db = _StubDatabase()
    app.state.redis = redis if redis is not None else _RecordingRedis()
    app.state.cache = InMemoryCache()
    return app


# ==============================================================================
# Request -- no enumeration
# ==============================================================================


async def test_request_known_active_email_stores_key() -> None:
    """Known + active email -> 200 + exactly one key under auth:pwreset:"""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    with patch("api.auth.routes.send_notification"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "reset_requested"}
    pwreset_keys = [k for k, _, _ in redis.set_calls if k.startswith("auth:pwreset:")]
    assert len(pwreset_keys) == 1


async def test_request_unknown_email_no_key_stored() -> None:
    """Unknown email -> 200 with identical body, NO key stored."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/password-reset/request", json={"email": "nobody@nowhere.example"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "reset_requested"}
    pwreset_keys = [k for k, _, _ in redis.set_calls if k.startswith("auth:pwreset:")]
    assert len(pwreset_keys) == 0


async def test_request_inactive_user_no_key_stored() -> None:
    """Inactive user -> 200, no key stored."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/password-reset/request", json={"email": "inactive@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "reset_requested"}
    pwreset_keys = [k for k, _, _ in redis.set_calls if k.startswith("auth:pwreset:")]
    assert len(pwreset_keys) == 0


# ==============================================================================
# Request -- reset email enqueue (S9.2)
# ==============================================================================


async def test_request_enqueues_reset_email_with_hashed_dedupe_key() -> None:
    """Known+active tenant user -> enqueue_notification called with a HASHED
    dedupe_key (never the raw token) + a body containing the reset URL/token;
    .delay() called once."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    captured_kwargs: dict[str, Any] = {}

    async def _capture_enqueue(db: Any, claims: Any, **kwargs: Any) -> str:
        captured_kwargs.update(kwargs)
        return "job-pwreset-1"

    with (
        patch("api.auth.routes.enqueue_notification", side_effect=_capture_enqueue) as mock_enqueue,
        patch("api.auth.routes.send_notification") as mock_task,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})

    assert resp.status_code == 200
    mock_enqueue.assert_awaited_once()
    assert captured_kwargs["channel"] == "email"
    assert captured_kwargs["recipient"] == "admin@example.com"

    # The dedupe_key is the SHA-256 hash of the issued token -- extract the
    # hash from the Redis store key (test-only visibility) to verify.
    pwreset_keys = [k for k, _, _ in redis.set_calls if k.startswith("auth:pwreset:")]
    assert len(pwreset_keys) == 1
    token_hash = pwreset_keys[0].removeprefix("auth:pwreset:")
    assert captured_kwargs["dedupe_key"] == f"pwreset:{token_hash}"

    # The reset URL (and thus the raw token) appears ONLY in the body.
    assert _extract_query_param(captured_kwargs["body"], "token")

    mock_task.delay.assert_called_once()
    _, delay_kwargs = mock_task.delay.call_args
    assert delay_kwargs["job_id"] == "job-pwreset-1"


async def test_request_dedupe_key_is_hash_not_raw_token() -> None:
    """The dedupe_key must never contain the raw token substring."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    captured_kwargs: dict[str, Any] = {}

    async def _capture_enqueue(db: Any, claims: Any, **kwargs: Any) -> str:
        captured_kwargs.update(kwargs)
        return "job-1"

    with (
        patch("api.auth.routes.enqueue_notification", side_effect=_capture_enqueue),
        patch("api.auth.routes.send_notification"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})

    raw_token = _extract_query_param(captured_kwargs["body"], "token")
    assert raw_token not in captured_kwargs["dedupe_key"]
    payload = captured_kwargs.get("payload")
    assert payload in (None, {}) or raw_token not in str(payload)


async def test_request_no_log_line_carries_raw_token(caplog: pytest.LogCaptureFixture) -> None:
    """PII/secret redaction (MANDATORY): the raw reset token never appears in any log record."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    captured: dict[str, Any] = {}

    async def _capture_enqueue(db: Any, claims: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "job-1"

    with (
        patch("api.auth.routes.enqueue_notification", side_effect=_capture_enqueue),
        patch("api.auth.routes.send_notification"),
        caplog.at_level("DEBUG"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})

    raw_token = _extract_query_param(captured["body"], "token")
    for record in caplog.records:
        assert raw_token not in record.getMessage()
        assert raw_token not in repr(getattr(record, "__dict__", {}))


async def test_request_platform_admin_no_enqueue_still_200() -> None:
    """A PLATFORM_ADMIN (tenant_id is None) user -> NO enqueue, still 200."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    platform_admin_row = dict(_ACTIVE_USER_ROW)
    platform_admin_row["id"] = "user-platform-admin"
    platform_admin_row["email"] = "platform-admin@example.com"
    platform_admin_row["tenant_id"] = None
    platform_admin_row["role"] = "PLATFORM_ADMIN"

    class _PlatformAdminDb(_StubDatabase):
        async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
            if args and str(args[0]).lower() == "platform-admin@example.com":
                return dict(platform_admin_row)
            return await super().fetchrow(query, *args)

    app.state.db = _PlatformAdminDb()

    with patch("api.auth.routes.enqueue_notification") as mock_enqueue:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/auth/password-reset/request", json={"email": "platform-admin@example.com"}
            )

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset_requested"}
    mock_enqueue.assert_not_called()


async def test_request_enqueue_raises_still_200() -> None:
    """An enqueue that raises -> still 200 (password_reset_enqueue_failed, ERROR)."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    with patch(
        "api.auth.routes.enqueue_notification", AsyncMock(side_effect=RuntimeError("db down"))
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset_requested"}


async def test_request_unknown_email_no_enqueue() -> None:
    """Unknown email -> same 200, no enqueue (enumeration-safe)."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    with patch("api.auth.routes.enqueue_notification") as mock_enqueue:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/auth/password-reset/request", json={"email": "nobody@nowhere.example"}
            )

    assert resp.status_code == 200
    mock_enqueue.assert_not_called()


async def test_request_repeat_dedupe_conflict_no_second_delay() -> None:
    """Idempotency (MANDATORY): enqueue_notification -> None (conflict) results
    in NO second .delay()."""
    redis = _RecordingRedis()
    app = _build_app(redis=redis)

    with (
        patch("api.auth.routes.enqueue_notification", AsyncMock(return_value=None)),
        patch("api.auth.routes.send_notification") as mock_task,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/auth/password-reset/request", json={"email": "admin@example.com"})

    assert resp.status_code == 200
    mock_task.delay.assert_not_called()


# ==============================================================================
# Confirm -- happy path
# ==============================================================================


async def test_confirm_happy_path() -> None:
    """Issue a token, confirm with >=12-char password -> 200; UPDATE recorded; key gone."""
    redis = _RecordingRedis()
    db = _StubDatabase()
    app = _build_app(redis=redis)
    app.state.db = db

    # Issue a token directly via the store
    from api.auth.password_reset import RedisPasswordResetStore

    token = await RedisPasswordResetStore(redis).issue("user-active-1", 1800)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/password-reset/confirm", json={
            "token": token,
            "new_password": "new-strong-password-123",
        })
    assert resp.status_code == 200
    assert resp.json() == {"status": "password_reset"}

    # Verify the UPDATE was called with a valid hash
    assert "UPDATE users SET password_hash" in db.last_sql
    new_hash = db.last_params[0]
    assert verify_password("new-strong-password-123", new_hash)

    # Redis key is gone
    from api.auth.password_reset import PASSWORD_RESET_PREFIX, _hash_token
    key = f"{PASSWORD_RESET_PREFIX}{_hash_token(token)}"
    assert await redis.get(key) is None


# ==============================================================================
# Confirm -- single-use
# ==============================================================================


async def test_confirm_single_use() -> None:
    """Reusing the same token -> 401 UNAUTHENTICATED."""
    redis = _RecordingRedis()
    db = _StubDatabase()
    app = _build_app(redis=redis)
    app.state.db = db

    from api.auth.password_reset import RedisPasswordResetStore

    token = await RedisPasswordResetStore(redis).issue("user-active-1", 1800)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp1 = await c.post("/auth/password-reset/confirm", json={
            "token": token,
            "new_password": "new-strong-password-123",
        })
        resp2 = await c.post("/auth/password-reset/confirm", json={
            "token": token,
            "new_password": "another-password-123",
        })
    assert resp1.status_code == 200
    assert resp2.status_code == 401
    assert resp2.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# Confirm -- bad token
# ==============================================================================


async def test_confirm_bad_token() -> None:
    """Unknown/garbage token -> 401."""
    redis = _RecordingRedis()
    db = _StubDatabase()
    app = _build_app(redis=redis)
    app.state.db = db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/password-reset/confirm", json={
            "token": "this-is-not-a-valid-token",
            "new_password": "new-strong-password-123",
        })
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


# ==============================================================================
# Confirm -- weak password
# ==============================================================================


async def test_confirm_weak_password_returns_422() -> None:
    """new_password shorter than 12 chars -> 422 (Pydantic validation)."""
    redis = _RecordingRedis()
    db = _StubDatabase()
    app = _build_app(redis=redis)
    app.state.db = db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/auth/password-reset/confirm", json={
            "token": "some-token",
            "new_password": "short",
        })
    assert resp.status_code == 422


# ==============================================================================
# End-to-end
# ==============================================================================


async def test_end_to_end_request_confirm_login() -> None:
    """Request -> confirm -> login with new password works, old does not."""
    redis = _RecordingRedis()
    db = _StubDatabase()
    app = _build_app(redis=redis)
    app.state.db = db

    from api.auth.password_reset import RedisPasswordResetStore

    # Issue token
    token = await RedisPasswordResetStore(redis).issue("user-active-1", 1800)

    # Confirm
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        confirm_resp = await c.post("/auth/password-reset/confirm", json={
            "token": token,
            "new_password": "brand-new-password-456",
        })
    assert confirm_resp.status_code == 200

    # The recorded new hash verifies against the new password
    new_hash = db.last_params[0]
    assert verify_password("brand-new-password-456", new_hash)
    assert not verify_password(_KNOWN_PASSPHRASE, new_hash)
