"""Migration 0035: scheduling_url column for Calendly hosted handoff (SR-6).

Raw SQL migration (no ORM models / no autogenerate).

- ``tenant_calendar_configs.scheduling_url`` -- nullable ``text``. Only set
  for a Calendly-configured tenant (``provider='calendly'``); the tenant's
  hosted Calendly page, returned verbatim by
  ``GET /public/schedule/availability-summary`` in the ``calendly_handoff``
  branch so the widget can ``window.open`` it (SR-6 decision 1). Not a
  secret -- may be echoed back by the admin config route, unlike
  ``credentials_ciphertext``.
"""
from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_calendar_configs ADD COLUMN scheduling_url text")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_calendar_configs DROP COLUMN IF EXISTS scheduling_url")
