"""Unit tests confirming jsonb codec registration via common.db.

The jsonb codec was moved from _init_db_connection in api.app to
_register_jsonb_codec in common.db so it is applied to EVERY asyncpg
connection by default (API, Celery workers, scripts) and cannot be forgotten.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

from common.db import _register_jsonb_codec


async def test_register_jsonb_codec_registers_jsonb_codec() -> None:
    """_register_jsonb_codec calls set_type_codec("jsonb", ...) on the conn."""
    mock_conn = AsyncMock()

    await _register_jsonb_codec(mock_conn)

    mock_conn.set_type_codec.assert_called_once_with(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
