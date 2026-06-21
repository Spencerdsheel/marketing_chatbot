"""Gateway dependencies -- resolve VISITOR AuthClaims from bearer token.

``get_visitor_claims`` reads the ``Authorization: Bearer`` header, validates
the JWT, and ensures the role is VISITOR. Used by widget endpoints that
require an authenticated visitor session.
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from common.errors import AuthenticationError, AuthorizationError
from fastapi import Request

from api.auth.tokens import claims_from_payload, decode_access_token
from api.config import get_api_settings


async def get_visitor_claims(request: Request) -> AuthClaims:
    """Extract and validate VISITOR AuthClaims from the bearer token.

    Raises ``AuthenticationError`` (401) when the header is missing or the
    token is invalid/expired. Raises ``AuthorizationError`` (403) when the
    token's role is not VISITOR.
    """
    auth_header: str | None = request.headers.get("authorization")
    if auth_header is None or not auth_header.startswith("Bearer "):
        raise AuthenticationError("A visitor session is required.")

    token = auth_header[7:]  # strip "Bearer "
    settings = get_api_settings()
    payload = decode_access_token(token, secret=settings.jwt_secret)
    claims = claims_from_payload(payload)

    if claims.role is not Role.VISITOR:
        raise AuthorizationError("This endpoint requires a visitor session.", code="NOT_A_VISITOR")

    return claims
