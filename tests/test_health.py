from collections.abc import Iterator

import pytest
import redis
from app.api.app import create_app
from app.core.config import RateLimitSettings, Settings
from app.core.db import create_db_engine
from app.core.ratelimit import RateLimiter, create_redis
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from tests.conftest import RoleEnv


@pytest.fixture
def live_redis(redis_url: str) -> Iterator[redis.Redis]:
    client = create_redis(redis_url)
    yield client
    client.close()


def test_liveness_needs_no_dependencies() -> None:
    client = TestClient(create_app())
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert "x-request-id" in r.headers


def test_health_is_exempt_from_rate_limiting(live_redis: redis.Redis) -> None:
    limiter = RateLimiter(live_redis, namespace="health-exempt")
    client = TestClient(create_app(limiter, rate_limit_settings=RateLimitSettings()))
    for _ in range(200):  # more than the public limit of 60 per minute
        assert client.get("/api/v1/health").status_code == 200
    assert "ratelimit-limit" not in client.get("/api/v1/health").headers


def test_readiness_ok_with_database_and_redis(
    role_env: RoleEnv, live_redis: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine: Engine = role_env.engine("app")
    limiter = RateLimiter(live_redis, namespace="ready-ok")
    client = TestClient(create_app(limiter, engine))
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    engine.dispose()


def test_readiness_failure_reveals_nothing(live_redis: redis.Redis) -> None:
    broken = Settings.model_construct(
        postgres_host="db-secret-host.internal",
        postgres_port=1,
        postgres_db="secretdb",
        postgres_user="secret_user",
        postgres_password=SecretStr("secret-password"),
    )
    engine = create_db_engine(broken)
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1, socket_timeout=0.1)
    client = TestClient(create_app(RateLimiter(dead, namespace="x"), engine))
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["code"] == "NOT_READY"
    for secret in ("db-secret-host", "secretdb", "secret_user", "secret-password", "127.0.0.1"):
        assert secret not in r.text
    engine.dispose()


def test_docs_and_unknown_routes_are_closed() -> None:
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/api/v1/nope"):
        r = client.get(path)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/problem+json")
