"""JWT token creation and validation (HS256).

Tokens carry ``{sub, role, tenant_id, project_ids, iat, exp, jti}`` and are
signed with the platform ``jwt_secret``. The ``jti`` (JWT ID) is a hex uuid
used by the logout blacklist (S1.4).
"""
from __future__ import annotations

import datetime as _dt
from uuid import uuid4

import jwt
from common.auth import AuthClaims, Role
from common.errors import AuthenticationError


def create_access_token(
    claims: AuthClaims,
    *,
    secret: str,
    ttl_seconds: int,
) -> tuple[str, str]:
    """Encode an HS256 JWT from *claims*. Returns ``(token, jti)``."""
    jti = uuid4().hex
    now = _dt.datetime.now(_dt.UTC)
    payload: dict[str, object] = {
        "sub": claims.subject,
        "role": claims.role.value,
        "tenant_id": claims.tenant_id,
        "project_ids": list(claims.project_ids),
        "iat": now,
        "exp": now + _dt.timedelta(seconds=ttl_seconds),
        "jti": jti,
    }
    token: str = jwt.encode(payload, secret, algorithm="HS256")
    return token, jti


def decode_access_token(token: str, *, secret: str) -> dict[str, object]:
    """Decode and validate an HS256 JWT. Raises ``AuthenticationError`` on failure."""
    try:
        payload: dict[str, object] = jwt.decode(
            token, secret, algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token.") from exc
    return payload


def claims_from_payload(payload: dict[str, object]) -> AuthClaims:
    """Reconstruct ``AuthClaims`` from a decoded JWT payload."""
    sub = str(payload["sub"])
    role = Role(str(payload["role"]))
    raw_tenant = payload.get("tenant_id")
    tenant_id = str(raw_tenant) if raw_tenant is not None else None
    raw_projects = payload.get("project_ids")
    project_ids: tuple[str, ...] = ()
    if isinstance(raw_projects, list):
        project_ids = tuple(str(p) for p in raw_projects)
    return AuthClaims(
        subject=sub,
        role=role,
        tenant_id=tenant_id,
        project_ids=project_ids,
    )
