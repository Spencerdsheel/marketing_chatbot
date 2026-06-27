"""API-specific settings extending the shared platform Settings.

``ApiSettings`` is a drop-in superset of ``common.settings.Settings``. It adds
cookie and token-TTL knobs needed by the auth module. The cached factory
``get_api_settings()`` replaces ``common.get_settings()`` in the API process.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from common.settings import Settings


class ApiSettings(Settings):
    """Settings for the API service -- extends common.Settings."""

    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_name: str = "access_token"
    access_token_ttl_seconds: int = 3600

    # Password reset token TTL (default 30 min).
    password_reset_ttl_seconds: int = 1800

    # DEV-ONLY: when True, password reset tokens are logged so a developer can
    # copy-paste them for testing. MUST stay False in production -- a reset
    # token is a secret (CLAUDE.md S3 "never log secrets/tokens/PII"). This is
    # a temporary bridge until Phase 9 email delivery.
    auth_reset_token_log: bool = False

    # Visitor session TTL (default 30 min). Used by the widget admission flow.
    visitor_session_ttl_seconds: int = 1800

    # Rate limiting: widget admission (by IP + client_key).
    widget_session_rate_limit_max: int = 30
    widget_session_rate_limit_window_seconds: int = 60

    # Rate limiting: auth endpoints (login + password-reset request, by IP).
    auth_rate_limit_max: int = 10
    auth_rate_limit_window_seconds: int = 60

    # CORS: preflight cache duration (seconds).
    cors_preflight_max_age: int = 600

    # CORS: origin-allowlist cache TTL (seconds).
    cors_origin_cache_ttl_seconds: int = 300

    # LLM: default max tokens per completion.
    llm_max_tokens: int = 1024

    # LLM: default/example model (per-tenant config overrides this).
    llm_default_model: str = "claude-opus-4-8"

    # LLM: bounded retries (SDK exp-backoff + jitter, transient failures only).
    llm_max_retries: int = 2

    # LLM: per-call timeout in seconds (applied by the SDK).
    llm_timeout_seconds: float = 30.0


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Return the process-wide API settings, constructed (and validated) once."""
    return ApiSettings()  # type: ignore[call-arg]  # values come from env/.env
