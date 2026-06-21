"""Edge middleware — security headers + dynamic per-tenant CORS.

Security headers are applied to **every** response (including errors).
CORS is dynamic: an Origin is allowed iff it appears in some enabled
tenant's ``allowed_origins`` (DB-backed, cached under a global key).
"""
from __future__ import annotations

from common.cache import Cache
from common.db import Database
from common.logging import get_logger
from fastapi import Response

_log = get_logger("api.edge")

# -- Security headers (applied to every response) -----------------------------

SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def apply_security_headers(response: Response) -> None:
    """Set the standard security headers on *response*."""
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value


# -- Dynamic per-tenant CORS --------------------------------------------------

_CORS_CACHE_PREFIX = "cors:origin:"


async def is_known_origin(
    db: Database,
    cache: Cache,
    origin: str,
    *,
    ttl: int,
) -> bool:
    """Return True if *origin* appears in any enabled tenant's allowed_origins.

    Cached under ``cors:origin:<origin>`` (global key — CORS validity is a
    platform-global fact, not tenant-scoped data).
    """
    cache_key = f"{_CORS_CACHE_PREFIX}{origin}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached == "1"

    # DB check: does any enabled tenant list this origin?
    exists = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM tenants WHERE enabled AND $1 = ANY(allowed_origins))",
        origin,
    )
    value = "1" if exists else "0"
    await cache.set(cache_key, value, ttl)
    return bool(exists)


def apply_cors_headers(
    response: Response,
    origin: str,
    *,
    max_age: int,
) -> None:
    """Set CORS headers reflecting a single concrete origin (never ``*``)."""
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Max-Age"] = str(max_age)
