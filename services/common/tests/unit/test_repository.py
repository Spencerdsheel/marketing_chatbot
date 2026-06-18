"""Unit tests for the Repository Protocol + InMemoryRepository.

Multi-tenant isolation is MANDATORY: tenant A must never see tenant B's rows.
The InMemoryRepository is also the reusable test double for downstream services.
"""
import pytest

from common.auth import AuthClaims, Role
from common.errors import AuthorizationError, NotFoundError, ValidationError
from common.repository import InMemoryRepository, Repository


def claims(role: Role, tenant_id: str | None) -> AuthClaims:
    return AuthClaims(subject="s", role=role, tenant_id=tenant_id)


A = claims(Role.CLIENT_ADMIN, "tenant-a")
B = claims(Role.CLIENT_ADMIN, "tenant-b")
ADMIN = claims(Role.PLATFORM_ADMIN, None)


def repo() -> InMemoryRepository:
    return InMemoryRepository("leads")


def test_satisfies_protocol() -> None:
    assert isinstance(repo(), Repository)


async def test_create_assigns_tenant_and_id() -> None:
    r = repo()
    row = await r.create(A, {"name": "Ada"})
    assert row["tenant_id"] == "tenant-a"
    assert row["id"]
    assert row["name"] == "Ada"


async def test_create_and_get_roundtrip() -> None:
    r = repo()
    created = await r.create(A, {"name": "Ada"})
    fetched = await r.get(A, created["id"])
    assert fetched == created


async def test_isolation_get_other_tenant_returns_none() -> None:
    r = repo()
    created = await r.create(A, {"name": "secret"})
    assert await r.get(B, created["id"]) is None  # tenant B cannot read tenant A


async def test_isolation_list_only_own_tenant() -> None:
    r = repo()
    await r.create(A, {"name": "a1"})
    await r.create(A, {"name": "a2"})
    await r.create(B, {"name": "b1"})
    assert {row["name"] for row in await r.list(A)} == {"a1", "a2"}
    assert {row["name"] for row in await r.list(B)} == {"b1"}


async def test_global_admin_sees_all_and_any() -> None:
    r = repo()
    a = await r.create(A, {"name": "a1"})
    await r.create(B, {"name": "b1"})
    assert len(await r.list(ADMIN)) == 2
    assert (await r.get(ADMIN, a["id"]))["name"] == "a1"


async def test_scoped_writer_cannot_inject_other_tenant() -> None:
    r = repo()
    with pytest.raises(AuthorizationError):
        await r.create(A, {"name": "x", "tenant_id": "tenant-b"})


async def test_global_admin_must_name_tenant_on_create() -> None:
    r = repo()
    with pytest.raises(ValidationError):
        await r.create(ADMIN, {"name": "x"})  # no tenant_id provided
    row = await r.create(ADMIN, {"name": "x", "tenant_id": "tenant-a"})
    assert row["tenant_id"] == "tenant-a"


async def test_update_changes_fields() -> None:
    r = repo()
    created = await r.create(A, {"name": "old"})
    updated = await r.update(A, created["id"], {"name": "new"})
    assert updated["name"] == "new"
    assert (await r.get(A, created["id"]))["name"] == "new"


async def test_update_tenant_id_is_immutable() -> None:
    r = repo()
    created = await r.create(A, {"name": "x"})
    with pytest.raises(ValidationError):
        await r.update(A, created["id"], {"tenant_id": "tenant-b"})


async def test_update_other_tenant_row_is_not_found() -> None:
    r = repo()
    created = await r.create(A, {"name": "x"})
    with pytest.raises(NotFoundError):
        await r.update(B, created["id"], {"name": "hacked"})


async def test_delete_removes_and_isolated() -> None:
    r = repo()
    created = await r.create(A, {"name": "x"})
    with pytest.raises(NotFoundError):
        await r.delete(B, created["id"])  # cannot delete another tenant's row
    await r.delete(A, created["id"])
    assert await r.get(A, created["id"]) is None


async def test_list_applies_extra_filters() -> None:
    r = repo()
    await r.create(A, {"name": "a1", "status": "new"})
    await r.create(A, {"name": "a2", "status": "won"})
    assert {row["name"] for row in await r.list(A, status="new")} == {"a1"}


async def test_returns_copies_not_internal_refs() -> None:
    r = repo()
    created = await r.create(A, {"name": "x"})
    created["name"] = "mutated-outside"
    assert (await r.get(A, created["id"]))["name"] == "x"
