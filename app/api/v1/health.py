"""Health endpoint: liveness only, minimal and non-sensitive.

It answers from the process alone, so it works when PostgreSQL, Redis or the rate limiter are
down, is exempt from rate limiting (it never uses the limiter dependency) and discloses no
dependencies, versions or host names. Readiness is deliberately not exposed (open decision
O20); see ``app.core.health``.
"""

from __future__ import annotations

from app.core.errors import Problem
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str = "ok"


@router.get(
    "/health",
    summary="Liveness: the process is running",
    responses={500: {"model": Problem, "description": "Internal error"}},
)
def liveness() -> Health:
    return Health()
