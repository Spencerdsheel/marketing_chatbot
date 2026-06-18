"""Integration: pgvector similarity search is tenant-isolated and ordered."""
from collections.abc import Callable

import pytest

from common.auth import AuthClaims, Role
from common.db import Database
from common.pgvector import similarity_search

pytestmark = pytest.mark.integration

A = AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="tenant-a")
B = AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="tenant-b")


async def _seed(db: Database, make_table: Callable[[str], object]) -> str:
    table = await make_table(  # type: ignore[misc]
        "id text PRIMARY KEY, tenant_id text NOT NULL, content text, embedding vector(3)"
    )
    rows = [
        ("a1", "tenant-a", "near", [1.0, 0.0, 0.0]),
        ("a2", "tenant-a", "far", [0.0, 1.0, 0.0]),
        ("b1", "tenant-b", "near-but-other-tenant", [1.0, 0.0, 0.0]),
    ]
    for rid, tid, content, emb in rows:
        await db.execute(
            f"INSERT INTO {table} (id, tenant_id, content, embedding) "  # noqa: S608
            "VALUES ($1, $2, $3, $4)",
            rid, tid, content, emb,
        )
    return table


async def test_similarity_is_tenant_isolated(db: Database, make_table: Callable[[str], object]) -> None:
    table = await _seed(db, make_table)
    results = await similarity_search(db, table, A, [1.0, 0.0, 0.0], top_k=10)
    tenants = {r["tenant_id"] for r in results}
    assert tenants == {"tenant-a"}  # tenant-b's identical vector is never returned


async def test_similarity_orders_by_distance(db: Database, make_table: Callable[[str], object]) -> None:
    table = await _seed(db, make_table)
    results = await similarity_search(db, table, A, [1.0, 0.0, 0.0], top_k=10)
    assert [r["id"] for r in results] == ["a1", "a2"]  # nearest first
    assert results[0]["distance"] <= results[1]["distance"]


async def test_top_k_limits_results(db: Database, make_table: Callable[[str], object]) -> None:
    table = await _seed(db, make_table)
    results = await similarity_search(db, table, A, [1.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0]["id"] == "a1"


async def test_other_tenant_sees_only_its_rows(db: Database, make_table: Callable[[str], object]) -> None:
    table = await _seed(db, make_table)
    results = await similarity_search(db, table, B, [1.0, 0.0, 0.0], top_k=10)
    assert {r["id"] for r in results} == {"b1"}
