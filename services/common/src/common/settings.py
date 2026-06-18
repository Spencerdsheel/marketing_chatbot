"""Application settings via Pydantic Settings — validated, fail-fast.

Config is read from environment variables (and an optional ``.env``). Required values
have NO default; constructing ``Settings`` (e.g. via ``get_settings()`` at startup)
raises immediately if anything required is missing or invalid. ``.env.example`` is
documentation, not defaults (CLAUDE.md §3).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.crypto import _normalize_key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Hybrid delivery — drives SaaS vs single-tenant behavior.
    deployment_mode: Literal["saas", "single_tenant"]

    # Data stores.
    database_url: str
    redis_url: str | None = None
    repository: Literal["postgres", "memory"] = "postgres"

    # Secrets (required).
    jwt_secret: str = Field(min_length=32)
    secret_encryption_key: str

    # Observability.
    log_level: str = "INFO"
    service_name: str = "common"

    @field_validator("secret_encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: str) -> str:
        # Raises ValueError (→ pydantic ValidationError) unless it resolves to 32 bytes.
        _normalize_key(value)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed (and validated) once."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
