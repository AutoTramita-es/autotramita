"""Exception handlers that render every error as application/problem+json."""

from __future__ import annotations

import logging

from app.core.errors import PROBLEM_CONTENT_TYPE, AppError, Problem
from app.core.request_context import get_request_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_STATUS = {
    400: ("BAD_REQUEST", "Bad request"),
    401: ("UNAUTHENTICATED", "Authentication required"),
    403: ("FORBIDDEN", "Action not allowed"),
    404: ("NOT_FOUND", "Resource not found"),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
    409: ("CONFLICT", "State conflict"),
    412: ("PRECONDITION_FAILED", "Precondition failed"),
    413: ("PAYLOAD_TOO_LARGE", "Payload too large"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Unsupported media type"),
    422: ("VALIDATION_ERROR", "Validation failed"),
    428: ("PRECONDITION_REQUIRED", "Precondition required"),
    429: ("RATE_LIMIT_EXCEEDED", "Too many requests"),
    500: ("INTERNAL_ERROR", "Internal error"),
    503: ("SERVICE_UNAVAILABLE", "Service temporarily unavailable"),
}

# Static texts only: Pydantic messages can quote the submitted value, which must never be
# echoed back (it may be personal data or a secret).
_VALIDATION_MESSAGES = {
    "missing": "Field required",
    "extra_forbidden": "Unknown field",
    "string_too_short": "Value is too short",
    "string_too_long": "Value is too long",
    "string_type": "Must be a string",
    "int_type": "Must be an integer",
    "int_parsing": "Must be an integer",
    "bool_type": "Must be a boolean",
    "greater_than_equal": "Value is too small",
    "less_than_equal": "Value is too large",
    "uuid_parsing": "Must be a valid UUID",
    "uuid_type": "Must be a valid UUID",
    "datetime_from_date_parsing": "Must be an ISO 8601 timestamp",
    "datetime_parsing": "Must be an ISO 8601 timestamp",
    "date_parsing": "Must be an ISO 8601 date",
    "json_invalid": "Body is not valid JSON",
    "string_pattern_mismatch": "Value has an invalid format",
    "literal_error": "Value is not allowed",
    "enum": "Value is not allowed",
    "value_error": "Value is not valid",
}


def _respond(problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _respond(
            Problem.build(
                title=exc.title,
                status=exc.status,
                detail=exc.detail,
                code=exc.code,
                request_id=get_request_id(),
            ),
            exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, title = _STATUS.get(exc.status_code, ("HTTP_ERROR", "HTTP error"))
        return _respond(
            Problem.build(
                title=title, status=exc.status_code, code=code, request_id=get_request_id()
            ),
            dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only locations and messages; never the submitted values.
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"]),
                "message": _VALIDATION_MESSAGES.get(str(e["type"]), "Value is not valid"),
            }
            for e in exc.errors()
        ]
        return _respond(
            Problem.build(
                title="Validation failed",
                status=422,
                code="VALIDATION_ERROR",
                request_id=get_request_id(),
                errors=errors,
            )
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", extra={"fields": {"type": type(exc).__name__}})
        return _respond(
            Problem.build(
                title="Internal error",
                status=500,
                code="INTERNAL_ERROR",
                request_id=get_request_id(),
            )
        )
