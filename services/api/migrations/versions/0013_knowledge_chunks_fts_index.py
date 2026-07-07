"""Migration 0013: GIN full-text-search index on knowledge_chunks.content.

Raw SQL migration (no ORM models / no autogenerate).

S6.2 adds a Postgres full-text (keyword) search leg alongside S6.1's vector
search. This is the supporting GIN index over ``to_tsvector('english',
content)`` so ``keyword_search`` (see ``api.rag.repository``) -- whose query
matches on ``to_tsvector($1::regconfig, content) @@ plainto_tsquery($1::regconfig,
$2)`` -- uses the index instead of a full sequential scan.

The literal ``'english'`` in the index expression must match the query-time
regconfig (``settings.rag_fts_language``, default ``"english"``) for the
index to be used. A non-default language at query time still works
correctly, just without this index (a full scan, degraded but not broken).

The index is a recall/latency **optimization only** -- correctness of the FTS
match does not depend on it. No table/column changes -- ``knowledge_chunks``
already exists from migration 0011.
"""
from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS knowledge_chunks_content_fts "
        "ON knowledge_chunks USING gin (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS knowledge_chunks_content_fts")
