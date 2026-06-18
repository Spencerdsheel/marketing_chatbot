"""pgvector access — tenant-isolated similarity search.

Embeddings live in a ``vector(N)`` column in tenant-scoped tables. Similarity uses the
cosine operator ``<=>`` (backed by an IVFFlat/HNSW index in production). There is exactly
one vector backend (pgvector); do not add another. Every query includes the tenant filter.

Register pgvector's type codec on each pooled connection via ``register_vector_init`` so
Python lists/np arrays round-trip as ``vector``:

    db = await Database.connect(dsn, init=register_vector_init)
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pgvector.asyncpg import register_vector

from common.auth import AuthClaims
from common.db import Database, safe_identifier
from common.tenancy import tenant_filter

if TYPE_CHECKING:
    from asyncpg import Connection, Record


async def register_vector_init(conn: Connection[Any]) -> None:
    """asyncpg pool ``init`` callback: enable the pgvector codec on the connection."""
    await register_vector(conn)


async def ensure_extension(db: Database) -> None:
    """Create the pgvector extension if absent (idempotent)."""
    await db.execute("CREATE EXTENSION IF NOT EXISTS vector")


async def similarity_search(
    db: Database,
    table: str,
    claims: AuthClaims,
    embedding: Sequence[float],
    *,
    top_k: int = 5,
    vector_column: str = "embedding",
    select: str = "*",
) -> list[Record]:
    """Return the ``top_k`` rows most similar to ``embedding`` within the caller's tenant.

    Results are ordered by ascending cosine distance and include a ``distance`` column.
    """
    table = safe_identifier(table)
    vector_column = safe_identifier(vector_column)
    params: list[Any] = [list(embedding)]
    frag, fparams = tenant_filter(claims, next_param=len(params) + 1)
    params += fparams
    params.append(top_k)
    limit_idx = len(params)
    sql = (
        f"SELECT {select}, {vector_column} <=> $1 AS distance "  # noqa: S608
        f"FROM {table} WHERE TRUE {frag} "
        f"ORDER BY {vector_column} <=> $1 ASC LIMIT ${limit_idx}"
    )
    return await db.fetch(sql, *params)
