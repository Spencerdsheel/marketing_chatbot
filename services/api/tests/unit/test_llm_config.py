"""Unit tests for LLM config repository (multi-tenant isolation).

Covers:
- upsert_llm_config stores ciphertext (not plaintext); decrypt round-trips.
- get_llm_config SELECT carries WHERE tenant_id = $1 bound to caller's tenant.
- Tenant A's claims never read tenant B's row.
- PLATFORM_ADMIN (global) → ValidationError.
"""
from __future__ import annotations

from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.crypto import SecretBox
from common.errors import ValidationError

from api.config import get_api_settings
from api.llm.config_repository import get_llm_config, upsert_llm_config

# -- Test doubles --------------------------------------------------------------

_TEST_ENCRYPTION_KEY = "x" * 48  # 48 chars, but SecretBox normalizes to 32 bytes


class _RecordingDatabase:
    """Database double that records SQL + params."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()
        self._rows = rows or []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return self._rows[0] if self._rows else None

    async def execute(self, query: str, *args: Any) -> str:
        self.last_sql = query
        self.last_params = args
        return "INSERT 1"

    async def close(self) -> None:
        pass


# -- Helpers -------------------------------------------------------------------


def _claims(tenant_id: str | None, role: Role) -> AuthClaims:
    return AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)


# -- Upsert stores ciphertext, not plaintext -----------------------------------


async def test_upsert_stores_ciphertext_not_plaintext() -> None:
    """The 4th bound param (api_key_ciphertext) != the plaintext key."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)
    plaintext_key = "sk-test-secret-key-12345"

    await upsert_llm_config(db, claims, provider="anthropic", model="claude-opus-4-8", api_key=plaintext_key)

    ciphertext = db.last_params[3]
    assert isinstance(ciphertext, str)
    assert ciphertext != plaintext_key

    # Round-trip: decrypt the stored ciphertext
    box = SecretBox(get_api_settings().secret_encryption_key)
    decrypted = box.decrypt_str(ciphertext)
    assert decrypted == plaintext_key


# -- base_url round-trips through upsert → get ---------------------------------


async def test_base_url_round_trips() -> None:
    """base_url stored via upsert and returned via get_llm_config."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await upsert_llm_config(
        db, claims,
        provider="openai",
        model="gpt-4o",
        api_key="sk-key",
        base_url="https://opencode.ai/zen/v1",
    )

    assert db.last_params[4] == "https://opencode.ai/zen/v1"


async def test_omitted_base_url_is_none() -> None:
    """Omitted base_url → None in params."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await upsert_llm_config(
        db, claims,
        provider="anthropic",
        model="claude-opus-4-8",
        api_key="sk-key",
    )

    assert db.last_params[4] is None


# -- get_llm_config with base_url ----------------------------------------------


async def test_get_llm_config_returns_base_url() -> None:
    """get_llm_config returns base_url when present."""
    row = {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_ciphertext": SecretBox(get_api_settings().secret_encryption_key).encrypt("sk-key"),
        "base_url": "https://opencode.ai/zen/v1",
        "api_version": None,
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims)

    assert config is not None
    assert config.provider == "openai"
    assert config.base_url == "https://opencode.ai/zen/v1"


async def test_get_llm_config_base_url_none_when_null() -> None:
    """get_llm_config returns base_url=None when column is NULL."""
    row = {
        "provider": "anthropic",
        "model": "claude-opus-4-8",
        "api_key_ciphertext": SecretBox(get_api_settings().secret_encryption_key).encrypt("sk-key"),
        "base_url": None,
        "api_version": None,
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims)

    assert config is not None
    assert config.base_url is None


# -- get_llm_config carries tenant filter --------------------------------------


async def test_get_llm_config_filters_by_tenant_id() -> None:
    """SELECT carries WHERE tenant_id = $1 bound to the caller's tenant."""
    row = {
        "provider": "anthropic",
        "model": "claude-opus-4-8",
        "api_key_ciphertext": SecretBox(get_api_settings().secret_encryption_key).encrypt("sk-key"),
        "base_url": None,
        "api_version": None,
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims)

    assert config is not None
    assert config.provider == "anthropic"
    assert config.model == "claude-opus-4-8"
    assert config.api_key == "sk-key"
    assert "tenant_id" in db.last_sql
    assert db.last_params[0] == "tenant-a"


# -- Multi-tenant isolation ----------------------------------------------------


async def test_tenant_a_cannot_read_tenant_b_config() -> None:
    """Tenant A's claims → SELECT bound to A's id; tenant B's row is never returned."""
    db = _RecordingDatabase(rows=[])  # No rows for tenant A
    claims_a = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims_a)

    assert config is None
    assert db.last_params[0] == "tenant-a"


# -- Global admin rejected -----------------------------------------------------


async def test_platform_admin_rejected() -> None:
    """PLATFORM_ADMIN (global, tenant_id=None) → ValidationError."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await get_llm_config(db, claims)


async def test_platform_admin_rejected_on_upsert() -> None:
    """PLATFORM_ADMIN cannot upsert LLM config."""
    db = _RecordingDatabase()
    claims = _claims(None, Role.PLATFORM_ADMIN)

    with pytest.raises(ValidationError):
        await upsert_llm_config(db, claims, provider="anthropic", model="claude-opus-4-8", api_key="sk-key")


# -- api_version round-trips through upsert → get --------------------------------


async def test_api_version_round_trips() -> None:
    """api_version stored via upsert and returned via get_llm_config."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await upsert_llm_config(
        db, claims,
        provider="azure",
        model="my-deployment",
        api_key="sk-key",
        base_url="https://my-resource.openai.azure.com",
        api_version="2024-02-01",
    )

    assert db.last_params[5] == "2024-02-01"


async def test_omitted_api_version_is_none() -> None:
    """Omitted api_version → None in params."""
    db = _RecordingDatabase()
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    await upsert_llm_config(
        db, claims,
        provider="anthropic",
        model="claude-opus-4-8",
        api_key="sk-key",
    )

    assert db.last_params[5] is None


async def test_get_llm_config_returns_api_version() -> None:
    """get_llm_config returns api_version when present."""
    row = {
        "provider": "azure",
        "model": "my-deployment",
        "api_key_ciphertext": SecretBox(get_api_settings().secret_encryption_key).encrypt("sk-key"),
        "base_url": "https://my-resource.openai.azure.com",
        "api_version": "2024-02-01",
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims)

    assert config is not None
    assert config.provider == "azure"
    assert config.api_version == "2024-02-01"


async def test_get_llm_config_api_version_none_when_null() -> None:
    """get_llm_config returns api_version=None when column is NULL."""
    row = {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key_ciphertext": SecretBox(get_api_settings().secret_encryption_key).encrypt("sk-key"),
        "base_url": None,
        "api_version": None,
    }
    db = _RecordingDatabase(rows=[row])
    claims = _claims("tenant-a", Role.CLIENT_ADMIN)

    config = await get_llm_config(db, claims)

    assert config is not None
    assert config.api_version is None
