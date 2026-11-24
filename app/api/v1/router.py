"""Version 1 router. Health is unlimited; everything else gets the public IP limit by default."""

from __future__ import annotations

from app.api.openapi import PROBLEM_RESPONSES
from app.api.v1 import health
from app.api.v1.auth import build_auth_router
from app.api.v1.me import build_me_router
from app.api.v1.sessions import build_sessions_router
from app.auth.settings import AuthLimitSettings
from app.core.config import RateLimitSettings
from app.core.ratelimit import build_policies, by_ip, rate_limit
from fastapi import APIRouter, Depends


def build_v1_router(
    settings: RateLimitSettings, auth_limits: AuthLimitSettings | None = None
) -> APIRouter:
    default_limit = rate_limit(
        build_policies(settings)["public"],
        by_ip(settings.trusted_proxy_networks),
        settings.trusted_proxy_networks,
    )
    router = APIRouter(prefix="/api/v1")
    router.include_router(health.router)  # exempt from rate limiting
    # Routers below inherit the default limit; authenticated, tenant, upload and export
    # policies are added per endpoint by their modules.
    limited = APIRouter(dependencies=[Depends(default_limit)])
    limited.include_router(
        build_auth_router(auth_limits or AuthLimitSettings(), settings.trusted_proxy_networks),
        responses=PROBLEM_RESPONSES,
    )
    limited.include_router(
        build_sessions_router(auth_limits or AuthLimitSettings(), settings.trusted_proxy_networks),
        responses=PROBLEM_RESPONSES,
    )
    limited.include_router(
        build_me_router(settings.trusted_proxy_networks), responses=PROBLEM_RESPONSES
    )
    router.include_router(limited)
    return router
