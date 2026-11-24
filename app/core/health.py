"""Internal dependency check (no HTTP route).

The public health endpoint is liveness only. Whether and how readiness is exposed is the open
decision O20 and is settled before going live; until then this helper is internal. It reports
which components failed by NAME ONLY: no hosts, users, versions or error text, in the result
or in logs.
"""

from __future__ import annotations

import logging

import redis
from app.core.ratelimit import RateLimiter
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)


def check_dependencies(engine: Engine | None, limiter: RateLimiter | None) -> list[str]:
    """Return the names of configured components that do not answer (empty means all fine)."""
    failed: list[str] = []
    if engine is not None:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            failed.append("database")
    if limiter is not None:
        try:
            limiter.ping()
        except redis.RedisError:
            failed.append("redis")
    if failed:
        log.error("dependency check failed", extra={"fields": {"components": failed}})
    return failed
