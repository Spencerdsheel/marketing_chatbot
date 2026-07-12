"""Shape test for migration 0026 (S9.3) -- no real DB.

Migration 0026 re-keys ``tenant_notification_configs`` to
``PRIMARY KEY (tenant_id, channel)``, adds ``twilio_account_sid``/
``twilio_from``, widens the ``provider`` CHECK to admit ``twilio``, adds a
``channel`` CHECK admitting ``sms``/``whatsapp``, and widens
``notification_jobs.channel`` CHECK to ``('email','sms','whatsapp')``. This
sprint's unit tests use a stub DB (no real Postgres), so this test asserts
the migration file's *shape* (revision chain + the expected raw-SQL
fragments) rather than executing it -- the live DDL is exercised in the
DoD live-pass recipe against a real Postgres.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0026_notifications_channels.py"
)


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("migration_0026", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain() -> None:
    module = _load_migration()
    assert module.revision == "0026"  # type: ignore[attr-defined]
    assert module.down_revision == "0025"  # type: ignore[attr-defined]


def test_upgrade_contains_expected_ddl_fragments() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")

    # Decision 1: per-channel re-key + Twilio columns + widened provider CHECK
    # + new channel CHECK.
    assert "ADD COLUMN channel text NOT NULL DEFAULT 'email'" in source
    assert "ALTER COLUMN channel DROP DEFAULT" in source
    assert "ADD COLUMN twilio_account_sid" in source
    assert "ADD COLUMN twilio_from" in source
    assert "CHECK (provider IN ('log', 'smtp', 'twilio'))" in source
    assert "CHECK (channel IN ('email', 'sms', 'whatsapp'))" in source
    assert "ADD PRIMARY KEY (tenant_id, channel)" in source

    # Decision 2: notification_jobs.channel CHECK widened.
    assert "CHECK (channel IN ('email', 'sms', 'whatsapp'))" in source

    # Auto-named constraints dropped defensively.
    assert "DROP CONSTRAINT IF EXISTS" in source


def test_downgrade_deletes_non_email_rows_first() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade")[1]

    assert "DELETE FROM tenant_notification_configs WHERE channel <> 'email'" in downgrade_body
    assert "DELETE FROM notification_jobs WHERE channel <> 'email'" in downgrade_body
    assert "ADD PRIMARY KEY (tenant_id)" in downgrade_body
    assert "CHECK (provider IN ('log', 'smtp'))" in downgrade_body
    assert "CHECK (channel IN ('email'))" in downgrade_body
