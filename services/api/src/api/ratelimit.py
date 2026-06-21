"""FastAPI glue for the shared rate limiter.

``client_ip`` extracts the caller's IP (X-Forwarded-For first hop behind the
trusted Nginx proxy, else ``request.client.host``). ``enforce_rate_limit`` is
a helper that routes call at the top of their handler to check the limit before
doing any work.
"""
from __future__ import annotations

from common.logging import get_logger
from common.ratelimit import InMemoryRateLimiter, RateLimiter
from fastapi import Request

_log = get_logger("api.ratelimit")


def client_ip(request: Request) -> str:
    """Return the caller's IP address.

    Reads the first hop of ``X-Forwarded-For`` if present (only trusted behind
    the Nginx proxy), otherwise falls back to ``request.client.host``.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def get_rate_limiter(request: Request) -> RateLimiter:
    """Return the process-wide rate limiter, lazily creating an in-memory one
    if the lifespan didn't set one (keeps existing tests working).
    """
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        limiter = InMemoryRateLimiter()
        request.app.state.rate_limiter = limiter
    return limiter


async def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Check the rate limit for the given scope+identifier.

    Raises ``RateLimitError`` (→ 429 + Retry-After) when the limit is exceeded.
    Call this at the top of the handler, before any DB or business logic.
    """
    key = f"{scope}:{identifier}"
    await get_rate_limiter(request).check(
        key, limit=limit, window_seconds=window_seconds
    )
