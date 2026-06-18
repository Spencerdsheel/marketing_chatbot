"""Unit tests for Settings — fail fast on missing/invalid required config."""
import pytest
from pydantic import ValidationError as PydanticValidationError

from common.settings import Settings, get_settings

VALID = {
    "deployment_mode": "saas",
    "database_url": "postgresql://u:p@localhost:5432/db",
    "jwt_secret": "x" * 32,
    "secret_encryption_key": "a" * 64,  # 64 hex chars = 32 bytes
}


def test_valid_settings_construct() -> None:
    s = Settings(_env_file=None, **VALID)
    assert s.deployment_mode == "saas"
    assert s.database_url.endswith("/db")


def test_defaults_applied() -> None:
    s = Settings(_env_file=None, **VALID)
    assert s.redis_url is None
    assert s.repository == "postgres"
    assert s.log_level == "INFO"


def test_missing_required_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEPLOYMENT_MODE", "DATABASE_URL", "JWT_SECRET", "SECRET_ENCRYPTION_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None)


def test_short_jwt_secret_rejected() -> None:
    bad = {**VALID, "jwt_secret": "tooshort"}
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, **bad)


def test_invalid_encryption_key_rejected() -> None:
    bad = {**VALID, "secret_encryption_key": "not-a-32-byte-key"}
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, **bad)


def test_invalid_deployment_mode_rejected() -> None:
    bad = {**VALID, "deployment_mode": "hybrid-typo"}
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, **bad)


def test_invalid_repository_rejected() -> None:
    bad = {**VALID, "repository": "elasticsearch"}
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, **bad)


def test_get_settings_reads_env_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "single_tenant")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("JWT_SECRET", "y" * 40)
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "b" * 64)
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2  # cached
    assert s1.deployment_mode == "single_tenant"
    get_settings.cache_clear()
