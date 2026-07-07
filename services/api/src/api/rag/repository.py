"""RAG repository -- tenant-scoped pgvector similarity search over knowledge_chunks.

This is a thin wrapper around ``common.pgvector.similarity_search``. Tenant
isolation is already enforced inside ``similarity_search`` (it applies
``tenant_filter(claims, ...)``); this module adds no un-filtered query. The
only responsibility here is:

- ``_reject_global(claims)`` so a PLATFORM_ADMIN (global, ``tenant_id=None``)
  caller is rejected -- retrieval is always tenant-scoped.
- Mapping each returned ``Record`` (which carries a ``distance`` column, cosine
  distance in ``[0, 2]``) into a typed ``ChunkMatch`` with
  ``score = 1.0 - distance``.

Data model (migration 0011): ``knowledge_chunks(tenant_id PK, doc_id, chunk_id
PK, content, embedding vector(768), metadata jsonb, created_at)``.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError
from common.pgvector import similarity_search


@dataclass(frozen=True)
class ChunkMatch:
    """A single retrieved chunk with its cosine-similarity score.

    ``score`` is the raw cosine similarity (``1 - distance``, range
    ``[-1, 1]``) -- NOT clamped here. The caller (``api.rag.service``) derives
    the single ``confidence`` signal from it; the per-chunk score is surfaced
    as-is so downstream consumers (e.g. the orchestrator) can see the raw
    value.
    """

    doc_id: str
    chunk_id: str
    content: str
    score: float


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    RAG retrieval is always tenant-scoped; a global caller has no tenant_id
    and therefore cannot be filtered to a tenant's rows.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "RAG retrieval is tenant-scoped; PLATFORM_ADMIN callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def search_chunks(
    db: Database,
    claims: AuthClaims,
    embedding: list[float],
    *,
    top_k: int,
) -> list[ChunkMatch]:
    """Return the ``top_k`` knowledge_chunks most similar to ``embedding``.

    Tenant-filtered inside ``similarity_search``; results are ordered by
    ascending distance (= descending score), matching the DB's ``ORDER BY``.
    """
    _reject_global(claims)

    rows = await similarity_search(
        db,
        "knowledge_chunks",
        claims,
        embedding,
        top_k=top_k,
        select="doc_id, chunk_id, content",
    )
    return [
        ChunkMatch(
            doc_id=str(row["doc_id"]),
            chunk_id=str(row["chunk_id"]),
            content=str(row["content"]),
            score=1.0 - float(row["distance"]),
        )
        for row in rows
    ]
