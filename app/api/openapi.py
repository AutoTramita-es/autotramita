"""OpenAPI contract (ADR-004): documented error model and problem+json media type.

Generated TypeScript and Dart clients come from this document, so errors are part of the
contract: every non-success response is declared as ``application/problem+json``.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import PROBLEM_CONTENT_TYPE, Problem
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Reusable by business routers: include_router(router, responses=PROBLEM_RESPONSES).
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": Problem, "description": description}
    for code, description in {
        400: "Bad request",
        401: "Authentication required",
        403: "Action not allowed",
        404: "Resource not found or not visible",
        409: "State conflict",
        412: "Precondition failed (stale version)",
        413: "Payload too large",
        415: "Unsupported media type",
        422: "Validation failed",
        428: "Precondition required (If-Match)",
        429: "Too many requests",
        500: "Internal error",
        503: "Service temporarily unavailable",
    }.items()
}


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            summary="AutoTramita REST API",
        )
        for operations in schema.get("paths", {}).values():
            for operation in operations.values():
                for status, response in operation.get("responses", {}).items():
                    content = response.get("content")
                    if (
                        not str(status).startswith("2")
                        and content
                        and "application/json" in content
                    ):
                        content[PROBLEM_CONTENT_TYPE] = content.pop("application/json")
        app.openapi_schema = schema
        return schema

    app.openapi = build  # type: ignore[method-assign]
