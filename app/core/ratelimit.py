"""Redis-backed rate limiting (fixed window, atomic).

The counter is incremented and expired in a single Lua script, so concurrent requests cannot
exceed the limit. Keys use a hash of the identity (IP addresses are personal data and never
appear in Redis keys or logs) and include the environment, policy and identity, so tenants
and policies are isolated from each other.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from collections.abc import Callable
from dataclasses import dataclass

import redis
from app.core.config import RateLimitSettings
from app.core.errors import ServiceUnavailable, TooManyRequests
from fastapi import Request, Response

log = logging.getLogger(__name__)

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


@dataclass(frozen=True, slots=True)
class Policy:
    name: str
    limit: int
    window_seconds: int = 60


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


def build_policies(settings: RateLimitSettings) -> dict[str, Policy]:
    return {
        "public": Policy("public", settings.public_per_min),
        "authenticated": Policy("authenticated", settings.authenticated_per_min),
        "tenant": Policy("tenant", settings.tenant_per_min),
        "upload": Policy("upload", settings.upload_per_min),
        "export": Policy("export", settings.export_per_min),
    }


def create_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url, socket_timeout=0.25, socket_connect_timeout=0.25, decode_responses=True
    )


class RateLimiter:
    def __init__(self, client: redis.Redis, *, namespace: str, fail_open: bool = True) -> None:
        self._client = client
        self._namespace = namespace
        self._fail_open = fail_open
        self._script = client.register_script(_SCRIPT)

    def ping(self) -> None:
        self._client.ping()

    def _key(self, policy: Policy, identity: str) -> str:
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        return f"rl:{self._namespace}:{policy.name}:{digest}"

    def check(self, policy: Policy, identity: str) -> Decision:
        try:
            count, ttl = self._script(
                keys=[self._key(policy, identity)], args=[policy.window_seconds]
            )
        except redis.RedisError:
            log.error("rate limiter unavailable", extra={"fields": {"policy": policy.name}})
            if self._fail_open:
                return Decision(True, policy.limit, policy.limit, policy.window_seconds)
            raise ServiceUnavailable(
                "Request limiting is temporarily unavailable.", code="RATE_LIMIT_UNAVAILABLE"
            ) from None
        remaining = max(policy.limit - int(count), 0)
        return Decision(int(count) <= policy.limit, policy.limit, remaining, int(ttl))


def client_ip(request: Request, trusted_hops: int = 0) -> str:
    """Client address; X-Forwarded-For is honored only for the configured trusted proxies."""
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p]
    if len(forwarded) < trusted_hops:
        return peer
    candidate = forwarded[-trusted_hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


def _headers(decision: Decision) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset_seconds),
    }


def rate_limit(
    policy: Policy, identity: Callable[[Request], str | None], trusted_hops: int = 0
) -> Callable[[Request, Response], None]:
    """Dependency factory. If the identity cannot be resolved (for example before
    authentication exists), the client address is used under the same policy."""

    def dependency(request: Request, response: Response) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        who = identity(request) or client_ip(request, trusted_hops)
        decision = limiter.check(policy, who)
        if not decision.allowed:
            raise TooManyRequests(
                "Too many requests. Try again later.",
                headers={**_headers(decision), "Retry-After": str(max(decision.reset_seconds, 1))},
            )
        for name, value in _headers(decision).items():
            response.headers[name] = value

    return dependency


def by_ip(trusted_hops: int = 0) -> Callable[[Request], str | None]:
    return lambda request: client_ip(request, trusted_hops)


def by_principal(request: Request) -> str | None:
    value = getattr(request.state, "principal_id", None)
    return f"user:{value}" if value else None


def by_tenant(request: Request) -> str | None:
    value = getattr(request.state, "tenant_id", None)
    return f"tenant:{value}" if value else None
