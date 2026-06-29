"""Unit tests for the _init_db_connection callback.

Verifies that the jsonb codec is registered on every pooled connection so
Python dict/list round-trips to/from jsonb columns.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from api.app import _init_db_connection


async def test_init_db_connection_registers_jsonb_codec() -> None:
    """_init_db_connection calls set_type_codec("jsonb", ...) on the conn."""
    mock_conn = AsyncMock()

    await _init_db_connection(mock_conn)

    call_args = mock_conn.set_type_codec.call_args
    assert call_args is not None
    assert call_args[1]["schema"] == "pg_catalog"
    # First positional arg is the type name
    assert call_args[0][0] == "jsonb"
    # encoder/decoder are callable
    assert callable(call_args[1]["encoder"])
    assert callable(call_args[1]["decoder"])
