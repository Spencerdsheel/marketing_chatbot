"""Unit tests for the optional Sentry integration.

Verifies import-guarded behavior: no-op when DSN is unset or sentry_sdk is
not installed, and proper forwarding when initialized.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from api.observability.sentry import init_sentry


def test_init_sentry_noop_when_dsn_is_none() -> None:
    """init_sentry(None, ...) is a no-op (no error, no init call)."""
    init_sentry(None, "dev")  # should not raise


def test_init_sentry_noop_when_dsn_is_empty() -> None:
    """init_sentry("", ...) is a no-op."""
    init_sentry("", "dev")


def test_init_sentry_calls_sdk_init_when_dsn_provided() -> None:
    """init_sentry with a DSN → calls sentry_sdk.init once."""
    mock_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": mock_sdk}):
        # Re-import to pick up the patched module
        import importlib

        import api.observability.sentry as sentry_mod

        importlib.reload(sentry_mod)

        sentry_mod.init_sentry("http://key@example.com/1", "production")
        mock_sdk.init.assert_called_once_with(
            dsn="http://key@example.com/1",
            environment="production",
            traces_sample_rate=0.0,
        )


def test_capture_exception_noop_when_uninitialized() -> None:
    """capture_exception is a no-op when Sentry was never initialized."""
    # Fresh import without init
    import importlib

    import api.observability.sentry as sentry_mod

    importlib.reload(sentry_mod)

    # Should not raise
    sentry_mod.capture_exception(RuntimeError("test"))


def test_capture_exception_forwards_when_initialized() -> None:
    """capture_exception forwards to sentry_sdk.capture_exception after init."""
    mock_sdk = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": mock_sdk}):
        import importlib

        import api.observability.sentry as sentry_mod

        importlib.reload(sentry_mod)

        sentry_mod.init_sentry("http://key@example.com/1", "dev")
        exc = RuntimeError("boom")
        sentry_mod.capture_exception(exc)
        mock_sdk.capture_exception.assert_called_once_with(exc)


def test_capture_exception_noop_when_sentry_sdk_not_installed() -> None:
    """capture_exception is a no-op when sentry_sdk import fails."""
    # Simulate sentry_sdk not being installed by patching it to None
    import api.observability.sentry as sentry_mod

    # Save original
    original_sdk = sentry_mod.sentry_sdk

    try:
        sentry_mod.sentry_sdk = None
        # Should not raise
        sentry_mod.capture_exception(RuntimeError("test"))
    finally:
        sentry_mod.sentry_sdk = original_sdk
