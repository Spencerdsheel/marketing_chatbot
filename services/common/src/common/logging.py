"""Structured JSON logging with request-scoped correlation context.

Log in JSON from day one (KB 02/03/08). A ``correlation_id`` (set by the gateway) plus
``tenant_id`` and ``user_id``/``visitor_id`` are carried in ContextVars and auto-injected
into every line. To avoid leaking secrets/PII, the formatter only emits a curated set of
extra fields — arbitrary attributes attached to a record are dropped.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
from collections.abc import Iterator
from contextvars import ContextVar, Token
from typing import Any

# Request-scoped context. None means "not set" → omitted from the log line.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)

_CONTEXT_VARS: dict[str, ContextVar[str | None]] = {
    "correlation_id": _correlation_id,
    "tenant_id": _tenant_id,
    "user_id": _user_id,
}

# Safe operational fields a caller may attach via ``extra=...``. Anything else is
# dropped so secrets/PII can't accidentally end up in logs.
_ALLOWED_EXTRA = frozenset(
    {"endpoint", "method", "status_code", "duration_ms", "event", "task", "attempt"}
)

# Standard LogRecord attributes (so we know what is an "extra").
_RESERVED = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, var in _CONTEXT_VARS.items():
            value = var.get()
            if value is not None:
                payload[name] = value
        for key, value in record.__dict__.items():
            if key in _ALLOWED_EXTRA and key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that emits JSON to stderr. Idempotent (no duplicate handlers)."""
    logger = logging.getLogger(name)
    if not any(getattr(h, "_chatbot_json", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._chatbot_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def bind_log_context(
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Token[str | None]]:
    """Set the given context fields (only those provided). Returns reset tokens."""
    updates = {
        "correlation_id": correlation_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
    tokens: dict[str, Token[str | None]] = {}
    for name, value in updates.items():
        if value is not None:
            tokens[name] = _CONTEXT_VARS[name].set(value)
    return tokens


def clear_log_context() -> None:
    """Reset all context fields to unset."""
    for var in _CONTEXT_VARS.values():
        var.set(None)


@contextlib.contextmanager
def log_context(
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> Iterator[None]:
    """Bind context for the duration of the block, restoring prior values on exit."""
    tokens = bind_log_context(
        correlation_id=correlation_id, tenant_id=tenant_id, user_id=user_id
    )
    try:
        yield
    finally:
        for name, token in tokens.items():
            _CONTEXT_VARS[name].reset(token)
