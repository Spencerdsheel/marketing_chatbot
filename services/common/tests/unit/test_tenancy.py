"""Unit tests for tenancy/RBAC helpers — the heart of multi-tenant isolation.

These cover all four roles. Multi-tenant isolation and RBAC tests are MANDATORY
(CLAUDE.md §3 testing).
"""
import pytest

from common.auth import AuthClaims, Role
from common.errors import AuthorizationError, ValidationError
from common.tenancy import (
    assert_tenant_access,
    require_role,
    resolve_write_tenant_id,
    tenant_filter,
)


def claims(role: Role, tenant_id: str | None) -> AuthClaims:
    return AuthClaims(subject="s", role=role, tenant_id=tenant_id)


# ---------------------------------------------------------------- tenant_filter

def test_tenant_filter_global_admin_has_no_filter() -> None:
    frag, params = tenant_filter(claims(Role.PLATFORM_ADMIN, None))
    assert frag == ""
    assert params == []


@pytest.mark.parametrize("role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR])
def test_tenant_filter_scopes_non_global_roles(role: Role) -> None:
    frag, params = tenant_filter(claims(role, "tenant-a"))
    assert frag == "AND tenant_id = $1"
    assert params == ["tenant-a"]


def test_tenant_filter_respects_param_index() -> None:
    frag, params = tenant_filter(claims(Role.CLIENT_ADMIN, "t"), next_param=3)
    assert frag == "AND tenant_id = $3"
    assert params == ["t"]


def test_tenant_filter_custom_column() -> None:
    frag, _ = tenant_filter(claims(Role.CLIENT_ADMIN, "t"), column="org_id")
    assert frag == "AND org_id = $1"


def test_tenant_filter_rejects_unsafe_column() -> None:
    with pytest.raises(ValidationError):
        tenant_filter(claims(Role.CLIENT_ADMIN, "t"), column="tenant_id; DROP TABLE x")


# --------------------------------------------------------- assert_tenant_access

def test_global_admin_can_access_any_row() -> None:
    assert_tenant_access(claims(Role.PLATFORM_ADMIN, None), "tenant-a")
    assert_tenant_access(claims(Role.PLATFORM_ADMIN, None), "tenant-b")


@pytest.mark.parametrize("role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR])
def test_same_tenant_access_allowed(role: Role) -> None:
    assert_tenant_access(claims(role, "tenant-a"), "tenant-a")


@pytest.mark.parametrize("role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR])
def test_cross_tenant_access_denied(role: Role) -> None:
    with pytest.raises(AuthorizationError):
        assert_tenant_access(claims(role, "tenant-a"), "tenant-b")


def test_access_denied_when_row_tenant_missing_for_scoped_caller() -> None:
    with pytest.raises(AuthorizationError):
        assert_tenant_access(claims(Role.CLIENT_AGENT, "tenant-a"), None)


# ------------------------------------------------------------------ require_role

def test_require_role_allows_listed_role() -> None:
    require_role(claims(Role.CLIENT_ADMIN, "t"), Role.CLIENT_ADMIN, Role.PLATFORM_ADMIN)


def test_require_role_denies_unlisted_role() -> None:
    # an agent may not perform a config action restricted to admins
    with pytest.raises(AuthorizationError):
        require_role(claims(Role.CLIENT_AGENT, "t"), Role.CLIENT_ADMIN, Role.PLATFORM_ADMIN)


# --------------------------------------------------------- resolve_write_tenant_id

def test_scoped_writer_gets_own_tenant() -> None:
    assert resolve_write_tenant_id(claims(Role.CLIENT_ADMIN, "tenant-a")) == "tenant-a"


def test_scoped_writer_cannot_target_other_tenant() -> None:
    # tenant_id is never taken from input: a mismatched explicit target is rejected
    with pytest.raises(AuthorizationError):
        resolve_write_tenant_id(claims(Role.CLIENT_ADMIN, "tenant-a"), requested="tenant-b")


def test_scoped_writer_may_pass_matching_tenant() -> None:
    assert resolve_write_tenant_id(
        claims(Role.CLIENT_ADMIN, "tenant-a"), requested="tenant-a"
    ) == "tenant-a"


def test_global_admin_must_specify_target_tenant() -> None:
    assert resolve_write_tenant_id(
        claims(Role.PLATFORM_ADMIN, None), requested="tenant-x"
    ) == "tenant-x"
    with pytest.raises(ValidationError):
        resolve_write_tenant_id(claims(Role.PLATFORM_ADMIN, None))
