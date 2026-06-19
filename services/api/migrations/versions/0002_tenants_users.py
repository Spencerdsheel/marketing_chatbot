"""Add tenants and users tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenants and users tables with tenant-role invariant."""
    op.execute("""
        CREATE TABLE tenants (
            id          text PRIMARY KEY,
            name        text NOT NULL,
            slug        text NOT NULL UNIQUE,
            enabled     boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE users (
            id              text PRIMARY KEY,
            tenant_id       text REFERENCES tenants(id) ON DELETE CASCADE,
            email           text NOT NULL,
            role            text NOT NULL
                CHECK (role IN ('PLATFORM_ADMIN', 'CLIENT_ADMIN', 'CLIENT_AGENT')),
            password_hash   text NOT NULL,
            name            text,
            active          boolean NOT NULL DEFAULT true,
            last_login_at   timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT users_tenant_role_chk CHECK (
                (role = 'PLATFORM_ADMIN' AND tenant_id IS NULL)
                OR (role <> 'PLATFORM_ADMIN' AND tenant_id IS NOT NULL)
            )
        )
    """)

    op.execute(
        "CREATE UNIQUE INDEX users_email_lower_uniq ON users (lower(email))"
    )
    op.execute("CREATE INDEX ix_users_tenant_id ON users (tenant_id)")
    op.execute("CREATE INDEX ix_users_role ON users (role)")


def downgrade() -> None:
    """Drop users then tenants (FK order)."""
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS tenants")
