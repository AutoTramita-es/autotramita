"""Application errors rendered as RFC 9457 problem details (ADR-004).

Every error has a stable machine-readable ``code``. Messages never include secrets, SQL,
stack traces or the existence of resources in other tenants (404 is used for invisible ones).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str = Field(description="Stable machine-readable error code")
    request_id: str | None = None
    errors: list[dict[str, str]] | None = Field(
        default=None, description="Field-level validation problems (no input values)"
    )


class AppError(Exception):
    """Base class for expected, client-visible errors."""

    status = 500
    code = "internal_error"
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
        if code:
            self.code = code


class BadRequest(AppError):
    status, code, title = 400, "bad_request", "Bad request"


class Unauthenticated(AppError):
    status, code, title = 401, "unauthenticated", "Authentication required"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Action not allowed"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Resource not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "State conflict"


class PreconditionFailed(AppError):
    status, code, title = 412, "precondition_failed", "Precondition failed"


class UnprocessableEntity(AppError):
    status, code, title = 422, "validation_error", "Validation failed"


class PreconditionRequired(AppError):
    status, code, title = 428, "precondition_required", "Precondition required"


class TooManyRequests(AppError):
    status, code, title = 429, "rate_limited", "Too many requests"


class ServiceUnavailable(AppError):
    status, code, title = 503, "service_unavailable", "Service temporarily unavailable"
