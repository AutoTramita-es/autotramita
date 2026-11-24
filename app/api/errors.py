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
    400: ("bad_request", "Bad request"),
    401: ("unauthenticated", "Authentication required"),
    403: ("forbidden", "Action not allowed"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "Method not allowed"),
    409: ("conflict", "State conflict"),
    412: ("precondition_failed", "Precondition failed"),
    415: ("unsupported_media_type", "Unsupported media type"),
    422: ("validation_error", "Validation failed"),
    428: ("precondition_required", "Precondition required"),
    429: ("rate_limited", "Too many requests"),
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
            Problem(
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
        code, title = _STATUS.get(exc.status_code, ("http_error", "HTTP error"))
        return _respond(
            Problem(title=title, status=exc.status_code, code=code, request_id=get_request_id()),
            dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only locations and messages; never the submitted values.
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": str(e["msg"])}
            for e in exc.errors()
        ]
        return _respond(
            Problem(
                title="Validation failed",
                status=422,
                code="validation_error",
                request_id=get_request_id(),
                errors=errors,
            )
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", extra={"fields": {"type": type(exc).__name__}})
        return _respond(
            Problem(
                title="Internal error",
                status=500,
                code="internal_error",
                request_id=get_request_id(),
            )
        )
