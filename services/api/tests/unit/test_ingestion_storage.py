"""Unit tests for api.ingestion.storage.

Covers:
- LocalStorageProvider put/get/exists/delete round-trip (tmp root).
- Keys are tenant-prefixed; a key under tenant A is not reachable via tenant B prefix.
- Path-traversal (``..``) and absolute keys are rejected (ValidationError).
- Fail-fast when storage_local_root is unset.
- get_storage() returns LocalStorageProvider for backend="local".
- get_storage() raises for unknown backend.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _reset_modules() -> None:
    # Reimport ingestion modules fresh + clear settings caches. Do NOT delete
    # api.config: that splits the module graph (api.app stays bound to the
    # original config) and poisons later tests. Clearing the caches on the single
    # shared config module gives fresh settings safely.
    for key in list(sys.modules.keys()):
        if key.startswith("api.ingestion"):
            del sys.modules[key]
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


# ==============================================================================
# LocalStorageProvider round-trips
# ==============================================================================


def test_local_put_get_round_trip(tmp_path: object) -> None:
    """put then get returns the same bytes."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        key = "tenant-a/doc-1/sample.txt"
        data = b"hello world"
        sp.put(key, data)
        assert sp.get(key) == data


def test_local_exists_true_after_put(tmp_path: object) -> None:
    """exists returns True after put."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        key = "tenant-a/doc-2/file.txt"
        assert not sp.exists(key)
        sp.put(key, b"content")
        assert sp.exists(key)


def test_local_delete_removes_file(tmp_path: object) -> None:
    """delete removes the file; exists returns False afterwards."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        key = "tenant-a/doc-3/file.txt"
        sp.put(key, b"to delete")
        assert sp.exists(key)
        sp.delete(key)
        assert not sp.exists(key)


def test_local_delete_missing_key_is_noop(tmp_path: object) -> None:
    """delete of a non-existent key does not raise."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        sp.delete("tenant-a/doc-99/nope.txt")  # should not raise


def test_local_get_missing_raises_file_not_found(tmp_path: object) -> None:
    """get of an absent key raises FileNotFoundError."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            sp.get("tenant-a/doc-5/missing.txt")


# ==============================================================================
# Tenant isolation: key under tenant A unreachable via tenant B prefix
# ==============================================================================


def test_local_tenant_isolation(tmp_path: object) -> None:
    """A file stored under tenant-a/ is not found via a tenant-b/ prefix."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        sp.put("tenant-a/doc-1/sample.txt", b"secret data")
        assert not sp.exists("tenant-b/doc-1/sample.txt")
        with pytest.raises(FileNotFoundError):
            sp.get("tenant-b/doc-1/sample.txt")


# ==============================================================================
# Security: path-traversal and absolute keys rejected
# ==============================================================================


def test_local_rejects_absolute_key(tmp_path: object) -> None:
    """An absolute key (starting with /) raises ValidationError."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from common.errors import ValidationError

        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        with pytest.raises(ValidationError) as exc_info:
            sp.put("/etc/passwd", b"nope")
        assert exc_info.value.code == "INVALID_STORAGE_KEY"


def test_local_rejects_dotdot_traversal(tmp_path: object) -> None:
    """A key containing '..' raises ValidationError."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from common.errors import ValidationError

        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        with pytest.raises(ValidationError) as exc_info:
            sp.put("tenant-a/../tenant-b/secret.txt", b"nope")
        assert exc_info.value.code == "INVALID_STORAGE_KEY"


def test_local_rejects_dotdot_in_exists(tmp_path: object) -> None:
    """exists() also rejects path-traversal keys."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from common.errors import ValidationError

        from api.ingestion.storage import LocalStorageProvider

        sp = LocalStorageProvider(str(tmp_path))
        with pytest.raises(ValidationError) as exc_info:
            sp.exists("../../etc/passwd")
        assert exc_info.value.code == "INVALID_STORAGE_KEY"


# ==============================================================================
# Fail-fast when storage_local_root is unset
# ==============================================================================


def test_local_raises_when_root_is_none() -> None:
    """LocalStorageProvider raises RuntimeError when root is None."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        with pytest.raises(RuntimeError, match="STORAGE_LOCAL_ROOT"):
            LocalStorageProvider(None)


def test_local_raises_when_root_is_empty_string() -> None:
    """LocalStorageProvider raises RuntimeError when root is an empty string."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.ingestion.storage import LocalStorageProvider

        with pytest.raises(RuntimeError, match="STORAGE_LOCAL_ROOT"):
            LocalStorageProvider("")


# ==============================================================================
# get_storage() selector
# ==============================================================================


def test_get_storage_returns_local_provider(tmp_path: object) -> None:
    """get_storage() with backend=local returns a LocalStorageProvider."""
    _reset_modules()
    env = {**_TEST_ENV, "STORAGE_BACKEND": "local", "STORAGE_LOCAL_ROOT": str(tmp_path)}
    with patch.dict("os.environ", env, clear=False):
        from api.config import get_api_settings

        get_api_settings.cache_clear()
        from api.ingestion.storage import LocalStorageProvider, get_storage

        provider = get_storage()
        assert isinstance(provider, LocalStorageProvider)


def test_get_storage_raises_for_unknown_backend() -> None:
    """get_storage() with an unknown backend raises ValidationError."""
    _reset_modules()
    env = {**_TEST_ENV, "STORAGE_BACKEND": "s3"}
    with patch.dict("os.environ", env, clear=False):
        from api.config import get_api_settings

        get_api_settings.cache_clear()
        from common.errors import ValidationError

        from api.ingestion.storage import get_storage

        with pytest.raises(ValidationError) as exc_info:
            get_storage()
        assert exc_info.value.code == "UNSUPPORTED_STORAGE_BACKEND"
