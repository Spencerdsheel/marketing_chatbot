"""Auth routes -- login, logout, and identity endpoints.

POST /auth/login authenticates by email + password and issues an HS256 JWT in
an httpOnly cookie. The token is NEVER returned in the response body. All
failure modes (unknown email, wrong password, inactive user) return the same
401 UNAUTHENTICATED to prevent user enumeration.

POST /auth/logout revokes the token's jti in Redis and clears the cookie.
Invalid/expired tokens are rejected with 401 (strict).
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from common.crypto import hash_password, verify_password
from common.errors import AuthenticationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from api.auth.blacklist import get_token_blacklist, remaining_ttl
from api.auth.dependencies import get_current_claims
from api.auth.password_reset import get_password_reset_store
from api.auth.repository import get_user_by_email, set_password_hash
from api.auth.tokens import create_access_token, decode_access_token
from api.config import get_api_settings
from api.ratelimit import client_ip, enforce_rate_limit

_log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic message -- identical for every auth failure to block enumeration.
_AUTH_FAILED_MSG = "Invalid email or password."


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: str
    password: str


class LoginProfile(BaseModel):
    """Successful login response (no token, no password_hash)."""

    id: str
    email: str
    role: str
    tenant_id: str | None
    name: str | None


@router.post("/login", response_model=LoginProfile)
async def login(body: LoginRequest, request: Request, response: Response) -> LoginProfile:
    """Authenticate by email + password; set JWT cookie."""
    settings = get_api_settings()

    # Rate limit by IP before any DB work.
    await enforce_rate_limit(
        request,
        scope="auth_login_ip",
        identifier=client_ip(request),
        limit=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    db = request.app.state.db

    # 1. Resolve identity (unscoped -- pre-auth)
    row = await get_user_by_email(db, body.email)

    if row is None:
        _log.info("login attempt for unknown email", extra={"event": "login_failed"})
        raise AuthenticationError(_AUTH_FAILED_MSG)

    # 2. Check active status
    is_active: bool = row.get("active", True)
    if not is_active:
        _log.info(
            "login attempt for inactive user",
            extra={"event": "login_failed"},
        )
        raise AuthenticationError(_AUTH_FAILED_MSG)

    # 3. Verify password (constant-time)
    if not verify_password(body.password, row["password_hash"]):
        _log.info(
            "login attempt with wrong password",
            extra={"event": "login_failed"},
        )
        raise AuthenticationError(_AUTH_FAILED_MSG)

    # 4. Build claims from the user row
    user_id: str = str(row["id"])
    role = Role(row["role"])
    tenant_id: str | None = str(row["tenant_id"]) if row.get("tenant_id") is not None else None

    claims = AuthClaims(
        subject=user_id,
        role=role,
        tenant_id=tenant_id,
    )

    # 5. Mint token
    ttl = settings.access_token_ttl_seconds
    token, _jti = create_access_token(claims, secret=settings.jwt_secret, ttl_seconds=ttl)

    # 6. Set httpOnly cookie
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=ttl,
        path="/",
    )

    # 7. Best-effort update last_login_at
    try:
        await db.execute(
            "UPDATE users SET last_login_at = now() WHERE id = $1",
            user_id,
        )
    except Exception:
        _log.warning(
            "failed to update last_login_at",
            extra={"event": "last_login_update_failed"},
        )

    _log.info("user logged in", extra={"event": "login_success"})

    # 8. Return profile (no token, no password_hash)
    return LoginProfile(
        id=user_id,
        email=row["email"],
        role=role.value,
        tenant_id=tenant_id,
        name=row.get("name"),
    )


class MeResponse(BaseModel):
    """Response model for GET /auth/me."""

    subject: str
    role: str
    tenant_id: str | None
    project_ids: list[str]


@router.get("/me", response_model=MeResponse)
async def me(
    claims: AuthClaims = Depends(get_current_claims),  # noqa: B008
) -> MeResponse:
    """Return the authenticated caller's identity claims."""
    return MeResponse(
        subject=claims.subject,
        role=claims.role.value,
        tenant_id=claims.tenant_id,
        project_ids=list(claims.project_ids),
    )


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Revoke the current token (blacklist jti in Redis) and clear the cookie.

    Strict: no cookie → 401; invalid/expired token → 401 (no cookie cleared).
    """
    settings = get_api_settings()
    token: str | None = request.cookies.get(settings.cookie_name)

    if token is None:
        raise AuthenticationError("Authentication is required.")

    # decode_access_token raises AuthenticationError on invalid/expired/tampered.
    # Do NOT catch it -- let it propagate as 401 (strict).
    payload = decode_access_token(token, secret=settings.jwt_secret)

    jti = str(payload["jti"])
    ttl = max(1, int(remaining_ttl(payload.get("exp"))))

    # Revoke -- propagates on RedisError (fail-closed).
    await get_token_blacklist(request).revoke(jti, ttl)

    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        samesite=settings.cookie_samesite,
    )

    _log.info("user logged out", extra={"event": "logout_success"})
    return {"status": "logged_out"}


# -- Password reset ------------------------------------------------------------


class PasswordResetRequest(BaseModel):
    """Body for POST /auth/password-reset/request."""

    email: str


class PasswordResetConfirm(BaseModel):
    """Body for POST /auth/password-reset/confirm."""

    token: str
    new_password: str = Field(min_length=12)


@router.post("/password-reset/request")
async def password_reset_request(
    body: PasswordResetRequest,
    request: Request,
) -> dict[str, str]:
    """Issue a single-use, time-limited password reset token.

    Always returns 200 with the same body to prevent user enumeration.
    A token is issued (and optionally logged) only for an existing active user.
    """
    settings = get_api_settings()

    # Rate limit by IP before any DB work.
    await enforce_rate_limit(
        request,
        scope="auth_pwreset_ip",
        identifier=client_ip(request),
        limit=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    db = request.app.state.db

    row = await get_user_by_email(db, body.email)

    if row is not None and row.get("active", True):
        user_id = str(row["id"])
        token = await get_password_reset_store(request).issue(
            user_id, settings.password_reset_ttl_seconds
        )
        if settings.auth_reset_token_log:
            # DEV-ONLY: the token goes in the message because the JSON formatter
            # drops non-allow-listed extra fields (common.logging keeps secrets
            # out of logs). Gated behind auth_reset_token_log; OFF in production.
            _log.warning(
                "DEV password reset token issued: %s",
                token,
                extra={"event": "password_reset_token"},
            )

    # Always same response -- no enumeration.
    return {"status": "reset_requested"}


@router.post("/password-reset/confirm")
async def password_reset_confirm(
    body: PasswordResetConfirm,
    request: Request,
) -> dict[str, str]:
    """Validate a reset token and write a new password hash.

    Single-use: the token is consumed atomically (Redis GETDEL).
    """
    db = request.app.state.db

    user_id = await get_password_reset_store(request).consume(body.token)
    if user_id is None:
        raise AuthenticationError("Invalid or expired reset token.")

    await set_password_hash(db, user_id, hash_password(body.new_password))
    _log.info(
        "password reset completed",
        extra={"event": "password_reset_success", "user_id": user_id},
    )
    return {"status": "password_reset"}
