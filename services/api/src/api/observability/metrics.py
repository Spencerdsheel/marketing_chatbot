"""Prometheus metrics for HTTP request-level observability.

Module-level singletons on the default ``REGISTRY`` so they are defined once
at import time (avoids ``Duplicated timeseries`` when the app is re-created
in tests).  Rendered by the existing ``/metrics`` route.

Labels:
- ``method``: HTTP method (GET, POST, …)
- ``route``: matched route template (e.g. ``/admin/leads/{lead_id}``), or
  ``__unmatched__`` when no route matched (404).  Never the raw path.
- ``status``: numeric HTTP status as a string.
"""
from prometheus_client import Counter, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)


def record_request(
    method: str,
    route: str,
    status: int,
    duration_seconds: float,
) -> None:
    """Increment the request counter and observe the latency histogram."""
    status_str = str(status)
    HTTP_REQUESTS_TOTAL.labels(
        method=method, route=route, status=status_str,
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=method, route=route,
    ).observe(duration_seconds)
