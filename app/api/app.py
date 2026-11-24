"""Application factory."""

from __future__ import annotations

from app.api.errors import install_error_handlers
from app.api.middleware import RequestIdMiddleware
from fastapi import FastAPI
from starlette.types import ASGIApp


class AutoTramitaApp(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # Outermost layer: the request id must also reach responses produced by the
        # server error handler for unhandled exceptions.
        return RequestIdMiddleware(super().build_middleware_stack())


def create_app() -> FastAPI:
    app = AutoTramitaApp(
        title="AutoTramita API",
        version="0.0.0",
        docs_url=None,
        redoc_url=None,
    )
    install_error_handlers(app)
    return app
