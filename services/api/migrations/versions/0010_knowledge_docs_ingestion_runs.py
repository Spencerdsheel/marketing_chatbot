"""Migration 0010: knowledge_docs and ingestion_runs tables.

Raw SQL migration (no ORM models / no autogenerate).

Adds the two tables required by the S5.2 document-ingestion slice:
- ``knowledge_docs``: one row per unique document per tenant.
  A UNIQUE (tenant_id, content_hash) constraint enforces idempotent re-upload
  (decision 5 in S5.2).
- ``ingestion_runs``: one row per parse-attempt for a document, recording
  status, duration, and any errors as jsonb (decision 6).
Both tables are composite-PK with tenant_id first (multi-tenancy, CLAUDE.md §2).
Both foreign-key to ``tenants(id) ON DELETE CASCADE`` for clean teardown.
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge_docs (
            tenant_id    text        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            doc_id       text        NOT NULL,
            source       text        NOT NULL,
            filename     text        NOT NULL,
            content_type text        NOT NULL,
            status       text        NOT NULL,
            content_hash text        NOT NULL,
            storage_key  text        NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, doc_id),
            UNIQUE (tenant_id, content_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_knowledge_docs_tenant_created "
        "ON knowledge_docs (tenant_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE ingestion_runs (
            tenant_id   text        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            run_id      text        NOT NULL,
            doc_id      text        NOT NULL,
            status      text        NOT NULL,
            chars_out   integer,
            errors      jsonb,
            started_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            duration_ms integer,
            PRIMARY KEY (tenant_id, run_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_ingestion_runs_tenant_doc "
        "ON ingestion_runs (tenant_id, doc_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingestion_runs")
    op.execute("DROP TABLE IF EXISTS knowledge_docs")
