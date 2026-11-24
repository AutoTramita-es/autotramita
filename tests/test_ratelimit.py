"""F1-T07 rate limiter: approximate Sliding Window Counter on a real Redis 7 (TEST_REDIS_URL).

Tests that need no Redis (configuration, header handling, failure behaviour against fake
servers) run everywhere; the rest is skipped locally and mandatory in CI.
"""

import logging
import math
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from ipaddress import ip_network
from typing import Annotated

import pytest
import redis
from app.api.app import create_app
from app.core.config import RateLimitSettings
from app.core.errors import ServiceUnavailable
from app.core.ratelimit import (
    REDIS_TIMEOUT_SECONDS,
    IPNetwork,
    Policy,
    RateLimiter,
    Rule,
    build_policies,
    by_ip,
    by_principal,
    by_tenant,
    client_ip,
    create_redis,
    rate_limits,
)
from fastapi import Depends
from fastapi.testclient import TestClient
from starlette.requests import Request

# --- helpers -------------------------------------------------------------------------------


def server_time(client: redis.Redis) -> float:
    seconds, micros = client.time()
    return float(seconds) + float(micros) / 1_000_000


def ensure_room(client: redis.Redis, window: int, needed: float) -> None:
    """Start the test early enough in a bucket that it cannot cross a bucket boundary."""
    left = window - (server_time(client) % window)
    if left < needed:
        time.sleep(left + 0.05)


def align(client: redis.Redis, window: int, max_elapsed: float = 0.25) -> float:
    """Wait for the start of a bucket; returns the elapsed time inside it."""
    while True:
        elapsed = server_time(client) % window
        if elapsed < max_elapsed:
            return elapsed
        time.sleep(window - elapsed + 0.01)


def make_request(peer: str | None, forwarded: list[str] | None = None, **state: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", v.encode()) for v in forwarded or []],
        "client": (peer, 5000) if peer else None,
    }
    request = Request(scope)
    for key, value in state.items():
        setattr(request.state, key, value)
    return request


@pytest.fixture
def client_redis(redis_url: str) -> Iterator[redis.Redis]:
    client = create_redis(redis_url)
    yield client
    client.close()


@pytest.fixture
def namespace() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def limiter(client_redis: redis.Redis, namespace: str) -> Iterator[RateLimiter]:
    yield RateLimiter(client_redis, namespace=namespace)
    for key in client_redis.scan_iter(f"rl:{namespace}:*"):
        client_redis.delete(key)


class FakeRedis:
    """TCP server that misbehaves on purpose and counts connections (no Redis involved)."""

    def __init__(self, mode: str) -> None:
        self.mode = mode  # "silent": accept and never answer; "close": accept and hang up
        self.connections = 0
        self._held: list[socket.socket] = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self.connections += 1
            if self.mode == "close":
                conn.close()
            else:
                self._held.append(conn)

    def close(self) -> None:
        self._server.close()
        for conn in self._held:
            conn.close()


@pytest.fixture(params=["silent", "close"])
def fake_redis(request: pytest.FixtureRequest) -> Iterator[FakeRedis]:
    server = FakeRedis(request.param)
    yield server
    server.close()


# --- configuration (no Redis needed) -------------------------------------------------------


def test_approved_default_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in RateLimitSettings.model_fields.values():
        assert isinstance(field.validation_alias, str)
        monkeypatch.delenv(field.validation_alias, raising=False)
    s = RateLimitSettings()
    assert (s.public_per_min, s.authenticated_per_min, s.tenant_per_min) == (60, 300, 3000)
    assert (s.upload_per_min, s.export_per_min) == (30, 5)
    assert (s.keycloak_max_failed_logins, s.keycloak_failure_window_minutes) == (5, 15)
    assert s.password_recovery_per_hour == 3
    assert s.trusted_proxy_cidrs == "" and s.trusted_proxy_networks == ()
    assert {n: (p.limit, p.window_seconds) for n, p in build_policies(s).items()} == {
        "public": (60, 60),
        "authenticated": (300, 60),
        "tenant": (3000, 60),
        "upload": (30, 60),
        "export": (5, 60),
    }


def test_limits_are_configurable_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_EXPORT_PER_MIN", "2")
    assert RateLimitSettings().export_per_min == 2
    assert build_policies(RateLimitSettings())["export"].limit == 2
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_PER_MIN", "0")
    with pytest.raises(ValueError):
        RateLimitSettings()


def test_fail_open_no_longer_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """O02: no local fallback. The old switch is gone and the variable has no effect."""
    monkeypatch.setenv("RATE_LIMIT_FAIL_OPEN", "true")
    assert not hasattr(RateLimitSettings(), "fail_open")


def test_redis_client_has_500ms_timeouts_and_no_retry() -> None:
    client = create_redis("redis://localhost:6379/0")
    kwargs = client.connection_pool.connection_kwargs
    assert REDIS_TIMEOUT_SECONDS == 0.5
    assert kwargs["socket_connect_timeout"] == 0.5
    assert kwargs["socket_timeout"] == 0.5
    assert kwargs["retry_on_timeout"] is False
    assert client.get_retry().get_retries() == 0  # type: ignore[union-attr]


# --- trusted proxy handling (no Redis needed) ----------------------------------------------

PROXY = [ip_network("10.0.0.0/24")]
PROXY_V6 = [ip_network("fd00::/64")]


def test_forwarded_header_is_ignored_without_trusted_proxies() -> None:
    assert client_ip(make_request("10.0.0.9", ["1.2.3.4, 5.6.7.8"])) == "10.0.0.9"
    assert client_ip(make_request("10.0.0.9", ["1.2.3.4"]), []) == "10.0.0.9"
    assert client_ip(make_request(None)) == "unknown"


def test_direct_client_outside_trusted_networks_cannot_spoof_the_header() -> None:
    spoof = make_request("198.51.100.5", ["1.1.1.1"])
    assert client_ip(spoof, PROXY) == "198.51.100.5"
    assert client_ip(make_request("198.51.100.5", ["10.0.0.9, 1.1.1.1"]), PROXY) == "198.51.100.5"
    assert client_ip(make_request("10.0.1.1", ["1.1.1.1"]), PROXY) == "10.0.1.1"  # just outside


def test_trusted_peer_uses_the_rightmost_untrusted_entry() -> None:
    assert client_ip(make_request("10.0.0.9", ["5.6.7.8"]), PROXY) == "5.6.7.8"
    # Entries a client prepends cannot change the result.
    assert client_ip(make_request("10.0.0.9", ["6.6.6.6, 7.7.7.7, 5.6.7.8"]), PROXY) == "5.6.7.8"
    # Multi-hop: trusted proxies in the chain are skipped from the right.
    multi = make_request("10.0.0.9", ["6.6.6.6, 5.6.7.8, 10.0.0.20, 10.0.0.30"])
    assert client_ip(multi, PROXY) == "5.6.7.8"
    # A client-supplied entry that looks like a trusted proxy does not help to hide.
    assert client_ip(make_request("10.0.0.9", ["10.0.0.1, 5.6.7.8"]), PROXY) == "5.6.7.8"


def test_unexpected_forwarded_values_fall_back_to_the_peer() -> None:
    for header in (
        ["not-an-ip"],
        ["999.1.1.1"],
        [" , "],
        ["5.6.7.8, garbage"],
        ["10.0.0.1, 10.0.0.2"],
    ):
        assert client_ip(make_request("10.0.0.9", header), PROXY) == "10.0.0.9", header
    assert client_ip(make_request("10.0.0.9"), PROXY) == "10.0.0.9"  # no header
    assert client_ip(make_request("10.0.0.9", ["1.2.3.4, "]), PROXY) == "1.2.3.4"
    long_chain = ", ".join(f"1.2.3.{n}" for n in range(1, 30))
    assert client_ip(make_request("10.0.0.9", [long_chain]), PROXY) == "10.0.0.9"


def test_missing_or_unparsable_peer_is_never_trusted() -> None:
    assert client_ip(make_request(None, ["1.2.3.4"]), PROXY) == "unknown"
    assert client_ip(make_request("testclient", ["1.2.3.4"]), PROXY) == "testclient"


def test_multiple_headers_ipv6_and_mapped_addresses() -> None:
    two_lines = make_request("10.0.0.9", ["1.2.3.4", "5.6.7.8"])
    assert client_ip(two_lines, PROXY) == "5.6.7.8"
    assert client_ip(make_request("10.0.0.9", ["2001:DB8::0001"]), PROXY) == "2001:db8::1"
    assert client_ip(make_request("fd00::7", ["203.0.113.9"]), PROXY_V6) == "203.0.113.9"
    assert client_ip(make_request("fd00::7", ["2001:db8::5"]), PROXY_V6) == "2001:db8::5"
    assert client_ip(make_request("fd01::7", ["2001:db8::5"]), PROXY_V6) == "fd01::7"
    mapped = make_request("::ffff:10.0.0.9", ["5.6.7.8"])  # IPv4 peer reported as IPv6-mapped
    assert client_ip(mapped, PROXY) == "5.6.7.8"
    assert client_ip(make_request("::ffff:198.51.100.5", ["1.1.1.1"]), PROXY) == "198.51.100.5"


@pytest.mark.parametrize("value", ["10.0.0.0/8, 192.168.0.0/16", " 10.0.0.1/32 ,fd00::/64", ""])
def test_trusted_proxy_cidrs_accepts_networks(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", value)
    parsed = RateLimitSettings().trusted_proxy_networks
    assert len(parsed) == len([v for v in value.split(",") if v.strip()])


@pytest.mark.parametrize(
    "value", ["0.0.0.0/0", "::/0", "10.0.0.5/24", "not-a-network", "10.0.0.1/33", "10.0.0.0/8,x"]
)
def test_trusted_proxy_cidrs_rejects_unsafe_or_malformed_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", value)
    with pytest.raises(ValueError):
        RateLimitSettings()


def test_legacy_hop_setting_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert RateLimitSettings().trusted_proxy_networks == ()


def test_principal_is_global_per_user_and_tenant_identity_is_separate() -> None:
    anonymous = make_request("1.1.1.1")
    assert by_principal(anonymous) is None
    assert by_tenant(anonymous) is None
    request = make_request("1.1.1.1", principal_id="u1", tenant_id="t1")
    assert by_principal(request) == "user:u1"  # R07: no tenant in the user identity
    assert by_tenant(request) == "tenant:t1"
    assert by_principal(make_request("1.1.1.1", principal_id="u1")) == "user:u1"
    assert by_principal(make_request("1.1.1.1", principal_id="u1", tenant_id="t2")) == "user:u1"
    assert by_principal(make_request("1.1.1.1", tenant_id="t1")) is None


# --- failures: 503, no retry, no fallback (no Redis needed) --------------------------------


def dead_limiter() -> RateLimiter:
    return RateLimiter(create_redis("redis://127.0.0.1:1/0"), namespace="dead")


def test_unreachable_redis_is_503_with_retry_after_5(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ServiceUnavailable) as err:
        dead_limiter().check(Policy("p", 1), "203.0.113.9")
    assert (err.value.status, err.value.code) == (503, "RATE_LIMIT_UNAVAILABLE")
    assert err.value.headers["Retry-After"] == "5"
    assert "203.0.113.9" not in caplog.text  # identities are never logged
    assert any("rate limiter unavailable" in r.getMessage() for r in caplog.records)


def test_operation_timeout_and_connection_loss_are_503_without_retry(
    fake_redis: FakeRedis,
) -> None:
    limiter = RateLimiter(create_redis(f"redis://127.0.0.1:{fake_redis.port}/0"), namespace="fake")
    started = time.monotonic()
    with pytest.raises(ServiceUnavailable) as err:
        limiter.check(Policy("p", 1), "who")
    elapsed = time.monotonic() - started
    assert err.value.code == "RATE_LIMIT_UNAVAILABLE"
    assert fake_redis.connections == 1  # exactly one attempt: no automatic retry
    if fake_redis.mode == "silent":
        assert 0.4 <= elapsed < 1.5  # the 500 ms operation timeout, not longer


def test_no_local_fallback_after_a_failure() -> None:
    limiter = dead_limiter()
    for _ in range(3):  # never "allowed" just because Redis is down
        with pytest.raises(ServiceUnavailable):
            limiter.check(Policy("p", 1), "who")


def test_duplicate_or_empty_checks_are_rejected() -> None:
    limiter = dead_limiter()
    with pytest.raises(ValueError):
        limiter.check_all([])
    with pytest.raises(ValueError):
        limiter.check_all([(Policy("p", 1), "x"), (Policy("p", 1), "x")])


# --- algorithm on real Redis ---------------------------------------------------------------


def test_each_default_limit_allows_exactly_its_quota(
    limiter: RateLimiter, client_redis: redis.Redis
) -> None:
    ensure_room(client_redis, 60, 15)
    for policy in build_policies(RateLimitSettings()).values():
        results = [limiter.check(policy, f"id-{policy.name}") for _ in range(policy.limit + 2)]
        assert [r.allowed for r in results] == [True] * policy.limit + [False, False], policy.name


def test_remaining_and_reset(limiter: RateLimiter, client_redis: redis.Redis) -> None:
    ensure_room(client_redis, 60, 5)
    policy = Policy("t", 3)
    results = [limiter.check(policy, "who") for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0, 0]
    assert 0 < results[0].reset_seconds <= 60


def test_denied_requests_do_not_consume_quota(
    limiter: RateLimiter, client_redis: redis.Redis, namespace: str
) -> None:
    ensure_room(client_redis, 60, 5)
    policy = Policy("d", 2)
    for _ in range(6):
        limiter.check(policy, "who")
    counts = [int(client_redis.get(k) or 0) for k in client_redis.scan_iter(f"rl:{namespace}:*")]
    assert sum(counts) == 2  # 2 allowed counted, 4 denied not counted


def test_all_limits_must_allow_and_denied_requests_count_nowhere(
    limiter: RateLimiter, client_redis: redis.Redis
) -> None:
    ensure_room(client_redis, 60, 5)
    tight, roomy = Policy("tight", 2), Policy("roomy", 5)
    both = [(tight, "u"), (roomy, "u")]
    assert limiter.check_all(both).allowed
    assert limiter.check_all(both).allowed
    third = limiter.check_all(both)
    assert not third.allowed
    assert third.blocking == ("tight",)
    assert third.retry_after_seconds >= 1
    # The denied request used no quota of the roomy limit: 3 of its 5 are still free.
    assert [limiter.check(roomy, "u").allowed for _ in range(4)] == [True, True, True, False]


def test_retry_after_is_the_longest_wait_over_blocking_limits(
    limiter: RateLimiter, client_redis: redis.Redis
) -> None:
    ensure_room(client_redis, 60, 5)
    short, long = Policy("short", 1, window_seconds=2), Policy("long", 1, window_seconds=60)
    assert limiter.check_all([(short, "u"), (long, "u")]).allowed
    denied = limiter.check_all([(short, "u"), (long, "u")])
    assert not denied.allowed
    assert set(denied.blocking) == {"short", "long"}
    assert denied.retry_after_seconds > 10  # the 60 s window dominates the 2 s one


def test_window_slides_instead_of_resetting(
    limiter: RateLimiter, client_redis: redis.Redis
) -> None:
    window, limit = 2, 4
    policy = Policy("slide", limit, window_seconds=window)
    align(client_redis, window)
    assert [limiter.check(policy, "u").allowed for _ in range(limit)] == [True] * limit
    assert not limiter.check(policy, "u").allowed
    # Just after the boundary the previous bucket still counts almost fully: still blocked.
    time.sleep(window - (server_time(client_redis) % window) + 0.02)
    assert not limiter.check(policy, "u").allowed
    # Part-way through the next bucket the estimate has decayed and some requests pass.
    time.sleep(1.0)
    before = server_time(client_redis) % window
    allowed = sum(limiter.check(policy, "u").allowed for _ in range(limit))
    after = server_time(client_redis) % window
    assert math.floor(limit * (before / window) - 0.05) <= allowed
    assert allowed <= math.floor(limit * (after / window)) + 1
    assert 0 < allowed < limit


def test_retry_after_matches_the_estimate_decay(
    limiter: RateLimiter, client_redis: redis.Redis
) -> None:
    window, limit = 2, 4
    policy = Policy("retry", limit, window_seconds=window)
    elapsed = align(client_redis, window)
    for _ in range(limit):
        limiter.check(policy, "u")
    denied = limiter.check(policy, "u")
    expected = (window - elapsed) + window * (1 - (limit - 1) / limit)  # about 2.2 to 2.5 s
    assert not denied.allowed
    assert expected - 0.4 <= denied.retry_after_seconds <= expected + 1.0
    time.sleep(denied.retry_after_seconds)
    assert limiter.check(policy, "u").allowed  # waiting as told is enough


def test_counters_expire(limiter: RateLimiter, client_redis: redis.Redis, namespace: str) -> None:
    policy = Policy("ttl", 5, window_seconds=1)
    limiter.check(policy, "u")
    keys = list(client_redis.scan_iter(f"rl:{namespace}:*"))
    assert keys
    assert all(0 < client_redis.pttl(k) <= 2000 for k in keys)  # kept for two windows only
    time.sleep(2.3)
    assert not list(client_redis.scan_iter(f"rl:{namespace}:*"))
    assert limiter.check(policy, "u").allowed


def test_limit_is_exact_under_concurrency(limiter: RateLimiter, client_redis: redis.Redis) -> None:
    ensure_room(client_redis, 60, 6)
    a, b = Policy("ca", 20), Policy("cb", 30)
    barrier = threading.Barrier(50)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def hit() -> None:
        barrier.wait()
        decision = limiter.check_all([(a, "who"), (b, "who")])
        with lock:
            outcomes.append(decision.allowed)

    threads = [threading.Thread(target=hit) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert outcomes.count(True) == 20
    # Neither limit was charged for the 30 denied requests: b has exactly 10 left.
    assert [limiter.check(b, "who").allowed for _ in range(11)] == [True] * 10 + [False]


def test_environments_tenants_and_actors_are_isolated(
    client_redis: redis.Redis, namespace: str
) -> None:
    dev = RateLimiter(client_redis, namespace=f"{namespace}-dev")
    prod = RateLimiter(client_redis, namespace=f"{namespace}-prod")
    try:
        ensure_room(client_redis, 60, 5)
        policy = Policy("iso", 1)
        assert dev.check(policy, "same-id").allowed
        assert not dev.check(policy, "same-id").allowed
        assert prod.check(policy, "same-id").allowed  # another environment
        assert dev.check(policy, "tenant:t2|user:u1").allowed  # another tenant, same actor
        assert dev.check(policy, "tenant:t1|user:u1").allowed
        assert dev.check(policy, "tenant:t1|user:u2").allowed  # another actor, same tenant
        assert not dev.check(policy, "tenant:t1|user:u1").allowed
    finally:
        for key in client_redis.scan_iter(f"rl:{namespace}-*"):
            client_redis.delete(key)


def test_keys_do_not_contain_identities(
    limiter: RateLimiter, client_redis: redis.Redis, namespace: str
) -> None:
    limiter.check(Policy("p", 5), "203.0.113.77")
    limiter.check(Policy("p", 5), "tenant:t-secret|user:u-secret")
    keys = list(client_redis.scan_iter(f"rl:{namespace}:*"))
    assert keys
    assert not any(x in k for k in keys for x in ("203.0.113.77", "t-secret", "u-secret"))
    assert all(k.startswith(f"rl:{namespace}:p:") for k in keys)


# --- HTTP behaviour with test-only routes --------------------------------------------------


def app_for(
    limiter: RateLimiter | None,
    monkeypatch: pytest.MonkeyPatch,
    trusted: list[IPNetwork] | None = None,
    peer: str = "198.51.100.1",
) -> TestClient:
    for name, value in {
        "RATE_LIMIT_PUBLIC_PER_MIN": "3",
        "RATE_LIMIT_AUTHENTICATED_PER_MIN": "5",
        "RATE_LIMIT_TENANT_PER_MIN": "7",
        "RATE_LIMIT_UPLOAD_PER_MIN": "2",
        "RATE_LIMIT_EXPORT_PER_MIN": "1",
    }.items():
        monkeypatch.setenv(name, value)
    p = build_policies(RateLimitSettings())
    nets = trusted or []
    app = create_app(limiter)

    def synthetic_context(request: Request) -> None:  # test-only stand-in for authentication
        request.state.principal_id = request.headers.get("x-test-user")
        request.state.tenant_id = request.headers.get("x-test-tenant")

    ctx = Depends(synthetic_context)
    public = rate_limits([Rule(p["public"], by_ip(nets))], nets)
    authed = rate_limits(
        [Rule(p["authenticated"], by_principal), Rule(p["tenant"], by_tenant)], nets
    )
    upload = rate_limits(
        [
            Rule(p["upload"], by_principal),
            Rule(p["authenticated"], by_principal),
            Rule(p["tenant"], by_tenant),
        ],
        nets,
    )
    export = rate_limits([Rule(p["export"], by_principal), Rule(p["tenant"], by_tenant)], nets)

    @app.get("/t/public")
    def _public(_: Annotated[None, Depends(public)]) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/t/auth", dependencies=[ctx])
    def _auth(_: Annotated[None, Depends(authed)]) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/t/upload", dependencies=[ctx])
    def _upload(_: Annotated[None, Depends(upload)]) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/t/export", dependencies=[ctx])
    def _export(_: Annotated[None, Depends(export)]) -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False, client=(peer, 5000))


def who(user: str, tenant: str) -> dict[str, str]:
    return {"x-test-user": user, "x-test-tenant": tenant}


def test_429_response_headers_and_body(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    first = client.get("/t/public")
    assert first.status_code == 200
    assert (first.headers["ratelimit-limit"], first.headers["ratelimit-remaining"]) == ("3", "2")
    assert client.get("/t/public").status_code == 200
    assert client.get("/t/public").status_code == 200
    denied = client.get("/t/public")
    assert denied.status_code == 429
    assert denied.headers["content-type"].startswith("application/problem+json")
    body = denied.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["type"] == "https://docs.autotramita.es/errors/rate-limit-exceeded"
    assert body["status"] == 429
    assert body["request_id"] == denied.headers["x-request-id"]
    # Waiting out the rest of the bucket plus the decay of the full previous bucket takes up to
    # two windows, so the bound is 120 s (the policy window is 60 s).
    assert 1 <= int(denied.headers["retry-after"]) <= 120
    assert denied.headers["ratelimit-remaining"] == "0"


def test_configured_limits_apply_per_route(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    h = who("u1", "t1")
    assert [client.post("/t/export", headers=h).status_code for _ in range(2)] == [200, 429]
    assert [client.post("/t/upload", headers=h).status_code for _ in range(3)] == [200, 200, 429]


def test_simultaneous_limits_user_tenant_and_all_or_nothing(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    u1 = who("u1", "t1")
    assert [client.post("/t/upload", headers=u1).status_code for _ in range(5)] == [
        200,
        200,
        429,
        429,
        429,
    ]
    # Denied uploads cost nothing: u1 still has 3 of its 5 authenticated requests.
    assert [client.get("/t/auth", headers=u1).status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]


def test_tenant_limit_is_shared_by_users_and_isolated_between_tenants(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    codes = [client.get("/t/auth", headers=who("u1", "t1")).status_code for _ in range(4)]
    codes += [client.get("/t/auth", headers=who("u2", "t1")).status_code for _ in range(4)]
    assert codes == [200] * 7 + [429]  # tenant t1 allows 7 in total, below 5 per user
    assert client.get("/t/auth", headers=who("u3", "t2")).status_code == 200  # another tenant
    # Same user id in another tenant: the per-user quota is global (R07), 5th request passes.
    assert client.get("/t/auth", headers=who("u1", "t3")).status_code == 200


def test_user_quota_is_global_across_tenants(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    codes = [
        client.get("/t/auth", headers=who("u1", f"t{n}")).status_code for n in range(7)
    ]  # a different tenant each time: the user limit (5) still applies
    assert codes == [200] * 5 + [429] * 2
    assert client.get("/t/auth", headers=who("u2", "t0")).status_code == 200  # another user


@pytest.mark.parametrize(
    "headers",
    [{}, {"x-test-user": "u1"}, {"x-test-tenant": "t1"}],
    ids=["none", "no-tenant", "no-user"],
)
def test_missing_identity_fails_closed_without_counting_or_ip_fallback(
    limiter: RateLimiter,
    client_redis: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    for path in ("/t/auth", "/t/upload", "/t/export"):
        for _ in range(12):  # far beyond any limit: always 401, never 429 or 200 via an IP key
            r = client.request("POST" if path != "/t/auth" else "GET", path, headers=headers)
            assert r.status_code == 401
            assert r.json()["code"] == "UNAUTHENTICATED"
            assert r.headers["content-type"].startswith("application/problem+json")
            assert "ratelimit-limit" not in r.headers
    # Nothing was counted: a valid caller still has the whole quota.
    assert [client.get("/t/auth", headers=who("u1", "t1")).status_code for _ in range(5)] == [
        200
    ] * 5
    assert client.get("/t/public").status_code == 200  # anonymous public route unaffected


def test_spoofed_forwarded_headers_cannot_evade_the_public_limit(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    codes = [
        client.get("/t/public", headers={"X-Forwarded-For": f"198.51.100.{n}"}).status_code
        for n in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]


def test_only_the_trusted_proxy_entry_separates_clients(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch, trusted=PROXY, peer="10.0.0.9")
    codes = [
        client.get("/t/public", headers={"X-Forwarded-For": f"6.6.6.{n}, 203.0.113.7"}).status_code
        for n in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]
    other = client.get("/t/public", headers={"X-Forwarded-For": "6.6.6.1, 203.0.113.8"})
    assert other.status_code == 200  # a different real client behind the proxy


def test_untrusted_peer_cannot_spoof_even_when_proxies_are_configured(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch, trusted=PROXY, peer="198.51.100.77")
    codes = [
        client.get("/t/public", headers={"X-Forwarded-For": f"203.0.113.{n}"}).status_code
        for n in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]


def test_health_is_exempt_even_with_exhausted_limits_or_without_redis(
    limiter: RateLimiter, client_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_room(client_redis, 60, 5)
    client = app_for(limiter, monkeypatch)
    for _ in range(5):
        client.get("/t/public")
    assert client.get("/t/public").status_code == 429
    for _ in range(50):
        assert client.get("/api/v1/health").status_code == 200
    assert "ratelimit-limit" not in client.get("/api/v1/health").headers
    down = app_for(dead_limiter(), monkeypatch)
    assert down.get("/api/v1/health").status_code == 200


def test_limited_route_without_redis_is_503_never_unlimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = app_for(dead_limiter(), monkeypatch)
    for _ in range(2):  # no local fallback: every request is refused
        r = client.get("/t/public")
        assert r.status_code == 503
        assert r.json()["code"] == "RATE_LIMIT_UNAVAILABLE"
        assert r.headers["retry-after"] == "5"
        assert r.headers["content-type"].startswith("application/problem+json")
    assert app_for(None, monkeypatch).get("/t/public").status_code == 503  # not configured
