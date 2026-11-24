"""Redis-backed rate limiting: approximate Sliding Window Counter (AT-01 O02, O18).

Algorithm. Time is split into fixed buckets of ``window_seconds``. For a request at elapsed
time ``e`` inside the current bucket the usage is estimated as

    estimate = previous_bucket_count * (1 - e / window) + current_bucket_count

and the request is allowed if ``estimate + 1 <= limit``. The estimate assumes requests were
spread evenly over the previous bucket, so it is APPROXIMATE (it can over- or under-count
around bucket boundaries) in exchange for two counters per limit and O(1) work.

Semantics approved by the owner for F1-T07:

* the time comes from the Redis server (``TIME``), never from application servers;
* all limits that apply to a request are checked and counted in ONE atomic Lua script;
* a request is counted only if EVERY applicable limit allows it (all or nothing), so a denied
  request consumes no quota of any limit;
* ``Retry-After`` is the longest wait, over the blocking limits, until the estimate drops far
  enough to allow one request again (at least 1 second, rounded up).

Availability trade-off (O02): there is no local fallback and no retry. If Redis cannot be
reached or does not answer within 500 ms, limited requests get ``503 RATE_LIMIT_UNAVAILABLE``
with ``Retry-After: 5``. A Redis outage therefore stops limited endpoints on purpose (security
over availability); ``/api/v1/health`` is exempt. Redis keys contain a hash of the identity,
never an IP address or user id, and logs never contain identities.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import redis
from app.core.config import RateLimitSettings
from app.core.errors import ServiceUnavailable, TooManyRequests
from fastapi import Request, Response
from redis.backoff import NoBackoff
from redis.retry import Retry

log = logging.getLogger(__name__)

REDIS_TIMEOUT_SECONDS = 0.5  # connect timeout and operation timeout, each
UNAVAILABLE_RETRY_AFTER_SECONDS = 5

# KEYS[i]: base key of limit i. ARGV: limit_i, window_seconds_i for every limit.
# Returns {all_allowed, (allowed, remaining, retry_after_ms, reset_ms) per limit}.
# Bucket keys are derived inside the script (single Redis instance, not Cluster).
_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local n = #KEYS
local all_ok = true
local out = {}
local cur_keys = {}
local windows = {}
for i = 1, n do
  local limit = tonumber(ARGV[2 * i - 1])
  local window = tonumber(ARGV[2 * i])
  local bucket = math.floor(now / window)
  local elapsed = now - bucket * window
  local cur_key = KEYS[i] .. ':' .. bucket
  local prev_key = KEYS[i] .. ':' .. (bucket - 1)
  local cur = tonumber(redis.call('GET', cur_key) or '0')
  local prev = tonumber(redis.call('GET', prev_key) or '0')
  local est = prev * (1 - elapsed / window) + cur
  local ok = (est + 1) <= limit + 1e-9
  local retry_ms = 0
  if not ok then
    all_ok = false
    local wait
    if prev > 0 and (limit - cur - 1) >= 0 then
      wait = window * (1 - (limit - cur - 1) / prev) - elapsed
      if wait < 0 then wait = 0 end
    else
      local u = 0
      if cur > 0 then
        u = window * (1 - (limit - 1) / cur)
        if u < 0 then u = 0 end
      end
      wait = (window - elapsed) + u
    end
    retry_ms = math.ceil(wait * 1000)
  end
  local after = est
  if ok then after = est + 1 end
  local remaining = math.floor(limit - after + 1e-9)
  if remaining < 0 then remaining = 0 end
  local reset_ms = retry_ms
  if ok then reset_ms = math.ceil((window - elapsed) * 1000) end
  out[#out + 1] = {ok and 1 or 0, remaining, retry_ms, reset_ms}
  cur_keys[i] = cur_key
  windows[i] = window
end
if all_ok then
  for i = 1, n do
    redis.call('INCR', cur_keys[i])
    redis.call('PEXPIRE', cur_keys[i], math.ceil(windows[i] * 2000))
  end
end
local flat = {all_ok and 1 or 0}
for i = 1, n do
  for j = 1, 4 do flat[#flat + 1] = out[i][j] end
end
return flat
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
    retry_after_seconds: int = 0
    blocking: tuple[str, ...] = field(default=())


def build_policies(settings: RateLimitSettings) -> dict[str, Policy]:
    return {
        "public": Policy("public", settings.public_per_min),
        "authenticated": Policy("authenticated", settings.authenticated_per_min),
        "tenant": Policy("tenant", settings.tenant_per_min),
        "upload": Policy("upload", settings.upload_per_min),
        "export": Policy("export", settings.export_per_min),
    }


def create_redis(url: str) -> redis.Redis:
    """Client for the limiter: 500 ms connect and operation timeouts, no automatic retry."""
    return redis.Redis.from_url(
        url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
        decode_responses=True,
    )


def _seconds(milliseconds: int) -> int:
    return max(math.ceil(milliseconds / 1000), 1)


class RateLimiter:
    def __init__(self, client: redis.Redis, *, namespace: str) -> None:
        self._client = client
        self._namespace = namespace  # the environment: dev, prod and test never share counters
        self._script = client.register_script(_SCRIPT)

    def ping(self) -> None:
        self._client.ping()

    def _key(self, policy: Policy, identity: str) -> str:
        digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
        return f"rl:{self._namespace}:{policy.name}:{digest}"

    def check(self, policy: Policy, identity: str) -> Decision:
        return self.check_all([(policy, identity)])

    def check_all(self, checks: Sequence[tuple[Policy, str]]) -> Decision:
        """Check and, if all allow, count every (policy, identity) pair atomically."""
        if not checks:
            raise ValueError("at least one limit is required")
        keys = [self._key(policy, identity) for policy, identity in checks]
        if len(set(keys)) != len(keys):
            raise ValueError("the same limit and identity must not be checked twice")
        args: list[int] = []
        for policy, _ in checks:
            args += [policy.limit, policy.window_seconds]
        try:
            raw = self._script(keys=keys, args=args)
        except redis.RedisError:
            # No retry and no local fallback (O02). Log policy names only, never identities.
            log.error(
                "rate limiter unavailable",
                extra={"fields": {"policies": [policy.name for policy, _ in checks]}},
            )
            raise ServiceUnavailable(
                "Request limiting is temporarily unavailable.",
                code="RATE_LIMIT_UNAVAILABLE",
                headers={"Retry-After": str(UNAVAILABLE_RETRY_AFTER_SECONDS)},
            ) from None
        rows = [raw[1 + 4 * i : 5 + 4 * i] for i in range(len(checks))]
        details = [
            (policy, bool(row[0]), int(row[1]), int(row[2]), int(row[3]))
            for (policy, _), row in zip(checks, rows, strict=True)
        ]
        blocking = [d for d in details if not d[1]]
        if blocking:
            return Decision(
                allowed=False,
                limit=min(blocking, key=lambda d: d[2])[0].limit,
                remaining=0,
                reset_seconds=_seconds(max(d[3] for d in blocking)),
                retry_after_seconds=_seconds(max(d[3] for d in blocking)),
                blocking=tuple(d[0].name for d in blocking),
            )
        tightest = min(details, key=lambda d: d[2])
        return Decision(
            allowed=True,
            limit=tightest[0].limit,
            remaining=tightest[2],
            reset_seconds=_seconds(tightest[4]),
        )


IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
MAX_FORWARDED_ENTRIES = 20


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def client_ip(request: Request, trusted_proxies: Sequence[IPNetwork] = ()) -> str:
    """Client address (R06). ``X-Forwarded-For`` is considered only when the direct peer is
    itself inside ``trusted_proxies`` (CIDR networks); a peer outside them cannot influence the
    result. The header is then read from the right, skipping entries that are trusted proxies;
    the first untrusted entry is the client. Anything unexpected (no trusted proxies, missing
    or unparsable peer, malformed or oversized header, only trusted entries) falls back to the
    direct peer address, the safe and conservative choice. Header lines are joined."""
    raw_peer = request.client.host if request.client else "unknown"
    peer = _parse_ip(raw_peer)
    if peer is None:
        return raw_peer
    if not trusted_proxies or not any(peer in net for net in trusted_proxies):
        return str(peer)
    joined = ",".join(request.headers.getlist("x-forwarded-for"))
    entries = [e for e in (part.strip() for part in joined.split(",")) if e]
    if not entries or len(entries) > MAX_FORWARDED_ENTRIES:
        return str(peer)
    for entry in reversed(entries):
        address = _parse_ip(entry)
        if address is None:
            return str(peer)
        if not any(address in net for net in trusted_proxies):
            return str(address)
    return str(peer)


def _headers(decision: Decision) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset_seconds),
    }


@dataclass(frozen=True, slots=True)
class Rule:
    """One limit applied to a route: a policy and how to identify the caller."""

    policy: Policy
    identity: Callable[[Request], str | None]


def rate_limits(
    rules: Sequence[Rule], trusted_proxies: Sequence[IPNetwork] = ()
) -> Callable[[Request, Response], None]:
    """Dependency factory: every rule must allow the request (checked together).

    If an identity cannot be resolved (for example before authentication exists), the client
    address is used under the same policy."""

    def dependency(request: Request, response: Response) -> None:
        limiter: RateLimiter | None = request.app.state.rate_limiter
        if limiter is None:  # misconfiguration must never mean "unlimited"
            raise ServiceUnavailable(
                "Request limiting is temporarily unavailable.",
                code="RATE_LIMIT_UNAVAILABLE",
                headers={"Retry-After": str(UNAVAILABLE_RETRY_AFTER_SECONDS)},
            )
        checks = [
            (rule.policy, rule.identity(request) or client_ip(request, trusted_proxies))
            for rule in rules
        ]
        decision = limiter.check_all(checks)
        if not decision.allowed:
            raise TooManyRequests(
                "Too many requests. Try again later.",
                headers={**_headers(decision), "Retry-After": str(decision.retry_after_seconds)},
            )
        for name, value in _headers(decision).items():
            response.headers[name] = value

    return dependency


def rate_limit(
    policy: Policy,
    identity: Callable[[Request], str | None],
    trusted_proxies: Sequence[IPNetwork] = (),
) -> Callable[[Request, Response], None]:
    """Dependency for a single limit (see ``rate_limits``)."""
    return rate_limits([Rule(policy, identity)], trusted_proxies)


def by_ip(trusted_proxies: Sequence[IPNetwork] = ()) -> Callable[[Request], str | None]:
    return lambda request: client_ip(request, trusted_proxies)


def by_principal(request: Request) -> str | None:
    """Actor identity, scoped by tenant when known so tenants never share actor counters."""
    value = getattr(request.state, "principal_id", None)
    if not value:
        return None
    tenant = getattr(request.state, "tenant_id", None)
    return f"tenant:{tenant}|user:{value}" if tenant else f"user:{value}"


def by_tenant(request: Request) -> str | None:
    value = getattr(request.state, "tenant_id", None)
    return f"tenant:{value}" if value else None
