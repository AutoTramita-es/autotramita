"""Health endpoints. They never expose infrastructure details and are not rate limited."""

from __future__ import annotations

import logging

import redis
from app.core.errors import ServiceUnavailable
from app.core.ratelimit import RateLimiter
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str = "ok"


@router.get("/health", summary="Liveness: the process is running")
def liveness() -> Health:
    return Health()


@router.get("/health/ready", summary="Readiness: configured dependencies answer")
def readiness(request: Request) -> Health:
    # Only configured components are checked. Failures are logged by component name and
    # reported to the caller as a plain 503, without hosts, users or error text.
    failed: list[str] = []
    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            failed.append("database")
    limiter: RateLimiter | None = request.app.state.rate_limiter
    if limiter is not None:
        try:
            limiter.ping()
        except redis.RedisError:
            failed.append("redis")
    if failed:
        log.error("readiness failed", extra={"fields": {"components": failed}})
        raise ServiceUnavailable("Not ready.", code="not_ready")
    return Health()
