"""Unit tests for cache-aside helpers (tenant-scoped keys + in-memory fallback)."""
from redis.exceptions import RedisError

from common.auth import AuthClaims, Role
from common.cache import FallbackCache, InMemoryCache, build_cache, cache_key


def _claims(role: Role, tenant_id: str | None) -> AuthClaims:
    return AuthClaims(subject="s", role=role, tenant_id=tenant_id)


# ----------------------------------------------------------------- cache_key

def test_cache_key_is_tenant_scoped() -> None:
    key = cache_key(_claims(Role.CLIENT_ADMIN, "tenant-a"), "lead", "123")
    assert key == "tenant:tenant-a:lead:123"


def test_cache_keys_differ_across_tenants() -> None:
    a = cache_key(_claims(Role.CLIENT_AGENT, "tenant-a"), "lead", "1")
    b = cache_key(_claims(Role.CLIENT_AGENT, "tenant-b"), "lead", "1")
    assert a != b


def test_cache_key_global_admin_scope() -> None:
    key = cache_key(_claims(Role.PLATFORM_ADMIN, None), "tenants")
    assert key == "tenant:global:tenants"


# ------------------------------------------------------------- InMemoryCache

async def test_inmemory_set_get_delete() -> None:
    c = InMemoryCache()
    await c.set("k", "v", ttl=60)
    assert await c.get("k") == "v"
    await c.delete("k")
    assert await c.get("k") is None


async def test_inmemory_get_missing_returns_none() -> None:
    assert await InMemoryCache().get("nope") is None


async def test_inmemory_ttl_expiry() -> None:
    now = {"t": 1000.0}
    c = InMemoryCache(time_fn=lambda: now["t"])
    await c.set("k", "v", ttl=10)
    now["t"] = 1009.0
    assert await c.get("k") == "v"
    now["t"] = 1011.0
    assert await c.get("k") is None


async def test_get_or_set_loads_once_then_caches() -> None:
    c = InMemoryCache()
    calls = {"n": 0}

    async def loader() -> str:
        calls["n"] += 1
        return "loaded"

    assert await c.get_or_set("k", 60, loader) == "loaded"
    assert await c.get_or_set("k", 60, loader) == "loaded"
    assert calls["n"] == 1  # loader not called on cache hit


async def test_invalidate_prefix() -> None:
    c = InMemoryCache()
    await c.set("tenant:a:lead:1", "x", ttl=60)
    await c.set("tenant:a:lead:2", "y", ttl=60)
    await c.set("tenant:b:lead:1", "z", ttl=60)
    await c.invalidate("tenant:a:lead:*")
    assert await c.get("tenant:a:lead:1") is None
    assert await c.get("tenant:a:lead:2") is None
    assert await c.get("tenant:b:lead:1") == "z"


# ------------------------------------------------------------- FallbackCache

class _FailingCache:
    async def get(self, key: str) -> str | None:
        raise RedisError("down")

    async def set(self, key: str, value: str, ttl: int) -> None:
        raise RedisError("down")

    async def delete(self, key: str) -> None:
        raise RedisError("down")

    async def invalidate(self, pattern: str) -> None:
        raise RedisError("down")


async def test_fallback_used_when_primary_fails() -> None:
    fallback = InMemoryCache()
    cache = FallbackCache(_FailingCache(), fallback)
    await cache.set("k", "v", ttl=60)            # primary raises → fallback
    assert await cache.get("k") == "v"           # served from fallback


# --------------------------------------------------------------- build_cache

def test_build_cache_without_redis_is_in_memory() -> None:
    assert isinstance(build_cache(None), InMemoryCache)


def test_build_cache_with_redis_url_is_fallback_wrapped() -> None:
    assert isinstance(build_cache("redis://localhost:6379/0"), FallbackCache)
