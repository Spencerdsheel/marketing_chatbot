"""Migration 0021: tenant_notification_configs + notification_jobs (S9.1).

Raw SQL migration (no ORM models / no autogenerate).

- ``tenant_notification_configs``: one row per tenant. Mirrors
  ``tenant_calendar_configs`` (S8.2) -- ``credentials_ciphertext`` stores the
  SMTP password AES-256-GCM encrypted (``SecretBox``), decrypted only when
  building a ``NotificationProvider``
  (``api.notifications.providers.notification_provider_for``); never logged
  or echoed by the route layer. ``provider`` is constrained to the two
  channels this sprint supports (``log``/``smtp``). ``provider="log"`` needs
  no SMTP fields -- the stub ignores them (zero-config dev default).
- ``notification_jobs``: the idempotency + delivery-tracking ledger (S9.1
  decision 3). ``job_id`` is a ``uuid4().hex`` PK (assigned in
  ``api.notifications.repository``, not a DB default -- matches
  ``reminder_jobs``/``schedule_events`` convention). ``UNIQUE (tenant_id,
  dedupe_key)`` backs ``ON CONFLICT DO NOTHING RETURNING`` idempotent
  enqueue (decision 4). ``recipient``/``subject``/``body`` are PII/content --
  stored because the worker needs them to send, never written to a log line.
  No ``run_at`` column: notifications are enqueued on demand and dispatched
  immediately by ``.delay()``, not polled by Beat (that is scheduling's
  reminder dispatcher, S8.3).
"""
from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_notification_configs (
            tenant_id               text        PRIMARY KEY,
            provider                text        NOT NULL
                                     CHECK (provider IN ('log', 'smtp')),
            from_address             text,
            from_name                text,
            smtp_host                text,
            smtp_port                int,
            smtp_use_tls             boolean     NOT NULL DEFAULT true,
            smtp_username             text,
            credentials_ciphertext   text,
            enabled                  boolean     NOT NULL DEFAULT false,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE notification_jobs (
            job_id      text        PRIMARY KEY,
            tenant_id   text        NOT NULL,
            channel     text        NOT NULL
                        CHECK (channel IN ('email')),
            template    text,
            recipient   text        NOT NULL,
            subject     text        NOT NULL,
            body        text        NOT NULL,
            payload     jsonb,
            dedupe_key  text        NOT NULL,
            status      text        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'failed')),
            attempts    int         NOT NULL DEFAULT 0,
            delivery_ref text,
            last_error  text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, dedupe_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_jobs")
    op.execute("DROP TABLE IF EXISTS tenant_notification_configs")
