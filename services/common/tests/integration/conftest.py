"""Fixtures for asyncpg/pgvector integration tests.

These run only when ``TEST_DATABASE_URL`` is set (see the top-level conftest). The DB
must allow ``CREATE EXTENSION vector``. Each test gets a uniquely-named table that is
dropped on teardown, so the tests are safe to run against a shared database.
"""
import os
import uuid
from collections.abc import AsyncIterator, Callable

import pytest_asyncio

from common.db import Database
from common.pgvector import ensure_extension, register_vector_init


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Database]:
    dsn = os.environ["TEST_DATABASE_URL"]
    # Ensure the extension exists before connections register the vector codec.
    bootstrap = await Database.connect(dsn)
    await ensure_extension(bootstrap)
    await bootstrap.close()

    database = await Database.connect(dsn, init=register_vector_init)
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def make_table(db: Database) -> AsyncIterator[Callable[[str], object]]:
    """Return an async factory that creates a uniquely-named table and tracks cleanup."""
    created: list[str] = []

    async def _make(columns_sql: str) -> str:
        name = f"t_{uuid.uuid4().hex}"
        await db.execute(f"CREATE TABLE {name} ({columns_sql})")
        created.append(name)
        return name

    try:
        yield _make  # type: ignore[misc]
    finally:
        for name in created:
            await db.execute(f"DROP TABLE IF EXISTS {name}")
