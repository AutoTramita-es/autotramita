"""Application errors rendered as RFC 9457 problem details (ADR-004, AT-01 O19).

Every error has a stable machine-readable English ``code`` in UPPER_SNAKE_CASE and a
``type`` URI derived from it. Messages never include secrets, SQL, stack traces, submitted
values or the existence of resources in other tenants (404 is used for invisible ones).
The documentation URIs are planned identifiers, not a claim that the pages exist yet.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

PROBLEM_CONTENT_TYPE = "application/problem+json"
ERROR_TYPE_BASE = "https://docs.autotramita.es/errors/"
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def problem_type(code: str) -> str:
    """``RATE_LIMIT_EXCEEDED`` -> ``https://docs.autotramita.es/errors/rate-limit-exceeded``."""
    return ERROR_TYPE_BASE + code.lower().replace("_", "-")


class Problem(BaseModel):
    type: str = Field(description="URI identifying the problem type (planned documentation URI)")
    title: str
    status: int
    detail: str | None = None
    code: str = Field(description="Stable machine-readable error code (UPPER_SNAKE_CASE)")
    request_id: str | None = Field(default=None, description="UUID of the request")
    errors: list[dict[str, str]] | None = Field(
        default=None, description="Field-level validation problems (no input values)"
    )

    @classmethod
    def build(
        cls,
        *,
        status: int,
        title: str,
        code: str,
        detail: str | None = None,
        request_id: str | None = None,
        errors: list[dict[str, str]] | None = None,
    ) -> Problem:
        return cls(
            type=problem_type(code),
            title=title,
            status=status,
            detail=detail,
            code=code,
            request_id=request_id,
            errors=errors,
        )


class AppError(Exception):
    """Base class for expected, client-visible errors."""

    status = 500
    code = "INTERNAL_ERROR"
    title = "Internal error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.headers = headers or {}
        if code is not None:
            self.code = code
        if not CODE_PATTERN.fullmatch(self.code):
            raise ValueError("Error codes must be UPPER_SNAKE_CASE English identifiers")


class BadRequest(AppError):
    status, code, title = 400, "BAD_REQUEST", "Bad request"


class Unauthenticated(AppError):
    status, code, title = 401, "UNAUTHENTICATED", "Authentication required"


class Forbidden(AppError):
    status, code, title = 403, "FORBIDDEN", "Action not allowed"


class NotFound(AppError):
    status, code, title = 404, "NOT_FOUND", "Resource not found"


class Conflict(AppError):
    status, code, title = 409, "CONFLICT", "State conflict"


class PreconditionFailed(AppError):
    status, code, title = 412, "PRECONDITION_FAILED", "Precondition failed"


class PayloadTooLarge(AppError):
    status, code, title = 413, "PAYLOAD_TOO_LARGE", "Payload too large"


class UnsupportedMediaType(AppError):
    status, code, title = 415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported media type"


class UnprocessableEntity(AppError):
    status, code, title = 422, "VALIDATION_ERROR", "Validation failed"


class PreconditionRequired(AppError):
    status, code, title = 428, "PRECONDITION_REQUIRED", "Precondition required"


class TooManyRequests(AppError):
    status, code, title = 429, "RATE_LIMIT_EXCEEDED", "Too many requests"


class InternalError(AppError):
    status, code, title = 500, "INTERNAL_ERROR", "Internal error"


class ServiceUnavailable(AppError):
    status, code, title = 503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable"
