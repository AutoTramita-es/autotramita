"""Request id middleware (pure ASGI, outermost so even unhandled 500s carry the id)."""

from __future__ import annotations

from app.core.request_context import new_request_id, set_request_id
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        set_request_id(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            set_request_id(None)


class NoStoreAuthMiddleware:
    """``Cache-Control: no-store`` on every answer of the sign-in routes, errors included, so
    no session state, redirect or error body is kept by a browser or intermediary cache."""

    PREFIXES = ("/api/v1/auth/", "/api/v1/me/security/")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(self.PREFIXES):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_no_store)
