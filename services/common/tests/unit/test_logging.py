"""Unit tests for structured JSON logging + correlation context."""
import json
import logging

from common.logging import (
    JsonFormatter,
    bind_log_context,
    clear_log_context,
    get_logger,
    log_context,
)


def _record(msg: str = "hello", **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="svc.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_get_logger_returns_logger() -> None:
    assert isinstance(get_logger("svc.x"), logging.Logger)


def test_get_logger_is_idempotent_no_duplicate_handlers() -> None:
    a = get_logger("svc.dup")
    n = len(a.handlers)
    b = get_logger("svc.dup")
    assert a is b
    assert len(b.handlers) == n


def test_formatter_emits_valid_json_with_base_fields() -> None:
    out = JsonFormatter().format(_record("a message"))
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "svc.test"
    assert payload["message"] == "a message"
    assert "timestamp" in payload


def test_context_fields_injected() -> None:
    clear_log_context()
    bind_log_context(correlation_id="corr-1", tenant_id="tenant-a", user_id="u1")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
        assert payload["correlation_id"] == "corr-1"
        assert payload["tenant_id"] == "tenant-a"
        assert payload["user_id"] == "u1"
    finally:
        clear_log_context()


def test_context_cleared() -> None:
    bind_log_context(correlation_id="corr-1")
    clear_log_context()
    payload = json.loads(JsonFormatter().format(_record()))
    assert "correlation_id" not in payload


def test_log_context_manager_restores_previous() -> None:
    clear_log_context()
    with log_context(correlation_id="outer"):
        with log_context(correlation_id="inner", tenant_id="t"):
            p = json.loads(JsonFormatter().format(_record()))
            assert p["correlation_id"] == "inner"
            assert p["tenant_id"] == "t"
        p = json.loads(JsonFormatter().format(_record()))
        assert p["correlation_id"] == "outer"
        assert "tenant_id" not in p
    p = json.loads(JsonFormatter().format(_record()))
    assert "correlation_id" not in p


def test_whitelisted_extra_included_arbitrary_dropped() -> None:
    # endpoint is a safe operational field; password must NEVER be logged.
    rec = _record(endpoint="/v1/leads", password="hunter2")
    payload = json.loads(JsonFormatter().format(rec))
    assert payload["endpoint"] == "/v1/leads"
    assert "password" not in payload
    assert "hunter2" not in json.dumps(payload)
