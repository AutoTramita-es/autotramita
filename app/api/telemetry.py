"""Pure ASGI middleware that wraps each HTTP request in a server span (see app.core.telemetry)."""

from __future__ import annotations

from app.core.request_context import get_request_id
from app.core.telemetry import get_tracer
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_ROUTE = "unmatched"


def route_template(scope: Scope) -> str:
    """Route template for the span: never contains values from the request path.

    FastAPI reports routes of included routers relative to their prefix, so the full template
    is rebuilt from the request path by replacing every path parameter value with its name; if
    a value cannot be located as a whole segment, the relative template is used instead."""
    route = scope.get("route")
    if route is None:
        return UNMATCHED_ROUTE
    full = str(scope.get("path", ""))
    params = {str(value): name for name, value in (scope.get("path_params") or {}).items()}
    if not params:
        return full  # a literal route: the path is its template
    segments = full.split("/")
    rebuilt = ["{" + params[seg] + "}" if seg in params else seg for seg in segments]
    if {seg for seg in segments if seg in params} != set(params):
        template = getattr(route, "path_format", None) or getattr(route, "path", None)
        return str(template) if template else UNMATCHED_ROUTE
    return "/".join(rebuilt)


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
