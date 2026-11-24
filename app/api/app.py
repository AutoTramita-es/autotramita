"""Application factory."""

from __future__ import annotations

from app.api.errors import install_error_handlers
from app.api.middleware import RequestIdMiddleware
from app.api.openapi import install_openapi
from app.api.telemetry import TelemetryMiddleware
from app.api.v1.router import build_v1_router
from app.core.config import RateLimitSettings, Settings
from app.core.db import create_db_engine
from app.core.ratelimit import RateLimiter, create_redis
from fastapi import FastAPI
from sqlalchemy import Engine
from starlette.types import ASGIApp


class AutoTramitaApp(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # Outermost layer: the request id must also reach responses produced by the
        # server error handler for unhandled exceptions. The telemetry span sits just inside
        # it, so it sees the final status of those responses and can carry the request id.
        return RequestIdMiddleware(TelemetryMiddleware(super().build_middleware_stack()))


def create_app(
    rate_limiter: RateLimiter | None = None,
    db_engine: Engine | None = None,
    rate_limit_settings: RateLimitSettings | None = None,
) -> FastAPI:
    """Build the app. Dependencies are injected so tests and workers control them."""
    app = AutoTramitaApp(
        title="AutoTramita API",
        version="0.0.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.rate_limiter = rate_limiter
    app.state.db_engine = db_engine
    install_error_handlers(app)
    app.include_router(build_v1_router(rate_limit_settings or RateLimitSettings()))
    install_openapi(app)
    return app


def create_app_from_settings(settings: Settings) -> FastAPI:
    limits = RateLimitSettings()
    limiter = RateLimiter(create_redis(settings.redis_url), namespace=settings.environment)
    return create_app(limiter, create_db_engine(settings), limits)
