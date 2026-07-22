"""Migration 0034: explicit source discriminator + Calendly idempotency guard (SR-6).

Raw SQL migration (no ORM models / no autogenerate).

- ``schedule_events.source`` -- ``text NOT NULL DEFAULT 'native'`` with a CHECK
  restricting to ``('native', 'calendly')`` (SR-6 decision 7). Existing rows
  backfill to ``'native'`` via the column default; every future native
  ``create_event`` insert also sets ``'native'`` explicitly (repository
  change, not this migration). The webhook (``ingest_calendly_event``) sets
  ``'calendly'``.
- A **partial unique index** on ``(tenant_id, calendar_ref) WHERE source =
  'calendly'`` is the DB-level idempotency guard for re-delivered Calendly
  webhook events (SR-6 decision 6a) -- ``calendar_ref`` is plain ``text``
  here (see migration 0018), storing ``"calendly:<uuid>"`` (mirrors the
  existing ``f"{provider}:{external_id}"`` convention used by
  ``api.scheduling.routes.book_slot``), so the index is a simple column
  index, not a jsonb expression index. A re-delivered ``invitee.created`` for
  the same Calendly UUID hits this constraint and the repository upserts
  (``ON CONFLICT``) rather than double-inserting.
"""
from __future__ import annotations

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "ALTER TABLE schedule_events ADD COLUMN source text NOT NULL DEFAULT 'native' "
        "CHECK (source IN ('native', 'calendly'))"
    )

    op.execute(
        "CREATE UNIQUE INDEX schedule_events_calendly_idempotent "
        "ON schedule_events (tenant_id, calendar_ref) WHERE source = 'calendly'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS schedule_events_calendly_idempotent")
    op.execute("ALTER TABLE schedule_events DROP COLUMN IF EXISTS source")
