"""Unit tests for the AppException hierarchy.

The error codes and HTTP statuses are part of the public API contract the gateway
error middleware relies on (see CLAUDE.md §3 and platform-foundations).
"""
import pytest

from common.errors import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


def test_base_is_exception() -> None:
    assert issubclass(AppException, Exception)


@pytest.mark.parametrize(
    ("exc_cls", "code", "status"),
    [
        (NotFoundError, "NOT_FOUND", 404),
        (ValidationError, "VALIDATION_ERROR", 422),
        (AuthenticationError, "UNAUTHENTICATED", 401),
        (AuthorizationError, "FORBIDDEN", 403),
        (RateLimitError, "RATE_LIMITED", 429),
        (InternalServerError, "INTERNAL_ERROR", 500),
    ],
)
def test_code_and_status_contract(
    exc_cls: type[AppException], code: str, status: int
) -> None:
    exc = exc_cls()
    assert exc.code == code
    assert exc.http_status == status
    assert isinstance(exc, AppException)


def test_all_codes_are_upper_snake_case() -> None:
    for exc_cls in (
        NotFoundError,
        ValidationError,
        AuthenticationError,
        AuthorizationError,
        RateLimitError,
        InternalServerError,
    ):
        code = exc_cls().code
        assert code == code.upper()
        assert " " not in code


def test_default_message_is_user_safe_string() -> None:
    exc = NotFoundError()
    assert isinstance(exc.message, str)
    assert exc.message  # non-empty
    # the message is also the Exception str representation
    assert str(exc) == exc.message


def test_custom_message_overrides_default() -> None:
    exc = NotFoundError("Lead 123 does not exist")
    assert exc.message == "Lead 123 does not exist"


def test_details_default_empty_and_settable() -> None:
    assert NotFoundError().details == {}
    exc = ValidationError("bad", details={"field": "email"})
    assert exc.details == {"field": "email"}


def test_to_dict_is_user_safe_payload() -> None:
    exc = ValidationError("Email is required", details={"field": "email"})
    payload = exc.to_dict()
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["message"] == "Email is required"
    # to_dict must NOT leak internal details by default (gateway adds correlation_id)
    assert "details" not in payload


def test_rate_limit_carries_optional_retry_after() -> None:
    exc = RateLimitError(retry_after=30)
    assert exc.retry_after == 30
    assert RateLimitError().retry_after is None


def test_code_can_be_overridden_per_instance() -> None:
    exc = ValidationError("bad", code="LEAD_INVALID")
    assert exc.code == "LEAD_INVALID"
    # but the class default is unchanged
    assert ValidationError().code == "VALIDATION_ERROR"
