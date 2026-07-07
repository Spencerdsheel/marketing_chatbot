"""Migration 0011: knowledge_chunks table + embedding_model column + chunks_out column.

Raw SQL migration (no ORM models / no autogenerate).

Adds the schema required by the S5.3 chunk-embed-store slice:
- ``knowledge_chunks``: one row per text chunk per document per tenant.
  Stores the pgvector embedding (vector(768)) alongside the raw chunk content
  and jsonb metadata. Composite PK (tenant_id, chunk_id); FK to knowledge_docs
  ON DELETE CASCADE so chunks are removed when the parent doc is deleted.
- ``tenant_llm_configs.embedding_model`` (nullable text): the per-tenant
  embedding model name used at ingest time.
- ``ingestion_runs.chunks_out`` (nullable integer): the number of chunks
  written by the last successful ingest run.

The ``vector`` extension is already present from S0.1 (migration 0001).
No IVFFlat/HNSW index yet — that is S6.1.
"""
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    # Add embedding_model to per-tenant LLM config.
    op.execute(
        "ALTER TABLE tenant_llm_configs ADD COLUMN embedding_model text"
    )

    # Add chunks_out to ingestion run log.
    op.execute(
        "ALTER TABLE ingestion_runs ADD COLUMN chunks_out integer"
    )

    # knowledge_chunks: tenant-isolated chunk + embedding storage.
    # The vector(768) dimension matches settings.embedding_dimension default.
    # A mismatch at ingest time is a deterministic failure, not a silent truncate.
    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            tenant_id   text        NOT NULL,
            doc_id      text        NOT NULL,
            chunk_id    text        NOT NULL,
            content     text        NOT NULL,
            embedding   vector(768) NOT NULL,
            metadata    jsonb,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, chunk_id),
            FOREIGN KEY (tenant_id, doc_id)
                REFERENCES knowledge_docs(tenant_id, doc_id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_knowledge_chunks_tenant_doc "
        "ON knowledge_chunks (tenant_id, doc_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_chunks")
    op.execute(
        "ALTER TABLE ingestion_runs DROP COLUMN IF EXISTS chunks_out"
    )
    op.execute(
        "ALTER TABLE tenant_llm_configs DROP COLUMN IF EXISTS embedding_model"
    )
