"""Seam re-verification for S12.7 (platform-admin tenant-explicit super-user).

No code changes in ``common`` for this sprint (D7) — this file proves, from
source, that a *derived* ``AuthClaims`` shaped like
``AuthClaims(role=CLIENT_ADMIN, tenant_id=X)`` (the shape
``api.auth.dependencies.resolve_tenant_scope`` constructs for a platform admin
reaching tenant X) is byte-for-byte indistinguishable from a *real*
CLIENT_ADMIN of X at the ``tenant_filter``/``assert_tenant_access``/
``resolve_write_tenant_id`` layer. This is the load-bearing guarantee the
whole sprint depends on: every repository that already filters by
``claims.tenant_id`` behaves correctly for a platform-admin-derived caller
for free, with zero repository changes.
"""
from __future__ import annotations

import pytest

from common.auth import AuthClaims, Role
from common.errors import AuthorizationError
from common.tenancy import assert_tenant_access, resolve_write_tenant_id, tenant_filter


def _derived_claims(tenant_id: str) -> AuthClaims:
    """The exact shape resolve_tenant_scope derives for a platform admin on tenant_id."""
    return AuthClaims(subject="platform-admin-1", role=Role.CLIENT_ADMIN, tenant_id=tenant_id)


def _real_client_admin(tenant_id: str) -> AuthClaims:
    return AuthClaims(subject="real-admin-1", role=Role.CLIENT_ADMIN, tenant_id=tenant_id)


# --------------------------------------------------------------- tenant_filter


def test_derived_claims_tenant_filter_matches_real_client_admin() -> None:
    derived_frag, derived_params = tenant_filter(_derived_claims("tenant-x"))
    real_frag, real_params = tenant_filter(_real_client_admin("tenant-x"))

    assert derived_frag == real_frag == "AND tenant_id = $1"
    assert derived_params == real_params == ["tenant-x"]


def test_derived_claims_tenant_filter_respects_param_index() -> None:
    frag, params = tenant_filter(_derived_claims("tenant-x"), next_param=3)
    assert frag == "AND tenant_id = $3"
    assert params == ["tenant-x"]


# ------------------------------------------------------------ assert_tenant_access


def test_derived_claims_can_access_own_target_tenant() -> None:
    assert_tenant_access(_derived_claims("tenant-x"), "tenant-x")


def test_derived_claims_cannot_access_a_different_tenant() -> None:
    """Even a platform-admin-derived caller is bound to X once tenant_id=X;
    it can never reach tenant Y through assert_tenant_access."""
    with pytest.raises(AuthorizationError):
        assert_tenant_access(_derived_claims("tenant-x"), "tenant-y")


# --------------------------------------------------------- resolve_write_tenant_id


def test_derived_claims_write_forced_onto_target_tenant() -> None:
    assert resolve_write_tenant_id(_derived_claims("tenant-x")) == "tenant-x"
    assert (
        resolve_write_tenant_id(_derived_claims("tenant-x"), requested="tenant-x") == "tenant-x"
    )


def test_derived_claims_write_rejects_mismatched_requested_tenant() -> None:
    """A derived claims object requesting tenant Y while scoped to X is a
    cross-tenant write attempt -- rejected exactly like a real CLIENT_ADMIN."""
    with pytest.raises(AuthorizationError):
        resolve_write_tenant_id(_derived_claims("tenant-x"), requested="tenant-y")
