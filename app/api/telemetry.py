"""Pure ASGI middleware that wraps each HTTP request in a server span (see app.core.telemetry)."""

from __future__ import annotations

from app.core.request_context import get_request_id
from app.core.telemetry import get_tracer
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_ROUTE = "unmatched"


def route_template(scope: Scope) -> str:
    """Route template for the span (R08): only the matched route's registered template, or the
    constant ``unmatched``. Nothing is ever derived from the request path, so no request
    value can appear in it. Where the framework registers a route relative to its router
    prefix, that relative registered template is reported (it is value-free by construction)."""
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(template, str) or not template:
        return UNMATCHED_ROUTE
    return template


class TelemetryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET")).upper()
        with get_tracer().start_as_current_span(
            method,
            kind=SpanKind.SERVER,
            record_exception=False,  # exception messages may contain data
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("http.request.method", method)
            request_id = get_request_id()
            if request_id:
                span.set_attribute("autotramita.request_id", request_id)

            async def send_and_record(message: Message) -> None:
                if message["type"] == "http.response.start":
                    status = int(message["status"])
                    span.set_attribute("http.response.status_code", status)
                    if status >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                await send(message)

            try:
                await self.app(scope, receive, send_and_record)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                route = route_template(scope)
                span.set_attribute("http.route", route)
                span.update_name(f"{method} {route}")
