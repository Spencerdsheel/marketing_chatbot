"""Prometheus metrics for the LLM provider boundary.

Module-level singletons on the default ``REGISTRY`` so they are defined once
at import time (avoids ``Duplicated timeseries`` when the app is re-created
in tests). Rendered by the existing ``/metrics`` route.

Labels:
- ``provider``: ``openai`` | ``anthropic`` | ``azure``
- ``op``: ``generate`` | ``embed`` | ``classify`` | ``stream``
- ``model``: the model/deployment name
- ``kind``: ``input`` | ``output``
"""
from prometheus_client import Counter, Histogram

LLM_REQUEST_DURATION = Histogram(
    "llm_request_duration_seconds",
    "LLM call latency",
    ["provider", "op"],
)

LLM_ERRORS = Counter(
    "llm_errors_total",
    "LLM call errors",
    ["provider", "op"],
)

LLM_TOKENS = Counter(
    "llm_tokens_total",
    "LLM token usage",
    ["provider", "model", "kind"],
)
