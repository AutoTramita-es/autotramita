"""Version 1 router. Health is unlimited; everything else gets the public IP limit by default."""

from __future__ import annotations

from app.api.v1 import health
from app.core.config import RateLimitSettings
from app.core.ratelimit import build_policies, by_ip, rate_limit
from fastapi import APIRouter, Depends


def build_v1_router(settings: RateLimitSettings) -> APIRouter:
    default_limit = rate_limit(
        build_policies(settings)["public"],
        by_ip(settings.trusted_proxy_networks),
        settings.trusted_proxy_networks,
    )
    router = APIRouter(prefix="/api/v1")
    router.include_router(health.router)  # exempt from rate limiting
    # Business routers are included here by later phases and inherit the default limit;
    # authenticated, tenant, upload and export policies are added per endpoint.
    router.include_router(APIRouter(dependencies=[Depends(default_limit)]))
    return router
