"""Repository pattern: the contract + the in-memory implementation.

Per KB ADR-002/003, the Protocol defines the interface; implementations swap via env
(``REPOSITORY=memory|postgres``). Every method takes ``AuthClaims`` first and is tenant
scoped — no method works without tenant context. ``tenant_id`` is assigned at creation
time and is immutable thereafter.

``InMemoryRepository`` is the dev/test implementation and the reusable test double every
downstream service uses in place of Postgres. It enforces the same isolation rules the
SQL layer does (a query simply never returns another tenant's rows).
"""
from __future__ import annotations

import uuid
from typing import Any, Protocol, runtime_checkable

from common.auth import AuthClaims
from common.errors import NotFoundError, ValidationError
from common.tenancy import resolve_write_tenant_id

Row = dict[str, Any]


@runtime_checkable
class Repository(Protocol):
    """Tenant-scoped data access contract. All methods require ``claims``."""

    async def get(self, claims: AuthClaims, id: str) -> Row | None: ...
    async def list(self, claims: AuthClaims, **filters: Any) -> list[Row]: ...
    async def create(self, claims: AuthClaims, data: Row) -> Row: ...
    async def update(self, claims: AuthClaims, id: str, changes: Row) -> Row: ...
    async def delete(self, claims: AuthClaims, id: str) -> None: ...


class InMemoryRepository:
    """In-memory, tenant-enforcing repository (dev/tests/test double)."""

    def __init__(self, table: str) -> None:
        self.table = table
        self._rows: dict[str, Row] = {}

    def _visible(self, claims: AuthClaims, row: Row) -> bool:
        return claims.is_global or row.get("tenant_id") == claims.tenant_id

    async def get(self, claims: AuthClaims, id: str) -> Row | None:
        row = self._rows.get(id)
        if row is None or not self._visible(claims, row):
            return None  # no existence leak across tenants
        return dict(row)

    async def list(self, claims: AuthClaims, **filters: Any) -> list[Row]:
        result = []
        for row in self._rows.values():
            if not self._visible(claims, row):
                continue
            if all(row.get(k) == v for k, v in filters.items()):
                result.append(dict(row))
        return result

    async def create(self, claims: AuthClaims, data: Row) -> Row:
        tenant_id = resolve_write_tenant_id(claims, data.get("tenant_id"))
        row = dict(data)
        row["tenant_id"] = tenant_id
        row.setdefault("id", uuid.uuid4().hex)
        self._rows[row["id"]] = row
        return dict(row)

    async def update(self, claims: AuthClaims, id: str, changes: Row) -> Row:
        row = self._rows.get(id)
        if row is None or not self._visible(claims, row):
            raise NotFoundError(f"{self.table} {id} not found")
        if "tenant_id" in changes and changes["tenant_id"] != row["tenant_id"]:
            raise ValidationError(
                "tenant_id is immutable.", code="TENANT_ID_IMMUTABLE"
            )
        updated = {**row, **changes, "tenant_id": row["tenant_id"], "id": row["id"]}
        self._rows[id] = updated
        return dict(updated)

    async def delete(self, claims: AuthClaims, id: str) -> None:
        row = self._rows.get(id)
        if row is None or not self._visible(claims, row):
            raise NotFoundError(f"{self.table} {id} not found")
        del self._rows[id]
