"""Optional Sentry integration -- import-guarded, no forced dependency.

``init_sentry(dsn, environment)`` is a no-op if ``sentry_sdk`` is not
installed or ``dsn`` is falsy.  ``capture_exception(exc)`` forwards to
``sentry_sdk.capture_exception`` only after a successful init.

Never sends PII deliberately; ``send_default_pii`` is not enabled.
"""
from __future__ import annotations

try:
    import sentry_sdk  # type: ignore[import-not-found]
except ImportError:
    sentry_sdk = None

_initialized = False


def init_sentry(dsn: str | None, environment: str) -> None:
    """Initialize Sentry if a DSN is provided and the SDK is available.

    No-op if ``sentry_sdk`` is not installed or ``dsn`` is falsy.
    """
    global _initialized

    if sentry_sdk is None or not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.0,
    )
    _initialized = True


def capture_exception(exc: BaseException) -> None:
    """Send an exception to Sentry, if initialized.

    No-op unless ``init_sentry`` was called with a valid DSN.
    """
    if not _initialized or sentry_sdk is None:
        return

    sentry_sdk.capture_exception(exc)
