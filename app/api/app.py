"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.api.errors import install_error_handlers
from app.api.middleware import NoStoreAuthMiddleware, RequestIdMiddleware
from app.api.openapi import API_VERSION, install_openapi
from app.api.telemetry import TelemetryMiddleware
from app.api.v1.router import build_v1_router
from app.auth.runtime import AuthRuntime
from app.auth.security.notify import SmtpNotifier
from app.auth.security.recovery_worker import EmailChangeRecoveryWorker
from app.auth.settings import AuthLimitSettings, AuthSettings
from app.core.config import RateLimitSettings, Settings
from app.core.db import create_db_engine, create_session_factory
from app.core.ratelimit import RateLimiter, create_redis
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import Engine
from starlette.types import ASGIApp


class AutoTramitaApp(FastAPI):
    def build_middleware_stack(self) -> ASGIApp:
        # Outermost layer: the request id must also reach responses produced by the
        # server error handler for unhandled exceptions. The telemetry span sits just inside
        # it, so it sees the final status of those responses and can carry the request id.
        return RequestIdMiddleware(
            TelemetryMiddleware(NoStoreAuthMiddleware(super().build_middleware_stack()))
        )


def create_app(
    rate_limiter: RateLimiter | None = None,
    db_engine: Engine | None = None,
    rate_limit_settings: RateLimitSettings | None = None,
    auth: AuthRuntime | None = None,
    auth_limits: AuthLimitSettings | None = None,
) -> FastAPI:
    """Build the app. Dependencies are injected so tests and workers control them."""
    app = AutoTramitaApp(
        title="AutoTramita API",
        version=API_VERSION,
        docs_url=None,
        redoc_url=None,
    )
    app.state.rate_limiter = rate_limiter
    app.state.db_engine = db_engine
    app.state.auth = auth  # None: the sign-in routes answer 503 AUTH_NOT_CONFIGURED
    install_error_handlers(app)
    app.include_router(build_v1_router(rate_limit_settings or RateLimitSettings(), auth_limits))
    install_openapi(app)
    return app


def create_app_from_settings(settings: Settings) -> FastAPI:
    limits = RateLimitSettings()
    redis_client = create_redis(settings.redis_url)
    limiter = RateLimiter(redis_client, namespace=settings.environment)
    engine = create_db_engine(settings)
    auth: AuthRuntime | None = None
    try:
        auth = AuthRuntime.build(
            AuthSettings(),  # type: ignore[call-arg]
            redis_client,
            engine,
            namespace=settings.environment,
            trusted_proxies=limits.trusted_proxy_networks,
        )
    except ValidationError:
        logging.getLogger(__name__).warning("authentication is not configured; sign-in disabled")
    app = create_app(limiter, engine, limits, auth)
    if auth is None or auth.admin is None or settings.worker_user is None:
        return app

    # Dedicated least-privilege DB credentials; no fallback to the web or owner role.
    worker_engine = create_db_engine(settings, role="worker")
    notifier = auth.notifier if isinstance(auth.notifier, SmtpNotifier) else None
    # O15: real production email and the D37 initiation route remain disabled.
    if settings.environment == "prod":
        notifier = None
    runtime = auth

    def cycle_finished(ok: bool) -> None:
        runtime.email_change_ready = ok and bool(
            notifier and runtime.settings.web_origin and runtime.settings.security_hmac_key
        )

    worker = EmailChangeRecoveryWorker(
        create_session_factory(worker_engine), auth.admin, notifier, on_cycle=cycle_finished
    )
    app.state.email_change_worker = worker

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker.start()
        try:
            yield
        finally:
            if worker.stop():
                worker_engine.dispose()

    app.router.lifespan_context = lifespan
    return app
