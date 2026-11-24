import threading
import time
import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
import redis
from app.api.app import create_app
from app.core.config import RateLimitSettings
from app.core.errors import ServiceUnavailable
from app.core.ratelimit import (
    Policy,
    RateLimiter,
    build_policies,
    by_ip,
    by_principal,
    by_tenant,
    client_ip,
    create_redis,
    rate_limit,
)
from fastapi import Depends
from fastapi.testclient import TestClient


@pytest.fixture
def client_redis(redis_url: str) -> Iterator[redis.Redis]:
    client = create_redis(redis_url)
    yield client
    client.close()


@pytest.fixture
def limiter(client_redis: redis.Redis) -> Iterator[RateLimiter]:
    ns = f"test-{uuid.uuid4().hex[:8]}"
    yield RateLimiter(client_redis, namespace=ns)
    for key in client_redis.scan_iter(f"rl:{ns}:*"):
        client_redis.delete(key)


def test_approved_default_limits() -> None:
    s = RateLimitSettings()
    assert (s.public_per_min, s.authenticated_per_min, s.tenant_per_min) == (60, 300, 3000)
    assert (s.upload_per_min, s.export_per_min) == (30, 5)
    assert (s.keycloak_max_failed_logins, s.keycloak_failure_window_minutes) == (5, 15)
    assert s.password_recovery_per_hour == 3
    assert s.fail_open is True
    assert s.trusted_proxy_hops == 0
    policies = build_policies(s)
    assert {n: p.limit for n, p in policies.items()} == {
        "public": 60,
        "authenticated": 300,
        "tenant": 3000,
        "upload": 30,
        "export": 5,
    }


def test_limits_are_configurable_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_EXPORT_PER_MIN", "2")
    monkeypatch.setenv("RATE_LIMIT_FAIL_OPEN", "false")
    s = RateLimitSettings()
    assert s.export_per_min == 2
    assert s.fail_open is False
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_PER_MIN", "0")
    with pytest.raises(ValueError):
        RateLimitSettings()


def test_allows_up_to_limit_then_denies(limiter: RateLimiter) -> None:
    policy = Policy("t", 3)
    results = [limiter.check(policy, "who") for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0, 0]
    assert 0 < results[0].reset_seconds <= 60


def test_window_resets(limiter: RateLimiter) -> None:
    policy = Policy("t", 1, window_seconds=1)
    assert limiter.check(policy, "who").allowed
    assert not limiter.check(policy, "who").allowed
    time.sleep(1.2)
    assert limiter.check(policy, "who").allowed


def test_identities_and_policies_are_independent(limiter: RateLimiter) -> None:
    a, b = Policy("a", 1), Policy("b", 1)
    assert limiter.check(a, "tenant:1").allowed
    assert not limiter.check(a, "tenant:1").allowed
    assert limiter.check(a, "tenant:2").allowed
    assert limiter.check(b, "tenant:1").allowed


def test_limit_is_exact_under_concurrency(limiter: RateLimiter) -> None:
    policy = Policy("c", 20)
    barrier = threading.Barrier(50)
    allowed: list[bool] = []
    lock = threading.Lock()

    def hit() -> None:
        barrier.wait()
        decision = limiter.check(policy, "who")
        with lock:
            allowed.append(decision.allowed)

    threads = [threading.Thread(target=hit) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert allowed.count(True) == 20


def test_keys_do_not_contain_the_identity(limiter: RateLimiter, client_redis: redis.Redis) -> None:
    limiter.check(Policy("p", 5), "203.0.113.77")
    keys = list(client_redis.scan_iter("rl:*"))
    assert keys
    assert not any("203.0.113.77" in k for k in keys)


def app_with(limiter: RateLimiter, policy: Policy) -> TestClient:
    app = create_app(limiter)
    limited = rate_limit(policy, by_ip())

    @app.get("/limited")
    def _limited(_: Annotated[None, Depends(limited)]) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/exempt")
    def _exempt() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_http_headers_429_and_exempt_route(limiter: RateLimiter) -> None:
    client = app_with(limiter, Policy("http", 2))
    first = client.get("/limited")
    assert first.status_code == 200
    assert first.headers["ratelimit-limit"] == "2"
    assert first.headers["ratelimit-remaining"] == "1"
    assert client.get("/limited").status_code == 200
    denied = client.get("/limited")
    assert denied.status_code == 429
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert denied.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(denied.headers["retry-after"]) >= 1
    assert denied.headers["ratelimit-remaining"] == "0"
    for _ in range(10):  # health-style routes without the dependency are never limited
        assert client.get("/exempt").status_code == 200


def closed_port_limiter(fail_open: bool) -> RateLimiter:
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1, socket_timeout=0.1)
    return RateLimiter(dead, namespace="dead", fail_open=fail_open)


def test_fail_open_allows_when_redis_is_down() -> None:
    assert closed_port_limiter(True).check(Policy("p", 1), "x").allowed


def test_fail_closed_answers_503_when_redis_is_down() -> None:
    with pytest.raises(ServiceUnavailable) as err:
        closed_port_limiter(False).check(Policy("p", 1), "x")
    assert err.value.code == "RATE_LIMIT_UNAVAILABLE"


class FakeRequest:
    def __init__(self, peer: str | None, xff: str | None = None) -> None:
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.state = type("S", (), {})()


def test_client_ip_ignores_forwarded_header_unless_trusted() -> None:
    req = FakeRequest("10.0.0.9", "1.2.3.4, 5.6.7.8")
    assert client_ip(req, 0) == "10.0.0.9"  # type: ignore[arg-type]
    assert client_ip(req, 1) == "5.6.7.8"  # type: ignore[arg-type]
    assert client_ip(req, 2) == "1.2.3.4"  # type: ignore[arg-type]
    assert client_ip(req, 3) == "10.0.0.9"  # type: ignore[arg-type]  # fewer hops than trusted
    assert client_ip(FakeRequest("10.0.0.9", "not-an-ip"), 1) == "10.0.0.9"  # type: ignore[arg-type]
    assert client_ip(FakeRequest(None), 0) == "unknown"  # type: ignore[arg-type]


def test_principal_and_tenant_identities() -> None:
    req = FakeRequest("1.1.1.1")
    assert by_principal(req) is None  # type: ignore[arg-type]
    req.state.principal_id = "u1"
    req.state.tenant_id = "t1"
    assert by_principal(req) == "user:u1"  # type: ignore[arg-type]
    assert by_tenant(req) == "tenant:t1"  # type: ignore[arg-type]
