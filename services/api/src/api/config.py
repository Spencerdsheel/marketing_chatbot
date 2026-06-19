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


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Return the process-wide API settings, constructed (and validated) once."""
    return ApiSettings()  # type: ignore[call-arg]  # values come from env/.env
