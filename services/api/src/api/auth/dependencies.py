"""Auth dependencies -- resolve AuthClaims from the request cookie.

``get_current_claims`` reads the JWT from the httpOnly cookie, validates it,
checks the Redis jti-blacklist (S1.4), and returns ``AuthClaims``.
``require_roles`` is a dependency factory that additionally enforces RBAC.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from common.auth import AuthClaims, Role
from common.errors import AuthenticationError
from common.tenancy import require_role
from fastapi import Depends, Request

from api.auth.blacklist import get_token_blacklist
from api.auth.tokens import claims_from_payload, decode_access_token
from api.config import get_api_settings


async def get_current_claims(request: Request) -> AuthClaims:
    """Extract and validate AuthClaims from the access-token cookie.

    Raises ``AuthenticationError`` (401) when the cookie is missing, the token
    is invalid, the token has expired, or the token's jti is blacklisted
    (logged out). The blacklist check is fail-closed: a Redis error denies
    the request.
    """
    settings = get_api_settings()
    token: str | None = request.cookies.get(settings.cookie_name)
    if token is None:
        raise AuthenticationError("Authentication is required.")

    payload = decode_access_token(token, secret=settings.jwt_secret)

    # Redis jti-blacklist check (S1.4). Fail-closed: RedisTokenBlacklist
    # raises AuthenticationError on RedisError.
    jti = payload.get("jti")
    if jti and await get_token_blacklist(request).is_revoked(str(jti)):
        raise AuthenticationError("Session has been revoked.")

    return claims_from_payload(payload)


def require_roles(
    *roles: Role,
) -> Callable[..., Coroutine[Any, Any, AuthClaims]]:
    """Dependency factory: resolve claims then enforce RBAC.

    Usage::

        @router.get("/admin-only")
        async def admin_only(
            claims: AuthClaims = Depends(require_roles(Role.PLATFORM_ADMIN)),
        ) -> ...:
    """

    async def _dependency(
        claims: AuthClaims = Depends(get_current_claims),  # noqa: B008
    ) -> AuthClaims:
        require_role(claims, *roles)
        return claims

    return _dependency
