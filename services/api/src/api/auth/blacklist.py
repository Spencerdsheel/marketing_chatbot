"""Token blacklist abstraction (Redis-only, fail-closed).

A single module that defines the revocation policy exactly once. Both
``get_current_claims`` (read check) and ``POST /auth/logout`` (write) import
from here.

**Fail-closed:** if the blacklist lookup cannot reach Redis, the request is
denied (``AuthenticationError``). Revocation is a security control; a silent
allow is not acceptable.
"""
from __future__ import annotations

import datetime as _dt
from typing import Protocol

from common.errors import AuthenticationError, InternalServerError
from common.logging import get_logger
from fastapi import Request
from redis.exceptions import RedisError

_log = get_logger(__name__)

BLACKLIST_PREFIX = "auth:blacklist:"


class TokenBlacklist(Protocol):
    async def revoke(self, jti: str, ttl_seconds: int) -> None: ...
    async def is_revoked(self, jti: str) -> bool: ...


class RedisTokenBlacklist:
    """Redis-backed token blacklist. Fail-closed on ``RedisError``."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        await self._client.set(  # type: ignore[attr-defined]
            f"{BLACKLIST_PREFIX}{jti}",
            "1",
            ex=max(1, ttl_seconds),
        )

    async def is_revoked(self, jti: str) -> bool:
        try:
            value = await self._client.get(  # type: ignore[attr-defined]
                f"{BLACKLIST_PREFIX}{jti}"
            )
            return value is not None
        except RedisError as err:
            _log.error(
                "blacklist check failed -- denying request (fail-closed)",
                extra={"event": "blacklist_check_error"},
            )
            raise AuthenticationError(
                "Session validation is temporarily unavailable."
            ) from err


def get_token_blacklist(request: Request) -> TokenBlacklist:
    """Resolve the ``TokenBlacklist`` for this request.

    Raises ``InternalServerError`` if Redis is not configured (loud misconfig).
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise InternalServerError("Revocation requires Redis.")
    return RedisTokenBlacklist(redis_client)


def remaining_ttl(exp_raw: object | None) -> int:
    """Return seconds until *exp* expires, minimum 1.

    Accepts both an int/float unix timestamp and a ``datetime``.
    """
    if exp_raw is None:
        return 3600
    if isinstance(exp_raw, _dt.datetime):
        exp_dt = exp_raw
    else:
        exp_ts = float(str(exp_raw))
        exp_dt = _dt.datetime.fromtimestamp(exp_ts, tz=_dt.UTC)
    remaining = int((exp_dt - _dt.datetime.now(_dt.UTC)).total_seconds())
    return max(remaining, 1)
