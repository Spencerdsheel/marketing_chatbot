"""Cache-aside helpers. Keys are ALWAYS tenant-scoped (CLAUDE.md §3).

- ``cache_key`` builds a ``tenant:<id>:<kind>:<...>`` key so one tenant can never read
  another's cached data.
- ``Cache`` is the protocol; ``InMemoryCache`` (dev/tests/fallback) and ``RedisCache``
  (prod) implement it.
- ``FallbackCache`` is the *explicit* infrastructure fallback: when Redis errors, it
  degrades to an in-memory cache rather than failing the request (CLAUDE.md §3 —
  infrastructure fallbacks are allowed and must be explicit).

Invalidate on mutation, never on read.
"""
from __future__ import annotations

import fnmatch
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from redis.exceptions import RedisError

from common.auth import AuthClaims
from common.logging import get_logger

_log = get_logger("common.cache")

Loader = Callable[[], Awaitable[str]]


def cache_key(claims: AuthClaims, kind: str, *parts: str) -> str:
    """Build a tenant-scoped cache key. Global admin uses the ``global`` scope."""
    scope = claims.tenant_id if claims.tenant_id is not None else "global"
    segments = ["tenant", scope, kind, *parts]
    return ":".join(segments)


@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def invalidate(self, pattern: str) -> None: ...


async def cache_get_or_set(cache: Cache, key: str, ttl: int, loader: Loader) -> str:
    """Return the cached value, or load + store it (cache-aside)."""
    cached = await cache.get(key)
    if cached is not None:
        return cached
    value = await loader()
    await cache.set(key, value, ttl)
    return value


class InMemoryCache:
    """Process-local cache. Used for dev, tests, and as the Redis fallback."""

    def __init__(self, *, time_fn: Callable[[], float] = time.monotonic) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self._time = time_fn

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        expires_at = self._time() + ttl if ttl > 0 else None
        self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def invalidate(self, pattern: str) -> None:
        for key in [k for k in self._store if fnmatch.fnmatchcase(k, pattern)]:
            self._store.pop(key, None)

    async def get_or_set(self, key: str, ttl: int, loader: Loader) -> str:
        return await cache_get_or_set(self, key, ttl, loader)


class RedisCache:
    """Redis-backed cache. Raises ``RedisError`` on connectivity failures."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)  # type: ignore[attr-defined]
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl: int) -> None:
        if ttl > 0:
            await self._client.set(key, value, ex=ttl)  # type: ignore[attr-defined]
        else:
            await self._client.set(key, value)  # type: ignore[attr-defined]

    async def delete(self, key: str) -> None:
        await self._client.delete(key)  # type: ignore[attr-defined]

    async def invalidate(self, pattern: str) -> None:
        async for key in self._client.scan_iter(match=pattern):  # type: ignore[attr-defined]
            await self._client.delete(key)  # type: ignore[attr-defined]

    async def get_or_set(self, key: str, ttl: int, loader: Loader) -> str:
        return await cache_get_or_set(self, key, ttl, loader)


class FallbackCache:
    """Use ``primary`` (Redis); on ``RedisError`` degrade to ``fallback`` (in-memory)."""

    def __init__(self, primary: Cache, fallback: Cache) -> None:
        self._primary = primary
        self._fallback = fallback

    async def get(self, key: str) -> str | None:
        try:
            return await self._primary.get(key)
        except RedisError:
            _log.warning(
                "cache primary unavailable; using in-memory fallback",
                extra={"event": "cache_fallback"},
            )
            return await self._fallback.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            await self._primary.set(key, value, ttl)
        except RedisError:
            await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        try:
            await self._primary.delete(key)
        except RedisError:
            await self._fallback.delete(key)

    async def invalidate(self, pattern: str) -> None:
        try:
            await self._primary.invalidate(pattern)
        except RedisError:
            await self._fallback.invalidate(pattern)

    async def get_or_set(self, key: str, ttl: int, loader: Loader) -> str:
        return await cache_get_or_set(self, key, ttl, loader)


def build_cache(redis_url: str | None) -> Cache:
    """Construct the cache for this process from config.

    No ``redis_url`` → in-memory only. With a URL → Redis primary wrapped in a
    FallbackCache so a Redis outage degrades gracefully instead of erroring.
    """
    if not redis_url:
        return InMemoryCache()
    from redis.asyncio import from_url

    client = from_url(redis_url)
    return FallbackCache(RedisCache(client), InMemoryCache())
