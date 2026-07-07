"""Unit tests for api.rag.repository.

Covers:
- search_chunks calls common.pgvector.similarity_search with
  table="knowledge_chunks", the tenant claims, and the embedding as a bound
  (positional) arg -- never interpolated into SQL.
- distance -> score mapping: score = 1 - distance (e.g. distance 0.1 -> 0.9).
- Result order is preserved from the DB (descending score = ascending distance).
- Global caller (tenant_id=None, PLATFORM_ADMIN) -> ValidationError, and
  similarity_search is never called (no un-filtered query escapes).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

from api.rag.repository import ChunkMatch, search_chunks

_TENANT_ID = "tenant-abc"


def _claims(tenant_id: str | None = _TENANT_ID, role: Role = Role.CLIENT_ADMIN) -> AuthClaims:
    return AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)


async def test_search_chunks_maps_distance_to_score_and_preserves_order() -> None:
    """distance 0.1 -> score 0.9; distance 0.4 -> score 0.6; DB order preserved."""
    rows = [
        {"doc_id": "doc-1", "chunk_id": "doc-1-0000", "content": "hello", "distance": 0.1},
        {"doc_id": "doc-1", "chunk_id": "doc-1-0001", "content": "world", "distance": 0.4},
    ]
    stub = AsyncMock(return_value=rows)
    claims = _claims()
    embedding = [0.1, 0.2, 0.3]

    with patch("api.rag.repository.similarity_search", new=stub):
        result = await search_chunks(object(), claims, embedding, top_k=5)

    assert isinstance(result[0], ChunkMatch)
    assert [m.score for m in result] == pytest.approx([0.9, 0.6])
    assert [m.doc_id for m in result] == ["doc-1", "doc-1"]
    assert [m.chunk_id for m in result] == ["doc-1-0000", "doc-1-0001"]
    assert [m.content for m in result] == ["hello", "world"]


async def test_search_chunks_passes_table_claims_and_embedding_through() -> None:
    """The wrapper adds no un-filtered query -- it delegates tenant filtering and
    passes the query embedding as a bound argument, never string-interpolated."""
    stub = AsyncMock(return_value=[])
    claims = _claims()
    embedding = [0.5, 0.6]

    with patch("api.rag.repository.similarity_search", new=stub):
        await search_chunks(object(), claims, embedding, top_k=7)

    stub.assert_awaited_once()
    args, kwargs = stub.await_args
    assert args[1] == "knowledge_chunks"
    assert args[2] is claims
    assert args[3] == embedding
    assert kwargs["top_k"] == 7
    assert kwargs["select"] == "doc_id, chunk_id, content"


async def test_search_chunks_global_caller_raises_validation_error() -> None:
    """PLATFORM_ADMIN (tenant_id=None) -> ValidationError; similarity_search not called."""
    stub = AsyncMock(return_value=[])
    claims = _claims(tenant_id=None, role=Role.PLATFORM_ADMIN)

    with patch("api.rag.repository.similarity_search", new=stub):
        with pytest.raises(ValidationError):
            await search_chunks(object(), claims, [0.1], top_k=5)

    stub.assert_not_awaited()


async def test_search_chunks_empty_result_returns_empty_list() -> None:
    stub = AsyncMock(return_value=[])
    claims = _claims()

    with patch("api.rag.repository.similarity_search", new=stub):
        result = await search_chunks(object(), claims, [0.1], top_k=5)

    assert result == []
