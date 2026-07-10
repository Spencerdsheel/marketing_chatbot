"""Migration 0019: tenant_calendar_configs table for calendar sync (S8.2).

Raw SQL migration (no ORM models / no autogenerate).

- ``tenant_calendar_configs``: one row per tenant. PK on ``tenant_id``
  (single row per tenant, upserted via ``ON CONFLICT``). ``credentials_ciphertext``
  holds the AES-256-GCM-encrypted (via ``SecretBox``) OAuth access token /
  ``StubCalendarProvider`` secret -- decrypted only to build a
  ``CalendarProvider`` (api.scheduling.calendar_config_repository), never
  logged or echoed. ``busy`` is a jsonb list of ``{"start": ..., "end": ...}``
  intervals consumed by ``StubCalendarProvider`` (dev/test only -- the
  ``GoogleCalendarProvider`` ignores it and queries Google directly).
  ``enabled`` gates whether the scheduling routes attempt free-busy/sync at
  all (S8.2 decisions 3/4). Does NOT touch ``schedule_events`` --
  ``calendar_ref`` already exists from migration 0018.
"""
from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_calendar_configs (
            tenant_id              text        PRIMARY KEY,
            provider               text        NOT NULL,
            calendar_id            text,
            credentials_ciphertext text,
            busy                   jsonb       NOT NULL DEFAULT '[]'::jsonb,
            enabled                boolean     NOT NULL DEFAULT false,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_calendar_configs")
