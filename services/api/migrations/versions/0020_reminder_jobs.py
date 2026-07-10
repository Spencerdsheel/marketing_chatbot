"""Migration 0020: reminder_jobs table for booking reminders (S8.3).

Raw SQL migration (no ORM models / no autogenerate).

- ``reminder_jobs``: one row per (tenant, event, offset). ``job_id`` is a
  ``uuid4().hex`` PK (assigned in ``api.scheduling.reminder_repository``, not
  a DB default -- matches ``schedule_events.event_id``'s convention). ``"offset"``
  is a reserved SQL word -- always double-quoted; constrained to the three
  supported values (S8.3 decision 2). ``status`` transitions
  ``pending -> queued -> sent``/``failed``, or ``skipped`` for an offset whose
  ``run_at`` was already past at booking time -- never omitted (decision 1).
  ``UNIQUE (tenant_id, event_id, "offset")`` backs ``ON CONFLICT DO NOTHING``
  idempotent creation. The composite FK to ``schedule_events`` cascades
  deletes so a compensated (S8.2 ``delete_event``) or future-cancelled event
  never leaves orphaned reminder rows. The ``(status, run_at)`` index serves
  the Celery Beat dispatcher's due-row poll (S8.3 decision 3).
"""
from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE reminder_jobs (
            job_id      text        PRIMARY KEY,
            tenant_id   text        NOT NULL,
            event_id    text        NOT NULL,
            "offset"    text        NOT NULL
                        CHECK ("offset" IN ('3d', '24h', '1h')),
            run_at      timestamptz NOT NULL,
            status      text        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'queued', 'sent', 'failed', 'skipped')),
            attempts    int         NOT NULL DEFAULT 0,
            last_error  text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, event_id, "offset"),
            FOREIGN KEY (tenant_id, event_id)
                REFERENCES schedule_events (tenant_id, event_id) ON DELETE CASCADE
        )
        """
    )

    op.execute(
        "CREATE INDEX reminder_jobs_due ON reminder_jobs (status, run_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reminder_jobs")
