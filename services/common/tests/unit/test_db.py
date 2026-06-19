"""Unit tests for Database.connect — statement_cache_size forwarding."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from common.db import Database


async def test_connect_forwards_statement_cache_size_when_set() -> None:
    """When statement_cache_size is not None, it is forwarded to create_pool."""
    stub_pool = AsyncMock()
    with patch("common.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=stub_pool) as mock:
        await Database.connect("postgres://stub-host:5432/appdb", statement_cache_size=0)
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["statement_cache_size"] == 0


async def test_connect_omits_statement_cache_size_when_none() -> None:
    """When statement_cache_size is None (default), it is NOT passed to create_pool."""
    stub_pool = AsyncMock()
    with patch("common.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=stub_pool) as mock:
        await Database.connect("postgres://stub-host:5432/appdb")
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert "statement_cache_size" not in kwargs
