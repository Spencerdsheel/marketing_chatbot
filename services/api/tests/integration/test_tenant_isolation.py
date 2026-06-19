"""Integration test — real two-tenant A/B isolation check.

Marked ``integration``; skipped when ``TEST_DATABASE_URL`` is not set.
The fixture creates the ``tenants`` table from the migration DDL in the test DB.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from common.auth import AuthClaims, Role
from common.db import Database

from api.tenants.repository import TenantRepository

pytestmark = pytest.mark.integration

_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

if not _TEST_DB_URL:
    pytest.skip("TEST_DATABASE_URL not set — skipping integration tests", allow_module_level=True)


@pytest.fixture
async def db() -> Any:
    """Create a live Database, set up the tenants table, yield, then tear down."""
    assert _TEST_DB_URL is not None
    database = await Database.connect(_TEST_DB_URL, min_size=1, max_size=2, statement_cache_size=0)

    # Create table from migration DDL
    await database.execute("DROP TABLE IF EXISTS users")
    await database.execute("DROP TABLE IF EXISTS tenants")
    await database.execute("""
        CREATE TABLE tenants (
            id          text PRIMARY KEY,
            name        text NOT NULL,
            slug        text NOT NULL UNIQUE,
            enabled     boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    yield database

    await database.execute("DROP TABLE IF EXISTS users")
    await database.execute("DROP TABLE IF EXISTS tenants")
    await database.close()


_PLATFORM_ADMIN = AuthClaims(
    subject="admin-global", role=Role.PLATFORM_ADMIN, tenant_id=None
)


async def test_tenant_isolation_a_b(db: Database) -> None:
    """CLIENT_ADMIN scoped to tenant A must not see tenant B."""
    repo = TenantRepository(db)

    # Create two tenants as platform admin
    tenant_a = await repo.create(
        _PLATFORM_ADMIN, {"name": "Tenant A", "slug": f"a-{uuid4().hex[:8]}"}
    )
    tenant_b = await repo.create(
        _PLATFORM_ADMIN, {"name": "Tenant B", "slug": f"b-{uuid4().hex[:8]}"}
    )

    # CLIENT_ADMIN scoped to A
    admin_a = AuthClaims(
        subject="user-a", role=Role.CLIENT_ADMIN, tenant_id=tenant_a["id"]
    )

    # list: A should see only their own tenant
    visible = await repo.list(admin_a)
    visible_ids = [t["id"] for t in visible]
    assert tenant_a["id"] in visible_ids
    assert tenant_b["id"] not in visible_ids

    # get(A): should return tenant A
    result_a = await repo.get(admin_a, tenant_a["id"])
    assert result_a is not None
    assert result_a["id"] == tenant_a["id"]

    # get(B): should return None (cross-tenant)
    result_b = await repo.get(admin_a, tenant_b["id"])
    assert result_b is None

    # Platform admin sees both
    all_tenants = await repo.list(_PLATFORM_ADMIN)
    all_ids = [t["id"] for t in all_tenants]
    assert tenant_a["id"] in all_ids
    assert tenant_b["id"] in all_ids
