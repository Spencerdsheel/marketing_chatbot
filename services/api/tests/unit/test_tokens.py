"""Unit tests for api.auth.tokens -- JWT creation, decoding, claims reconstruction."""
from __future__ import annotations

import datetime as _dt
from unittest.mock import patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import AuthenticationError

from api.auth.tokens import claims_from_payload, create_access_token, decode_access_token

# Non-secret test value -- not a real credential.
_SECRET = "x" * 48
_OTHER_SECRET = "y" * 48


# -- Round-trip ----------------------------------------------------------------


def test_create_and_decode_round_trip() -> None:
    """A token created with create_access_token decodes back via decode_access_token."""
    claims = AuthClaims(
        subject="user-1",
        role=Role.CLIENT_ADMIN,
        tenant_id="tenant-abc",
        project_ids=("p1", "p2"),
    )
    token, jti = create_access_token(claims, secret=_SECRET, ttl_seconds=300)

    payload = decode_access_token(token, secret=_SECRET)

    assert payload["sub"] == "user-1"
    assert payload["role"] == "CLIENT_ADMIN"
    assert payload["tenant_id"] == "tenant-abc"
    assert payload["project_ids"] == ["p1", "p2"]
    assert payload["jti"] == jti
    # exp is in the future
    assert payload["exp"] > _dt.datetime.now(_dt.UTC).timestamp()


# -- Payload shape -------------------------------------------------------------


def test_payload_contains_required_fields() -> None:
    claims = AuthClaims(subject="u", role=Role.CLIENT_AGENT, tenant_id="t1")
    token, jti = create_access_token(claims, secret=_SECRET, ttl_seconds=60)
    payload = decode_access_token(token, secret=_SECRET)
    for key in ("sub", "role", "tenant_id", "project_ids", "iat", "exp", "jti"):
        assert key in payload, f"missing key: {key}"


def test_jti_is_unique() -> None:
    claims = AuthClaims(subject="u", role=Role.CLIENT_AGENT, tenant_id="t1")
    _, jti1 = create_access_token(claims, secret=_SECRET, ttl_seconds=60)
    _, jti2 = create_access_token(claims, secret=_SECRET, ttl_seconds=60)
    assert jti1 != jti2


# -- Rejection: tampered token ------------------------------------------------


def test_tampered_token_raises() -> None:
    claims = AuthClaims(subject="u", role=Role.CLIENT_AGENT, tenant_id="t1")
    token, _ = create_access_token(claims, secret=_SECRET, ttl_seconds=300)
    tampered = token[:-4] + "XXXX"
    with pytest.raises(AuthenticationError):
        decode_access_token(tampered, secret=_SECRET)


# -- Rejection: wrong secret --------------------------------------------------


def test_wrong_secret_raises() -> None:
    claims = AuthClaims(subject="u", role=Role.CLIENT_AGENT, tenant_id="t1")
    token, _ = create_access_token(claims, secret=_SECRET, ttl_seconds=300)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=_OTHER_SECRET)


# -- Rejection: expired token -------------------------------------------------


def test_expired_token_raises() -> None:
    claims = AuthClaims(subject="u", role=Role.CLIENT_AGENT, tenant_id="t1")
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=2)
    with patch("api.auth.tokens._dt") as mock_dt:
        mock_dt.UTC = _dt.UTC
        mock_dt.datetime.now.return_value = past
        mock_dt.timedelta = _dt.timedelta
        token, _ = create_access_token(claims, secret=_SECRET, ttl_seconds=60)
    with pytest.raises(AuthenticationError, match="expired"):
        decode_access_token(token, secret=_SECRET)


# -- claims_from_payload: CLIENT_ADMIN -----------------------------------------


def test_claims_from_payload_client_admin() -> None:
    payload = {
        "sub": "user-42",
        "role": "CLIENT_ADMIN",
        "tenant_id": "tenant-xyz",
        "project_ids": ["p1"],
    }
    result = claims_from_payload(payload)
    assert result.subject == "user-42"
    assert result.role is Role.CLIENT_ADMIN
    assert result.tenant_id == "tenant-xyz"
    assert result.project_ids == ("p1",)


# -- claims_from_payload: PLATFORM_ADMIN (null tenant) ------------------------


def test_claims_from_payload_platform_admin_null_tenant() -> None:
    payload = {
        "sub": "admin-1",
        "role": "PLATFORM_ADMIN",
        "tenant_id": None,
        "project_ids": [],
    }
    result = claims_from_payload(payload)
    assert result.role is Role.PLATFORM_ADMIN
    assert result.tenant_id is None


# -- Garbage token -------------------------------------------------------------


def test_garbage_string_raises() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.jwt", secret=_SECRET)
