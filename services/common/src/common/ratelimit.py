"""Sliding-window rate limiter (Redis-backed, in-memory fallback).

A shared primitive that multiple tiers (widget, auth, admin, global) can reuse.
Redis outage degrades to per-process in-memory limiting (fail-open, per CLAUDE.md
infrastructure-fallback rules -- unlike the auth blacklist which is fail-closed).
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol
from uuid import uuid4

from redis.exceptions import RedisError

from common.errors import RateLimitError
from common.logging import get_logger

_log = get_logger("common.ratelimit")


class RateLimiter(Protocol):
    async def check(self, key: str, *, limit: int, window_seconds: int) -> None: ...


class RedisRateLimiter:
    """Sliding-window log via Redis sorted set.

    Key pattern: ``ratelimit:<key>``. Each call: evict old entries, add a new
    one with the current timestamp as score, count entries, set expiry. If the
    count exceeds the limit, raise ``RateLimitError`` with a ``retry_after``
    derived from the oldest entry still in the window.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.time()
        redis_key = f"ratelimit:{key}"
        window_start = now - window_seconds

        pipe = self._client.pipeline(transaction=True)  # type: ignore[attr-defined]
        pipe.zremrangebyscore(redis_key, 0, window_start)
        member = f"{now}:{uuid4().hex}"
        pipe.zadd(redis_key, {member: now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()

        count: int = results[2]
        if count > limit:
            # Find the earliest score to compute retry_after
            earliest = await self._client.zrange(redis_key, 0, 0, withscores=True)  # type: ignore[attr-defined]
            if earliest:
                earliest_score = earliest[0][1]
                retry_after = math.ceil(window_seconds - (now - earliest_score))
            else:
                retry_after = window_seconds
            raise RateLimitError(
                "Rate limit exceeded.",
                retry_after=max(1, retry_after),
            )


class InMemoryRateLimiter:
    """Process-local sliding-window log. Used for dev, tests, and Redis fallback."""

    def __init__(self, *, time_fn: Callable[[], float] = time.monotonic) -> None:
        self._logs: dict[str, deque[float]] = {}
        self._time = time_fn

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = self._time()
        log = self._logs.setdefault(key, deque())

        # Evict entries outside the window
        cutoff = now - window_seconds
        while log and log[0] <= cutoff:
            log.popleft()

        if len(log) >= limit:
            retry_after = math.ceil(window_seconds - (now - log[0]))
            raise RateLimitError(
                "Rate limit exceeded.",
                retry_after=max(1, retry_after),
            )

        log.append(now)


class FallbackRateLimiter:
    """Use ``primary`` (Redis); on ``RedisError`` degrade to ``fallback`` (in-memory)."""

    def __init__(self, primary: RateLimiter, fallback: RateLimiter) -> None:
        self._primary = primary
        self._fallback = fallback

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        try:
            await self._primary.check(key, limit=limit, window_seconds=window_seconds)
        except RateLimitError:
            # A real limit hit -- propagate, don't swallow it.
            raise
        except RedisError:
            _log.warning(
                "rate-limiter primary unavailable; using in-memory fallback",
                extra={"event": "ratelimit_fallback"},
            )
            await self._fallback.check(key, limit=limit, window_seconds=window_seconds)


def build_rate_limiter(redis_client: object | None) -> RateLimiter:
    """Construct the rate limiter for this process.

    No redis client → in-memory only. With a client → Redis primary wrapped in
    a FallbackRateLimiter so a Redis outage degrades gracefully.
    """
    if redis_client is None:
        return InMemoryRateLimiter()
    return FallbackRateLimiter(RedisRateLimiter(redis_client), InMemoryRateLimiter())
