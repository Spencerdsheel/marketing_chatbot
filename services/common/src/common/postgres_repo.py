"""Postgres implementation of the Repository contract (asyncpg, parameterized).

Every query composes ``tenant_filter`` so tenant isolation is guaranteed at the data
layer. Table/column names are validated identifiers (never user input); all values are
bound as ``$N`` parameters. ``tenant_id`` is set on create and is immutable.
"""
from __future__ import annotations

import uuid
from typing import Any

from common.auth import AuthClaims
from common.db import Database, safe_identifier
from common.errors import NotFoundError, ValidationError
from common.tenancy import resolve_write_tenant_id, tenant_filter

Row = dict[str, Any]


class PostgresRepository:
    """Generic tenant-scoped repository for a single table with ``id``/``tenant_id``."""

    def __init__(self, db: Database, table: str) -> None:
        self.db = db
        self.table = safe_identifier(table)

    async def get(self, claims: AuthClaims, id: str) -> Row | None:
        frag, fparams = tenant_filter(claims, next_param=2)
        sql = f"SELECT * FROM {self.table} WHERE id = $1 {frag}"  # noqa: S608
        row = await self.db.fetchrow(sql, id, *fparams)
        return dict(row) if row is not None else None

    async def list(self, claims: AuthClaims, **filters: Any) -> list[Row]:
        params: list[Any] = []
        frag, fparams = tenant_filter(claims, next_param=len(params) + 1)
        params += fparams
        clauses = ""
        for key, value in filters.items():
            safe_identifier(key)
            params.append(value)
            clauses += f" AND {key} = ${len(params)}"
        sql = f"SELECT * FROM {self.table} WHERE TRUE {frag}{clauses}"  # noqa: S608
        rows = await self.db.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def create(self, claims: AuthClaims, data: Row) -> Row:
        tenant_id = resolve_write_tenant_id(claims, data.get("tenant_id"))
        payload: Row = {**data, "tenant_id": tenant_id}
        payload.setdefault("id", uuid.uuid4().hex)
        cols = [safe_identifier(k) for k in payload]
        placeholders = [f"${i + 1}" for i in range(len(cols))]
        sql = (
            f"INSERT INTO {self.table} ({', '.join(cols)}) "  # noqa: S608
            f"VALUES ({', '.join(placeholders)}) RETURNING *"
        )
        row = await self.db.fetchrow(sql, *payload.values())
        assert row is not None  # noqa: S101  # INSERT ... RETURNING always yields a row
        return dict(row)

    async def update(self, claims: AuthClaims, id: str, changes: Row) -> Row:
        existing = await self.get(claims, id)
        if existing is None:
            raise NotFoundError(f"{self.table} {id} not found")
        if "tenant_id" in changes and changes["tenant_id"] != existing["tenant_id"]:
            raise ValidationError("tenant_id is immutable.", code="TENANT_ID_IMMUTABLE")
        set_cols = [k for k in changes if k not in ("id", "tenant_id")]
        if not set_cols:
            return existing
        params: list[Any] = []
        assignments = []
        for key in set_cols:
            safe_identifier(key)
            params.append(changes[key])
            assignments.append(f"{key} = ${len(params)}")
        params.append(id)
        id_idx = len(params)
        frag, fparams = tenant_filter(claims, next_param=len(params) + 1)
        params += fparams
        sql = (
            f"UPDATE {self.table} SET {', '.join(assignments)} "  # noqa: S608
            f"WHERE id = ${id_idx} {frag} RETURNING *"
        )
        row = await self.db.fetchrow(sql, *params)
        if row is None:
            raise NotFoundError(f"{self.table} {id} not found")
        return dict(row)

    async def delete(self, claims: AuthClaims, id: str) -> None:
        frag, fparams = tenant_filter(claims, next_param=2)
        sql = f"DELETE FROM {self.table} WHERE id = $1 {frag}"  # noqa: S608
        result = await self.db.execute(sql, id, *fparams)
        # asyncpg returns e.g. "DELETE 1"; 0 rows means not visible / not found.
        if result.rsplit(" ", 1)[-1] == "0":
            raise NotFoundError(f"{self.table} {id} not found")
