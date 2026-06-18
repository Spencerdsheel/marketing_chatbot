"""asyncpg access — connection pool lifecycle + thin parameterized query helpers.

No ORM (KB ADR / 02_BACKEND_PHILOSOPHY). All SQL is parameterized via asyncpg's
``$1, $2`` placeholders — never string-formatted with user data. PgBouncer (transaction
mode) sits in front in deployment; here we manage an asyncpg pool.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

import asyncpg

if TYPE_CHECKING:
    from asyncpg import Connection, Pool, Record

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_identifier(name: str) -> str:
    """Validate a SQL identifier (table/column). Identifiers are never user input,
    but validating closes the door on injection through a mistaken call site."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


class Database:
    """Owns an asyncpg pool and exposes parameterized query helpers."""

    def __init__(self, pool: Pool[Any]) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        init: Callable[[Connection[Any]], Awaitable[None]] | None = None,
    ) -> Database:
        pool = await asyncpg.create_pool(
            dsn, min_size=min_size, max_size=max_size, init=init
        )
        assert pool is not None  # noqa: S101  # create_pool returns None only without dsn
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def fetch(self, query: str, *args: Any) -> list[Record]:
        return cast("list[Record]", await self._pool.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Record | None:
        return cast("Record | None", await self._pool.fetchrow(query, *args))

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._pool.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return cast(str, await self._pool.execute(query, *args))

    def acquire(self) -> Any:
        """Acquire a connection (use ``async with db.acquire() as conn:``)."""
        return self._pool.acquire()
