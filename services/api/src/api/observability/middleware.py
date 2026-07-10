"""HTTP metrics middleware -- records request latency + counts.

An ASGI/HTTP middleware function (mirrors the existing ``@app.middleware("http")``
blocks in ``app.py``) that times the request around ``call_next``, then records
the metric with the route template (not the raw path).
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import Request, Response

from api.observability.metrics import record_request


async def metrics_middleware(request: Request, call_next: Any) -> Response:
    """Time the request, then record HTTP metrics with low-cardinality labels."""
    start = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:
        # Record a 500 for unhandled exceptions, then re-raise.
        route = _get_route(request)
        duration = time.perf_counter() - start
        record_request(
            method=request.method,
            route=route,
            status=500,
            duration_seconds=duration,
        )
        raise

    route = _get_route(request)
    duration = time.perf_counter() - start
    record_request(
        method=request.method,
        route=route,
        status=response.status_code,
        duration_seconds=duration,
    )
    return response


def _get_route(request: Request) -> str:
    """Return the matched route template, or ``__unmatched__``."""
    route = request.scope.get("route")
    if route is not None:
        path = getattr(route, "path", None)
        if path is not None:
            return str(path)
    return "__unmatched__"
