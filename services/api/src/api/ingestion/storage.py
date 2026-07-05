"""Object-storage abstraction for the document-ingestion pipeline.

``StorageProvider`` is a ``typing.Protocol`` defining the four operations every
driver must implement. ``LocalStorageProvider`` is the first driver — it roots
files under ``settings.storage_local_root`` and enforces **tenant-scoped,
traversal-proof** key paths.

Key contract:
- Keys MUST start with a tenant prefix: ``{tenant_id}/{doc_id}/...``
- Absolute keys (starting with ``/``) are rejected.
- Path-traversal components (``..``) in any segment are rejected.
- Both checks raise ``ValidationError`` (code ``INVALID_STORAGE_KEY``).

A key violation at the driver level means tenant A's key can never resolve
inside tenant B's directory, even if a caller forgets the prefix check.

Selecting a driver:
  ``get_storage()`` reads ``settings.storage_backend`` and returns the
  appropriate ``StorageProvider`` instance. Currently only ``"local"`` is
  supported; S3/GCS drivers slot in here later via an ``elif``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from common.errors import ValidationError

from api.config import get_api_settings


@runtime_checkable
class StorageProvider(Protocol):
    """Protocol every storage driver must satisfy."""

    def put(self, key: str, data: bytes) -> None:
        """Write ``data`` under ``key``, creating intermediate directories."""
        ...

    def get(self, key: str) -> bytes:
        """Return the bytes stored under ``key``.

        Raises ``FileNotFoundError`` if the key does not exist.
        """
        ...

    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` is present in storage."""
        ...

    def delete(self, key: str) -> None:
        """Delete the object at ``key``.

        No-op if the key does not exist.
        """
        ...


def _validate_key(key: str) -> None:
    """Reject absolute paths and path-traversal components.

    Raises ``ValidationError`` (``INVALID_STORAGE_KEY``) on violation.
    All callers pass tenant-prefixed keys, so traversal out of the tenant
    directory is structurally impossible once these two checks pass.
    """
    if key.startswith("/"):
        raise ValidationError(
            "Storage key must not be an absolute path.",
            code="INVALID_STORAGE_KEY",
        )
    # Normalise to forward slashes before checking segments.
    parts = key.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValidationError(
            "Storage key must not contain path-traversal components (..).",
            code="INVALID_STORAGE_KEY",
        )


class LocalStorageProvider:
    """File-system storage driver rooted at ``root``.

    Constructed by ``get_storage()`` which passes ``settings.storage_local_root``.
    Fail-fast: raises ``RuntimeError`` if ``root`` is ``None`` or empty — the
    caller must have set ``STORAGE_LOCAL_ROOT`` (CLAUDE.md §3 config).
    """

    def __init__(self, root: str | None) -> None:
        if not root:
            raise RuntimeError(
                "LocalStorageProvider requires STORAGE_LOCAL_ROOT to be set. "
                "See deploy/.env.example for documentation."
            )
        self._root = Path(root).resolve()

    def _full_path(self, key: str) -> Path:
        _validate_key(key)
        return self._root / key

    def put(self, key: str, data: bytes) -> None:
        """Write ``data`` under ``key``, creating parent directories."""
        path = self._full_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        """Return bytes at ``key``; raises ``FileNotFoundError`` if absent."""
        return self._full_path(key).read_bytes()

    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` exists on disk."""
        return self._full_path(key).exists()

    def delete(self, key: str) -> None:
        """Delete file at ``key``; silent no-op if absent."""
        path = self._full_path(key)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def get_storage() -> StorageProvider:
    """Return the configured ``StorageProvider`` instance.

    Resolution order:
    1. Read ``settings.storage_backend`` (default ``"local"``).
    2. Construct and return the matching driver.
    3. Unknown backend → ``ValidationError`` (``UNSUPPORTED_STORAGE_BACKEND``).

    Fail-fast: ``LocalStorageProvider`` raises ``RuntimeError`` if
    ``storage_local_root`` is unset (``CLAUDE.md §3 config``).
    """
    settings = get_api_settings()
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorageProvider(settings.storage_local_root)
    raise ValidationError(
        f"Unsupported storage backend: {backend!r}. Supported: 'local'.",
        code="UNSUPPORTED_STORAGE_BACKEND",
    )
