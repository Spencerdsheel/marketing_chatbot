"""Migration 0016: tenant_crm_configs table for outbound CRM sync config.

Raw SQL migration (no ORM models / no autogenerate).

S7.4 adds the per-tenant CRM sync configuration (decision 2):
- ``tenant_crm_configs``: one row per tenant. ``connector`` selects the
  ``CRMSync`` implementation (``"webhook"`` only this sprint); ``webhook_url``
  is the destination for the webhook connector; ``secret_ciphertext`` is the
  AES-256-GCM (``common.crypto.SecretBox``) encrypted signing secret, never
  stored or logged in plaintext; ``enabled`` gates whether ``crm.sync_lead``
  performs a sync at all (disabled/missing -> no-op success, not an error).
  Single row per tenant -- ``tenant_id`` is the primary key.
"""
from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_crm_configs (
            tenant_id           text        PRIMARY KEY,
            connector           text        NOT NULL,
            webhook_url         text,
            secret_ciphertext   text,
            enabled             boolean     NOT NULL DEFAULT false,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_crm_configs")
