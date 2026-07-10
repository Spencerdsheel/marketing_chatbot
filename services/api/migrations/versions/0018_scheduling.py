"""Migration 0018: availability + schedule_events tables for native booking (S8.1).

Raw SQL migration (no ORM models / no autogenerate).

- ``availability``: one row per tenant. ``timezone`` is a validated IANA name (app
  layer); ``rules`` is the jsonb slot-generation ruleset (slot_minutes,
  buffer_minutes, weekly_hours). PK on ``tenant_id`` (single row per tenant,
  upserted via ``ON CONFLICT``).
- ``schedule_events``: one row per booked/cancelled/completed/no-show call.
  Composite PK ``(tenant_id, event_id)``. ``calendar_ref`` is left NULL this
  sprint (S8.2 wires CalendarProvider sync). A **partial unique index** on
  ``(tenant_id, starts_at) WHERE status = 'booked'`` guarantees no double-booking
  for a tenant even under a race -- cancelled/completed events don't block it.
  A supporting ``(tenant_id, starts_at)`` index serves slot-window queries.
"""
from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE availability (
            tenant_id   text        PRIMARY KEY,
            timezone    text        NOT NULL,
            rules       jsonb       NOT NULL,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE schedule_events (
            tenant_id    text        NOT NULL,
            event_id     text        NOT NULL,
            lead_id      text,
            visitor_id   text,
            starts_at    timestamptz NOT NULL,
            ends_at      timestamptz NOT NULL,
            timezone     text        NOT NULL,
            status       text        NOT NULL DEFAULT 'booked'
                         CHECK (status IN ('booked', 'cancelled', 'completed', 'no_show')),
            calendar_ref text,
            consent      jsonb       NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, event_id)
        )
        """
    )

    # No-double-booking guard (S8.1 decision 4): two booked events cannot share a
    # start for the same tenant, even under a concurrent-insert race. Partial
    # (WHERE status = 'booked') so cancelled/completed/no_show rows don't block.
    op.execute(
        "CREATE UNIQUE INDEX schedule_events_no_double_book "
        "ON schedule_events (tenant_id, starts_at) WHERE status = 'booked'"
    )

    op.execute(
        "CREATE INDEX idx_schedule_events_tenant_starts "
        "ON schedule_events (tenant_id, starts_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_events")
    op.execute("DROP TABLE IF EXISTS availability")
