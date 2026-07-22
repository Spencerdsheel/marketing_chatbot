"""Migration 0036: calendly_handoff_intents table -- email-keyed correlation (SR-6).

Raw SQL migration (no ORM models / no autogenerate).

- ``calendly_handoff_intents``: one row per pre-handoff email submission
  (``POST /public/schedule/handoff-intent``). Short-lived (``expires_at``,
  default TTL via ``calendly_handoff_intent_ttl_seconds``) -- a deliberate,
  documented reversal of SR-5 decision 7d for the Calendly path only (SR-6
  decision 5). No PK/unique constraint on ``(tenant_id, email)`` -- multiple
  intents for the same email are allowed (decision 5b: the most-recent
  non-expired one wins at lookup time, ``ORDER BY created_at DESC LIMIT 1``).
  The supporting index on ``(tenant_id, lower(email))`` serves the webhook's
  ``find_handoff_visitor`` lookup.
"""
from __future__ import annotations

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calendly_handoff_intents (
            tenant_id  text        NOT NULL,
            visitor_id text        NOT NULL,
            email      text        NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_calendly_handoff_intents_tenant_email "
        "ON calendly_handoff_intents (tenant_id, lower(email))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calendly_handoff_intents")
