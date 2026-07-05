"""Unit tests for Database.connect — statement_cache_size forwarding and jsonb codec."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from common.db import Database, _register_jsonb_codec


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


# ---------------------------------------------------------------------------
# jsonb codec — default registration tests
# ---------------------------------------------------------------------------


async def test_register_jsonb_codec_calls_set_type_codec() -> None:
    """_register_jsonb_codec calls set_type_codec with the expected arguments."""
    mock_conn = AsyncMock()
    await _register_jsonb_codec(mock_conn)
    mock_conn.set_type_codec.assert_called_once_with(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def test_connect_always_registers_jsonb_codec() -> None:
    """Database.connect passes an init that registers the jsonb codec on every connection.

    This is the durable fix for the Celery worker bug: every connection — whether
    opened by the API, a Celery task, or any future entrypoint — gets the codec
    automatically, so no caller can accidentally forget it.
    """
    stub_pool = AsyncMock()
    with patch("common.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=stub_pool) as mock:
        await Database.connect("postgres://stub-host:5432/appdb")
        _, kwargs = mock.call_args
        # create_pool must receive a non-None init callable.
        assert kwargs.get("init") is not None

    # Simulate what asyncpg does: call the composed init with a mock connection.
    composed_init = kwargs["init"]
    mock_conn = AsyncMock()
    await composed_init(mock_conn)
    mock_conn.set_type_codec.assert_called_once_with(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def test_connect_composes_caller_init_after_jsonb_codec() -> None:
    """When a caller-provided init is passed, it runs AFTER the jsonb codec registration.

    Both the built-in jsonb codec and the caller's init must be called in order.
    This ensures backward compatibility: app.py (and any other caller) can still
    provide an init callback for additional setup; it won't override the codec.
    """
    call_order: list[str] = []

    stub_pool = AsyncMock()

    async def _caller_init(conn: object) -> None:
        call_order.append("caller_init")

    with patch("common.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=stub_pool) as mock:
        await Database.connect("postgres://stub-host:5432/appdb", init=_caller_init)
        _, kwargs = mock.call_args

    composed_init = kwargs["init"]
    mock_conn = AsyncMock()

    # Replace set_type_codec with an AsyncMock that also appends to call_order.
    set_type_codec_mock = AsyncMock(side_effect=lambda *a, **kw: call_order.append("set_type_codec"))
    mock_conn.set_type_codec = set_type_codec_mock

    await composed_init(mock_conn)

    # jsonb codec must run BEFORE the caller's init.
    assert call_order == ["set_type_codec", "caller_init"]
    # The codec must still be called with the correct arguments.
    set_type_codec_mock.assert_called_once_with(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
