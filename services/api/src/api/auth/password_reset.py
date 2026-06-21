"""Password reset token store (Redis-only, single-use via GETDEL).

Tokens are stored as SHA-256 hashes -- a Redis dump must not reveal a usable
token. The ``consume`` operation is atomic (``GETDEL``) so each token is
single-use.

This is a temporary dev bridge until Phase 9 email delivery. The token is
NEVER returned in an HTTP response body; it is surfaced via logs only when
the dev-only ``auth_reset_token_log`` setting is True.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Protocol

from common.errors import InternalServerError
from fastapi import Request

PASSWORD_RESET_PREFIX = "auth:pwreset:"  # noqa: S105


def _hash_token(token: str) -> str:
    """SHA-256 hex digest of the raw reset token."""
    return hashlib.sha256(token.encode()).hexdigest()


class PasswordResetStore(Protocol):
    async def issue(self, user_id: str, ttl_seconds: int) -> str: ...
    async def consume(self, token: str) -> str | None: ...


class RedisPasswordResetStore:
    """Redis-backed password reset token store.

    Stores only SHA-256 hashes; consumes atomically via GETDEL.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    async def issue(self, user_id: str, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        key = f"{PASSWORD_RESET_PREFIX}{_hash_token(token)}"
        await self._client.set(key, user_id, ex=max(1, ttl_seconds))  # type: ignore[attr-defined]
        return token

    async def consume(self, token: str) -> str | None:
        raw = await self._client.getdel(  # type: ignore[attr-defined]
            f"{PASSWORD_RESET_PREFIX}{_hash_token(token)}"
        )
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode()
        return str(raw)


def get_password_reset_store(request: Request) -> PasswordResetStore:
    """Resolve the ``PasswordResetStore`` for this request.

    Raises ``InternalServerError`` if Redis is not configured (same posture as
    ``get_token_blacklist``).
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise InternalServerError("Password reset requires Redis.")
    return RedisPasswordResetStore(redis_client)
