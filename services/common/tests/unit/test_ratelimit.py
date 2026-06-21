"""Unit tests for the shared rate limiter (InMemoryRateLimiter + FallbackRateLimiter)."""
from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from common.errors import RateLimitError
from common.ratelimit import FallbackRateLimiter, InMemoryRateLimiter

# -- InMemoryRateLimiter -------------------------------------------------------


class _TimeKeeper:
    """Injectable clock for deterministic tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


async def test_in_memory_allows_up_to_limit() -> None:
    """Exactly ``limit`` requests pass without raising."""
    clock = _TimeKeeper()
    limiter = InMemoryRateLimiter(time_fn=clock)
    for _ in range(3):
        await limiter.check("test-key", limit=3, window_seconds=60)


async def test_in_memory_raises_on_excess() -> None:
    """The (limit+1)-th request raises RateLimitError with retry_after > 0."""
    clock = _TimeKeeper()
    limiter = InMemoryRateLimiter(time_fn=clock)
    for _ in range(3):
        await limiter.check("test-key", limit=3, window_seconds=60)
    with pytest.raises(RateLimitError) as exc_info:
        await limiter.check("test-key", limit=3, window_seconds=60)
    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after > 0


async def test_in_memory_slides_after_window() -> None:
    """After the window passes, requests are allowed again."""
    clock = _TimeKeeper()
    limiter = InMemoryRateLimiter(time_fn=clock)
    for _ in range(3):
        await limiter.check("test-key", limit=3, window_seconds=60)
    # Advance past the window
    clock.advance(61)
    # Should be allowed again
    await limiter.check("test-key", limit=3, window_seconds=60)


# -- FallbackRateLimiter -------------------------------------------------------


class _FailingPrimary:
    """A primary that always raises RedisError."""

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        raise RedisError("connection refused")


class _LimitHittingPrimary:
    """A primary that always raises RateLimitError (real limit hit)."""

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        raise RateLimitError("Rate limit exceeded.", retry_after=30)


async def test_fallback_degrades_on_redis_error() -> None:
    """When the primary raises RedisError, the fallback handles the call."""
    primary = _FailingPrimary()
    fallback = InMemoryRateLimiter()
    limiter = FallbackRateLimiter(primary, fallback)
    # Should not raise -- fallback handles it
    await limiter.check("test-key", limit=3, window_seconds=60)


async def test_fallback_propagates_rate_limit_error() -> None:
    """A real RateLimitError from the primary is NOT swallowed."""
    primary = _LimitHittingPrimary()
    fallback = InMemoryRateLimiter()
    limiter = FallbackRateLimiter(primary, fallback)
    with pytest.raises(RateLimitError):
        await limiter.check("test-key", limit=3, window_seconds=60)
