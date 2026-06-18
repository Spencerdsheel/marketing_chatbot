"""Unit tests for Role and AuthClaims — the tenant boundary.

AuthClaims is the ONLY carrier of tenant_id. tenant_id is None exactly for
PLATFORM_ADMIN (global scope); every other role MUST carry a non-empty tenant_id.
"""
import dataclasses

import pytest

from common.auth import AuthClaims, Role
from common.errors import ValidationError


def test_role_is_str_enum_with_stable_values() -> None:
    assert Role.PLATFORM_ADMIN.value == "PLATFORM_ADMIN"
    assert Role.CLIENT_ADMIN.value == "CLIENT_ADMIN"
    assert Role.CLIENT_AGENT.value == "CLIENT_AGENT"
    assert Role.VISITOR.value == "VISITOR"
    # str-enum: comparable/serializable as its string value
    assert Role.VISITOR == "VISITOR"


def test_platform_admin_has_none_tenant_and_is_global() -> None:
    claims = AuthClaims(subject="u1", role=Role.PLATFORM_ADMIN, tenant_id=None)
    assert claims.tenant_id is None
    assert claims.is_platform_admin is True
    assert claims.is_global is True


@pytest.mark.parametrize(
    "role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR]
)
def test_non_platform_roles_require_tenant(role: Role) -> None:
    claims = AuthClaims(subject="s", role=role, tenant_id="tenant-a")
    assert claims.tenant_id == "tenant-a"
    assert claims.is_platform_admin is False
    assert claims.is_global is False


@pytest.mark.parametrize(
    "role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR]
)
def test_non_platform_role_without_tenant_is_rejected(role: Role) -> None:
    with pytest.raises(ValidationError):
        AuthClaims(subject="s", role=role, tenant_id=None)


@pytest.mark.parametrize(
    "role", [Role.CLIENT_ADMIN, Role.CLIENT_AGENT, Role.VISITOR]
)
def test_non_platform_role_with_blank_tenant_is_rejected(role: Role) -> None:
    with pytest.raises(ValidationError):
        AuthClaims(subject="s", role=role, tenant_id="   ")


def test_platform_admin_with_tenant_is_rejected() -> None:
    # PLATFORM_ADMIN is global; carrying a tenant_id is a contradiction.
    with pytest.raises(ValidationError):
        AuthClaims(subject="u", role=Role.PLATFORM_ADMIN, tenant_id="tenant-a")


def test_claims_are_frozen() -> None:
    claims = AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        claims.tenant_id = "other"  # type: ignore[misc]


def test_project_ids_default_and_value() -> None:
    assert AuthClaims(subject="s", role=Role.CLIENT_ADMIN, tenant_id="t").project_ids == ()
    claims = AuthClaims(
        subject="s", role=Role.CLIENT_AGENT, tenant_id="t", project_ids=("p1", "p2")
    )
    assert claims.project_ids == ("p1", "p2")


def test_role_accepts_string_value() -> None:
    claims = AuthClaims(subject="s", role=Role("CLIENT_ADMIN"), tenant_id="t")
    assert claims.role is Role.CLIENT_ADMIN
