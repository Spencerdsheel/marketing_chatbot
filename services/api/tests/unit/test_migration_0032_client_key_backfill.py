"""Unit tests for migration 0032 -- backfill for the 0030 gap (live-testing find).

Migration 0030 (S12.1) renamed ``tenants.client_key`` to
``tenants.client_key_hash`` but never backfilled/rehashed the existing
*plaintext* values already in that column for tenants that pre-date the
migration (confirmed live via psql: the ``isngs`` tenant's
``client_key_hash`` was still the raw ``pk_...`` key after 0030 ran). Since
``api.gateway.repository.get_tenant_by_client_key`` (S12.1) now hashes the
incoming raw key and looks up ``WHERE client_key_hash = $1``, those
pre-existing tenants can never match -- widget admission was permanently
broken for them.

0032 is a genuine data backfill, not pure DDL, so it can't be shape-tested
the way 0026 is (no real Postgres in this suite -- see
``test_notifications_migration_0026.py``). Instead we exercise the real
``upgrade()`` function against a fake SQLAlchemy-``Connection``-shaped bind
(recording ``execute()`` calls), using ``api.admin.repository
._is_client_key_hash`` for the "already hashed?" check -- the same pure
helper is unit-tested directly in ``test_admin_repository.py``.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0032_client_key_hash_backfill.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0032", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeBind:
    """Records every UPDATE issued; serves a fixed row set for the SELECT."""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows
        self.updates: list[dict[str, Any]] = []

    def execute(self, clause: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(clause).strip().upper()
        if sql.startswith("SELECT"):
            return _FakeResult(self._rows)
        assert sql.startswith("UPDATE")
        assert params is not None
        self.updates.append(params)
        return _FakeResult([])


def test_revision_chain() -> None:
    module = _load_migration()
    assert module.revision == "0032"  # type: ignore[attr-defined]
    assert module.down_revision == "0031"  # type: ignore[attr-defined]


def test_upgrade_rehashes_plaintext_rows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration()

    plaintext = "pk_WlpgWi4qtZSZhlNP0Ce2RZKvS1U7mgbp"
    already_hashed = hashlib.sha256(b"pk_demo_seed_key").hexdigest()

    fake_bind = _FakeBind(
        rows=[
            ("tenant-isngs", plaintext),
            ("tenant-demo", already_hashed),
        ]
    )
    monkeypatch.setattr(module.op, "get_bind", lambda: fake_bind)

    module.upgrade()

    # Only the still-plaintext row was updated.
    assert len(fake_bind.updates) == 1
    update = fake_bind.updates[0]
    assert update["id"] == "tenant-isngs"
    assert update["hash"] == hashlib.sha256(plaintext.encode()).hexdigest()


def test_upgrade_is_idempotent_second_run_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration()

    plaintext = "pk_WlpgWi4qtZSZhlNP0Ce2RZKvS1U7mgbp"
    rehashed = hashlib.sha256(plaintext.encode()).hexdigest()

    # Simulate the state of the table *after* the first run: every row is
    # now a valid 64-hex-char digest.
    fake_bind = _FakeBind(rows=[("tenant-isngs", rehashed)])
    monkeypatch.setattr(module.op, "get_bind", lambda: fake_bind)

    module.upgrade()

    assert fake_bind.updates == []


def test_downgrade_is_a_documented_no_op() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade")[1]

    # Mirrors 0030's own precedent: a one-way data-shape change can't be
    # reversed (SHA-256 is not invertible), so downgrade is schema-only /
    # a documented no-op rather than a fabricated "unhash".
    assert "pass" in downgrade_body
