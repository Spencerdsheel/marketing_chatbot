"""Migration 0012: HNSW cosine index on knowledge_chunks.embedding.

Raw SQL migration (no ORM models / no autogenerate).

S6.1 makes the vectors written in S5.3 actually searchable at scale: an HNSW
index on ``knowledge_chunks.embedding`` using the cosine-distance operator
class (``vector_cosine_ops``) so that ``ORDER BY embedding <=> $1`` queries
(see ``common.pgvector.similarity_search``) use the index instead of a full
sequential scan.

HNSW (unlike IVFFlat) builds fine on an empty/tiny table and needs no ``lists``
tuning -- good for dev/CI where the table may have few or zero rows. Requires
pgvector >= 0.5.0, already the S0.1 baseline.

The index is a recall/latency **optimization only**: correctness of ``<=>``
search does not depend on it (exact search without the index returns the same
top-k, just slower at scale). No table/column changes -- ``knowledge_chunks``
already exists from migration 0011.
"""
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS knowledge_chunks_embedding_hnsw")
