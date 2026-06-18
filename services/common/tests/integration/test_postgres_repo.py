"""Integration: PostgresRepository enforces tenant isolation against a real DB."""
from collections.abc import Callable

import pytest

from common.auth import AuthClaims, Role
from common.db import Database
from common.errors import NotFoundError, ValidationError
from common.postgres_repo import PostgresRepository

pytestmark = pytest.mark.integration

A = AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="tenant-a")
B = AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="tenant-b")
ADMIN = AuthClaims(subject="s", role=Role.PLATFORM_ADMIN, tenant_id=None)


async def _repo(db: Database, make_table: Callable[[str], object]) -> PostgresRepository:
    table = await make_table(  # type: ignore[misc]
        "id text PRIMARY KEY, tenant_id text NOT NULL, name text, status text"
    )
    return PostgresRepository(db, table)


async def test_create_and_get_roundtrip(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    created = await repo.create(A, {"name": "Ada"})
    assert created["tenant_id"] == "tenant-a"
    fetched = await repo.get(A, created["id"])
    assert fetched is not None
    assert fetched["name"] == "Ada"


async def test_cross_tenant_get_returns_none(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    created = await repo.create(A, {"name": "secret"})
    assert await repo.get(B, created["id"]) is None


async def test_list_isolated_by_tenant(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    await repo.create(A, {"name": "a1"})
    await repo.create(A, {"name": "a2"})
    await repo.create(B, {"name": "b1"})
    assert {r["name"] for r in await repo.list(A)} == {"a1", "a2"}
    assert {r["name"] for r in await repo.list(B)} == {"b1"}
    assert len(await repo.list(ADMIN)) == 3


async def test_list_filters(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    await repo.create(A, {"name": "a1", "status": "new"})
    await repo.create(A, {"name": "a2", "status": "won"})
    assert {r["name"] for r in await repo.list(A, status="new")} == {"a1"}


async def test_scoped_writer_cannot_inject_other_tenant(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    from common.errors import AuthorizationError

    with pytest.raises(AuthorizationError):
        await repo.create(A, {"name": "x", "tenant_id": "tenant-b"})


async def test_update_isolation_and_immutable_tenant(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    created = await repo.create(A, {"name": "old"})
    updated = await repo.update(A, created["id"], {"name": "new"})
    assert updated["name"] == "new"
    with pytest.raises(NotFoundError):
        await repo.update(B, created["id"], {"name": "hacked"})
    with pytest.raises(ValidationError):
        await repo.update(A, created["id"], {"tenant_id": "tenant-b"})


async def test_delete_isolation(db: Database, make_table: Callable[[str], object]) -> None:
    repo = await _repo(db, make_table)
    created = await repo.create(A, {"name": "x"})
    with pytest.raises(NotFoundError):
        await repo.delete(B, created["id"])
    await repo.delete(A, created["id"])
    assert await repo.get(A, created["id"]) is None
