"""F1-T08: liveness-only health, OpenTelemetry hook without exporter, redaction (AC12)."""

import json
import logging
import socket
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import redis
from app.api.app import create_app
from app.core.config import RateLimitSettings, Settings
from app.core.db import create_db_engine
from app.core.health import check_dependencies
from app.core.logging import JsonFormatter
from app.core.ratelimit import RateLimiter, create_redis
from app.core.telemetry import get_tracer, set_tracer_provider
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import SecretStr
from sqlalchemy import Engine
from tests.conftest import RoleEnv

SECRET_HOST, SECRET_DB, SECRET_USER, SECRET_PW = (
    "db-secret-host.internal",
    "secretdb",
    "secret_user",
    "secret-password",
)


def broken_engine() -> Engine:
    broken = Settings.model_construct(
        postgres_host=SECRET_HOST,
        postgres_port=1,
        postgres_db=SECRET_DB,
        postgres_user=SECRET_USER,
        postgres_password=SecretStr(SECRET_PW),
    )
    return create_db_engine(broken)


def dead_limiter() -> RateLimiter:
    return RateLimiter(create_redis("redis://127.0.0.1:1/0"), namespace="dead")


@pytest.fixture
def live_redis(redis_url: str) -> Iterator[redis.Redis]:
    client = create_redis(redis_url)
    yield client
    client.close()


# --- liveness: minimal, non-sensitive, independent of every dependency ---------------------


def test_liveness_response_is_minimal() -> None:
    r = TestClient(create_app()).get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["content-type"] == "application/json"
    assert str(uuid.UUID(r.headers["x-request-id"])) == r.headers["x-request-id"]


def test_liveness_touches_no_dependency_and_reveals_nothing() -> None:
    engine = broken_engine()
    client = TestClient(create_app(dead_limiter(), engine))
    started = time.monotonic()
    r = client.get("/api/v1/health")
    assert time.monotonic() - started < 0.4  # no 500 ms timeouts: nothing was contacted
    assert (r.status_code, r.json()) == (200, {"status": "ok"})
    everything = r.text + str(dict(r.headers))
    for secret in (
        SECRET_HOST,
        SECRET_DB,
        SECRET_USER,
        SECRET_PW,
        "127.0.0.1",
        "postgres",
        "redis",
    ):
        assert secret.lower() not in everything.lower()
    engine.dispose()


def test_limiter_outage_does_not_block_health() -> None:
    client = TestClient(create_app(dead_limiter(), rate_limit_settings=RateLimitSettings()))
    for _ in range(100):  # also far above the public limit of 60 per minute
        assert client.get("/api/v1/health").status_code == 200
    assert "ratelimit-limit" not in client.get("/api/v1/health").headers


def test_health_is_exempt_with_a_working_limiter(live_redis: redis.Redis) -> None:
    limiter = RateLimiter(live_redis, namespace="health-exempt")
    client = TestClient(create_app(limiter, rate_limit_settings=RateLimitSettings()))
    for _ in range(200):
        assert client.get("/api/v1/health").status_code == 200
    assert "ratelimit-limit" not in client.get("/api/v1/health").headers


def test_no_public_readiness_route_and_no_other_health_paths() -> None:
    client = TestClient(create_app(dead_limiter(), broken_engine()))
    for path in ("/api/v1/health/ready", "/api/v1/health/live", "/health", "/ready"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/problem+json")
    paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
    assert [p for p in paths if "health" in p] == ["/api/v1/health"]


def test_docs_and_unknown_routes_are_closed() -> None:
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/api/v1/unknown"):
        assert client.get(path).status_code == 404


# --- internal dependency check (not an HTTP route) -----------------------------------------


def test_dependency_check_ok_with_database_and_redis(
    role_env: RoleEnv, live_redis: redis.Redis
) -> None:
    engine = role_env.engine("app")
    assert check_dependencies(engine, RateLimiter(live_redis, namespace="deps-ok")) == []
    assert check_dependencies(None, None) == []
    engine.dispose()


def test_dependency_check_names_components_and_reveals_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    engine = broken_engine()
    assert check_dependencies(engine, dead_limiter()) == ["database", "redis"]
    for secret in (SECRET_HOST, SECRET_DB, SECRET_USER, SECRET_PW, "127.0.0.1"):
        assert secret not in caplog.text
    engine.dispose()


# --- OpenTelemetry hook: spans without any exporter or network ------------------------------


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)
    yield exporter
    set_tracer_provider(None)


def server_span(exporter: InMemorySpanExporter) -> ReadableSpan:
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    return finished[0]


def test_each_request_gets_one_span_with_only_safe_attributes(
    spans: InMemorySpanExporter,
) -> None:
    client = TestClient(create_app())
    r = client.get("/api/v1/health?token=query-secret", headers={"Authorization": "Bearer abc"})
    span = server_span(spans)
    assert span.name == "GET /api/v1/health"
    assert dict(span.attributes or {}) == {
        "http.request.method": "GET",
        "http.route": "/api/v1/health",
        "http.response.status_code": 200,
        "autotramita.request_id": r.headers["x-request-id"],
    }
    assert "query-secret" not in str(span.to_json()) and "Bearer" not in str(span.to_json())


def test_parameter_values_never_reach_the_span_name_or_attributes(
    spans: InMemorySpanExporter,
) -> None:
    app = create_app()

    @app.get("/api/v1/t/things/{thing_id}")
    def _thing(thing_id: uuid.UUID) -> dict[str, str]:
        return {"id": str(thing_id)}

    thing = uuid.uuid4()
    assert TestClient(app).get(f"/api/v1/t/things/{thing}").status_code == 200
    span = server_span(spans)
    assert span.name == "GET /api/v1/t/things/{thing_id}"
    assert str(thing) not in span.to_json()


def test_unmatched_paths_never_put_the_raw_path_in_a_span(spans: InMemorySpanExporter) -> None:
    TestClient(create_app()).get("/t/customer-123456/secret")
    span = server_span(spans)
    assert span.name == "GET unmatched"
    assert "customer-123456" not in span.to_json()
    assert dict(span.attributes or {})["http.response.status_code"] == 404


def test_unhandled_errors_mark_the_span_without_the_exception_message(
    spans: InMemorySpanExporter,
) -> None:
    app = create_app()

    @app.get("/t/boom")
    def _boom() -> None:
        raise RuntimeError("password=hunter2 SELECT * FROM secret")

    r = TestClient(app, raise_server_exceptions=False).get("/t/boom")
    assert r.status_code == 500
    span = server_span(spans)
    assert span.status.status_code is StatusCode.ERROR
    assert dict(span.attributes or {})["http.response.status_code"] == 500
    assert "hunter2" not in span.to_json() and "SELECT" not in span.to_json()
    assert not span.events  # no recorded exception with its message


def test_without_a_provider_the_hook_is_a_noop() -> None:
    set_tracer_provider(None)
    r = TestClient(create_app()).get("/api/v1/health")
    assert r.status_code == 200
    with get_tracer().start_as_current_span("x") as span:
        assert not span.is_recording()


def test_no_exporter_no_credentials_and_no_network(
    spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    client = TestClient(create_app())
    for _ in range(3):
        assert client.get("/api/v1/health").status_code == 200
    assert len(spans.get_finished_spans()) == 3
    assert not [m for m in sys.modules if m.startswith("opentelemetry.exporter")]
    pyproject = Path("pyproject.toml").read_text()
    assert "opentelemetry-exporter" not in pyproject and "sentry" not in pyproject.lower()


# --- request id and redaction ---------------------------------------------------------------


def test_error_logs_are_redacted_and_carry_the_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()

    @app.get("/t/boom")
    def _boom() -> None:
        raise RuntimeError("password=hunter2 token=abc123")

    caplog.set_level(logging.DEBUG)
    r = TestClient(app, raise_server_exceptions=False).get("/t/boom")
    formatter = JsonFormatter()
    lines = [formatter.format(rec) for rec in caplog.records if "unhandled" in rec.getMessage()]
    assert len(lines) == 1
    assert "hunter2" not in lines[0] and "abc123" not in lines[0]
    assert json.loads(lines[0])["fields"] == {"type": "RuntimeError"}
    assert r.json()["request_id"] == r.headers["x-request-id"]
