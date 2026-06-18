"""Tenancy + RBAC helpers — where multi-tenant isolation is *guaranteed*.

Multi-tenancy is a data-access concern (CLAUDE.md §3, KB ADR-003): it is enforced
where data is accessed, not at the API edge. These helpers make the safe path the
only easy path so no repository hand-rolls a tenant filter.

- ``tenant_filter``       — composable parameterized SQL fragment (or empty for global admin).
- ``assert_tenant_access``— guard a fetched row, even when fetched by primary key.
- ``require_role``        — RBAC gate (authorization is a filter/guard, not a UI concern).
- ``resolve_write_tenant_id`` — decide the tenant a write belongs to WITHOUT trusting input.
"""
from __future__ import annotations

import re

from common.auth import AuthClaims
from common.errors import AuthorizationError, ValidationError

# Column names are developer-supplied constants, never user input — but validate
# anyway so a typo/injection can never reach the SQL string.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_column(column: str) -> str:
    if not _IDENTIFIER_RE.match(column):
        raise ValidationError(
            f"Unsafe SQL identifier for tenant column: {column!r}",
            code="INVALID_SQL_IDENTIFIER",
        )
    return column


def tenant_filter(
    claims: AuthClaims, *, next_param: int = 1, column: str = "tenant_id"
) -> tuple[str, list[str]]:
    """Return a parameterized ``AND`` fragment scoping a query to the caller's tenant.

    - Global admin (``tenant_id is None``) → ``("", [])`` (no tenant restriction).
    - Otherwise → ``("AND <column> = $<next_param>", [tenant_id])``.

    The fragment is meant to be appended to a ``WHERE`` clause; ``next_param`` must be
    the next free positional placeholder index in the query being built.
    """
    _validate_column(column)
    if claims.is_global:
        return "", []
    assert claims.tenant_id is not None  # narrowed by is_global  # noqa: S101
    return f"AND {column} = ${next_param}", [claims.tenant_id]


def assert_tenant_access(claims: AuthClaims, row_tenant_id: str | None) -> None:
    """Raise ``AuthorizationError`` if ``claims`` may not touch a row of this tenant.

    Runs even for reads fetched by primary key — a row's ``tenant_id`` must always be
    re-checked against the caller. Global admins bypass the tenant restriction.
    """
    if claims.is_global:
        return
    if row_tenant_id is None or row_tenant_id != claims.tenant_id:
        raise AuthorizationError(
            "Cross-tenant access is not permitted.",
            code="CROSS_TENANT_ACCESS",
        )


def require_role(claims: AuthClaims, *allowed: object) -> None:
    """Raise ``AuthorizationError`` unless the caller holds one of ``allowed`` roles."""
    if claims.role not in allowed:
        raise AuthorizationError(
            "Your role is not permitted to perform this action.",
            code="ROLE_NOT_PERMITTED",
        )


def resolve_write_tenant_id(
    claims: AuthClaims, requested: str | None = None
) -> str:
    """Return the tenant a write belongs to, never trusting caller-supplied input.

    - Scoped roles: the write is forced onto ``claims.tenant_id``. A ``requested``
      value that disagrees is a cross-tenant attempt and is rejected.
    - Global admin: must name an explicit target tenant (there is no implicit one).
    """
    if claims.is_global:
        if not requested or not requested.strip():
            raise ValidationError(
                "A target tenant_id is required for a global-admin write.",
                code="TENANT_ID_REQUIRED",
            )
        return requested
    assert claims.tenant_id is not None  # narrowed by is_global  # noqa: S101
    if requested is not None and requested != claims.tenant_id:
        raise AuthorizationError(
            "Cannot write to a different tenant than your own.",
            code="CROSS_TENANT_WRITE",
        )
    return claims.tenant_id
