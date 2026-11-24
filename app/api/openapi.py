"""OpenAPI contract (ADR-004): documented error model and problem+json media type.

Generated TypeScript and Dart clients come from this document, so errors are part of the
contract: every non-success response is declared as ``application/problem+json``.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import PROBLEM_CONTENT_TYPE, Problem
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

API_VERSION = "0.0.0"  # single source for FastAPI's info.version; kept equal to pyproject.toml

REQUEST_ID_HEADER = "X-Request-ID"

# Headers documented for every response, or for the statuses that carry them.
_COMPONENT_HEADERS: dict[str, dict[str, Any]] = {
    "RequestId": {
        "description": "UUID of the request; problem responses repeat it as request_id.",
        "schema": {"type": "string", "format": "uuid"},
    },
    "RetryAfter": {
        "description": "Seconds to wait before retrying (whole seconds, at least 1).",
        "schema": {"type": "integer", "minimum": 1},
    },
    "RateLimitLimit": {
        "description": "Limit of the most restrictive applicable rate limit.",
        "schema": {"type": "integer", "minimum": 1},
    },
    "RateLimitRemaining": {
        "description": "Requests left in the most restrictive applicable rate limit.",
        "schema": {"type": "integer", "minimum": 0},
    },
    "RateLimitReset": {
        "description": "Seconds until the rate limit window allows requests again.",
        "schema": {"type": "integer", "minimum": 0},
    },
}
_STATUS_HEADERS: dict[str, dict[str, str]] = {
    "409": {"Retry-After": "RetryAfter"},  # only for an in-flight idempotent request
    "429": {
        "Retry-After": "RetryAfter",
        "RateLimit-Limit": "RateLimitLimit",
        "RateLimit-Remaining": "RateLimitRemaining",
        "RateLimit-Reset": "RateLimitReset",
    },
    "503": {"Retry-After": "RetryAfter"},
}
_FRAMEWORK_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


def _use_problem_for_validation_errors(schema: dict[str, Any]) -> None:
    """FastAPI documents 422 with its own schema, but real 422 bodies are ``Problem``."""
    text = json.dumps(schema)
    for name in _FRAMEWORK_VALIDATION_SCHEMAS:
        text = text.replace(f"#/components/schemas/{name}", "#/components/schemas/Problem")
    schema.clear()
    schema.update(json.loads(text))
    schemas = schema.get("components", {}).get("schemas", {})
    for name in _FRAMEWORK_VALIDATION_SCHEMAS:
        schemas.pop(name, None)


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
                    headers = response.setdefault("headers", {})
                    headers[REQUEST_ID_HEADER] = {"$ref": "#/components/headers/RequestId"}
                    for header, component in _STATUS_HEADERS.get(str(status), {}).items():
                        headers[header] = {"$ref": f"#/components/headers/{component}"}
        _use_problem_for_validation_errors(schema)
        schema.setdefault("components", {}).setdefault("headers", {}).update(_COMPONENT_HEADERS)
        app.openapi_schema = schema
        return schema

    app.openapi = build  # type: ignore[method-assign]
