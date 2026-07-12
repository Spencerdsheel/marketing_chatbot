"""Migration 0026: per-channel tenant_notification_configs + widened CHECKs (S9.3).

Raw SQL migration (no ORM models / no autogenerate) -- same style as 0021.

Decision 1 -- re-key ``tenant_notification_configs`` to
``PRIMARY KEY (tenant_id, channel)`` so a tenant may hold an independent
``email``, ``sms``, and ``whatsapp`` config row simultaneously:
  - ``ADD COLUMN channel text NOT NULL DEFAULT 'email'`` backfills every
    existing row to ``channel='email'`` (the S9.1/S9.2 email flow is
    byte-for-byte preserved), then ``DROP DEFAULT`` so future inserts always
    set it explicitly.
  - ``ADD COLUMN twilio_account_sid`` / ``ADD COLUMN twilio_from`` -- the
    Twilio Basic-Auth username + sender number (non-secret identifiers,
    stored plain). The Twilio Auth Token (the secret) reuses the existing
    ``credentials_ciphertext`` column, AES-256-GCM at rest exactly like the
    SMTP password.
  - Widen the ``provider`` CHECK to admit ``'twilio'``.
  - Add a ``channel`` CHECK admitting ``'email'``/``'sms'``/``'whatsapp'``.
  - Re-key the PK: ``DROP CONSTRAINT tenant_notification_configs_pkey`` ->
    ``ADD PRIMARY KEY (tenant_id, channel)``. Existing ``(tenant_id,
    'email')`` rows are unique post-backfill -- no conflict.

Decision 2 -- widen ``notification_jobs.channel`` CHECK to
``('email','sms','whatsapp')``. Nothing else about ``notification_jobs``
changes -- the ledger, the ``(tenant_id, dedupe_key)`` UNIQUE, the ``status``
flip, and the enqueue/mark repo functions are channel-agnostic and reused
verbatim.

``DROP CONSTRAINT IF EXISTS`` guards the auto-named CHECK/PK constraints
(Postgres default names: ``<table>_<column>_check``,
``tenant_notification_configs_pkey``) so the migration is safe to re-run /
tolerant of a differently-named existing constraint.

Downgrade (dev-only, explicit, reversible): non-``email`` rows are deleted
FIRST (both tables) so the composite PK / widened CHECKs can be safely
dropped and the original S9.1 shape restored.
"""
from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    # -- tenant_notification_configs: backfill channel, add Twilio columns --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "ADD COLUMN channel text NOT NULL DEFAULT 'email'"
    )
    op.execute("ALTER TABLE tenant_notification_configs ALTER COLUMN channel DROP DEFAULT")
    op.execute("ALTER TABLE tenant_notification_configs ADD COLUMN twilio_account_sid text")
    op.execute("ALTER TABLE tenant_notification_configs ADD COLUMN twilio_from text")

    # -- widen the provider CHECK to admit 'twilio' --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_provider_check"
    )
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "ADD CONSTRAINT tenant_notification_configs_provider_check "
        "CHECK (provider IN ('log', 'smtp', 'twilio'))"
    )

    # -- add the channel CHECK --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_channel_check"
    )
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "ADD CONSTRAINT tenant_notification_configs_channel_check "
        "CHECK (channel IN ('email', 'sms', 'whatsapp'))"
    )

    # -- re-key the PK to (tenant_id, channel) --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_pkey"
    )
    op.execute(
        "ALTER TABLE tenant_notification_configs ADD PRIMARY KEY (tenant_id, channel)"
    )

    # -- notification_jobs: widen the channel CHECK --
    op.execute(
        "ALTER TABLE notification_jobs DROP CONSTRAINT IF EXISTS notification_jobs_channel_check"
    )
    op.execute(
        "ALTER TABLE notification_jobs "
        "ADD CONSTRAINT notification_jobs_channel_check "
        "CHECK (channel IN ('email', 'sms', 'whatsapp'))"
    )


def downgrade() -> None:
    # Delete non-email rows FIRST so the narrower CHECKs/PK can be restored.
    op.execute("DELETE FROM tenant_notification_configs WHERE channel <> 'email'")
    op.execute("DELETE FROM notification_jobs WHERE channel <> 'email'")

    # -- tenant_notification_configs: restore (tenant_id)-only PK --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_pkey"
    )
    op.execute("ALTER TABLE tenant_notification_configs ADD PRIMARY KEY (tenant_id)")

    # -- restore the original provider CHECK --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_provider_check"
    )
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "ADD CONSTRAINT tenant_notification_configs_provider_check "
        "CHECK (provider IN ('log', 'smtp'))"
    )

    # -- drop the channel CHECK + the channel/Twilio columns --
    op.execute(
        "ALTER TABLE tenant_notification_configs "
        "DROP CONSTRAINT IF EXISTS tenant_notification_configs_channel_check"
    )
    op.execute("ALTER TABLE tenant_notification_configs DROP COLUMN channel")
    op.execute("ALTER TABLE tenant_notification_configs DROP COLUMN twilio_account_sid")
    op.execute("ALTER TABLE tenant_notification_configs DROP COLUMN twilio_from")

    # -- notification_jobs: restore the ('email')-only channel CHECK --
    op.execute(
        "ALTER TABLE notification_jobs DROP CONSTRAINT IF EXISTS notification_jobs_channel_check"
    )
    op.execute(
        "ALTER TABLE notification_jobs "
        "ADD CONSTRAINT notification_jobs_channel_check "
        "CHECK (channel IN ('email'))"
    )
