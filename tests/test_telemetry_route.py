"""R08: the span route is a registered template or ``unmatched``; request values never leak.

No Redis or PostgreSQL needed; spans go to an in-memory exporter and nothing leaves the process.
"""

from collections.abc import Iterator

import pytest
from app.api.app import create_app
from app.api.telemetry import UNMATCHED_ROUTE, route_template
from app.core.telemetry import set_tracer_provider
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.types import Scope

SECRET = "SECRET-9f3a"


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)
    yield exporter
    set_tracer_provider(None)


class FakeRoute:
    def __init__(self, path_format: str) -> None:
        self.path_format = path_format
        self.path = path_format


def scope(route: object | None, path: str, **params: object) -> Scope:
    return {"type": "http", "route": route, "path": path, "path_params": params}


def only_span(exporter: InMemorySpanExporter) -> ReadableSpan:
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    return finished[0]


# --- unit: template derivation --------------------------------------------------------------


def test_no_route_is_constant_unmatched() -> None:
    assert route_template(scope(None, f"/x/{SECRET}")) == UNMATCHED_ROUTE
    assert route_template({"type": "http", "path": f"/x/{SECRET}"}) == UNMATCHED_ROUTE
    assert route_template(scope(object(), f"/x/{SECRET}")) == UNMATCHED_ROUTE
    assert route_template(scope(FakeRoute(""), f"/x/{SECRET}")) == UNMATCHED_ROUTE


def test_template_is_the_registered_one_and_never_reads_the_request_path() -> None:
    cases: list[tuple[FakeRoute, str, dict[str, object]]] = [
        (FakeRoute("/health"), "/api/v1/health", {}),
        (FakeRoute("/cases/{cid}"), f"/api/v1/cases/{SECRET}", {"cid": SECRET}),
        (FakeRoute("/a/{x}/b/{y}"), f"/p/a/{SECRET}/b/{SECRET}", {"x": SECRET, "y": SECRET}),
        (FakeRoute("/c/{x}"), "/v1/c/v1", {"x": "v1"}),
        (FakeRoute("/n/{i}"), "/api/n/007", {"i": 7}),
        (FakeRoute("/x/{a}"), f"/sub/{SECRET}/x/AVAL", {"tenant": SECRET, "a": "AVAL"}),
    ]
    for route, path, params in cases:
        got = route_template(scope(route, path, **params))
        assert got == route.path_format
        assert SECRET not in got


def test_path_and_params_cannot_change_the_result() -> None:
    route = FakeRoute("/cases/{cid}")
    results = {
        route_template(scope(route, path, **params))
        for path, params in [
            ("/", {}),
            ("/anything/at/all", {"cid": "v"}),
            (f"/{SECRET}", {"cid": SECRET, "z": SECRET}),
        ]
    }
    assert results == {"/cases/{cid}"}
    assert route_template({"type": "http", "route": route}) == "/cases/{cid}"


# --- real app: spans ------------------------------------------------------------------------


def build_app() -> TestClient:
    app = create_app()
    inner = APIRouter(prefix="/cases")

    @inner.get("/{case_id}/docs/{name:path}")
    def _doc(case_id: str, name: str) -> dict[str, str]:
        return {"c": case_id, "n": name}

    @inner.get("/{case_id}/n/{n:int}")
    def _num(case_id: str, n: int) -> dict[str, int]:
        return {"n": n}

    @inner.get("/boom/{case_id}")
    def _boom(case_id: str) -> None:
        raise RuntimeError(f"password=hunter2 {case_id}")

    outer = APIRouter(prefix="/api/v1/t")
    outer.include_router(inner)
    app.include_router(outer)
    sub = FastAPI()

    @sub.get("/x/{a}")
    def _sub(a: str) -> str:
        return a

    app.mount("/tenant/{tenant_id}", sub)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"/api/v1/t/cases/{SECRET}/docs/a/b/{SECRET}?token={SECRET}",
            "/cases/{case_id}/docs/{name}",
        ),
        (
            f"/api/v1/t/cases/{SECRET}/docs/{SECRET}/{SECRET}",
            "/cases/{case_id}/docs/{name}",
        ),
        (f"/api/v1/t/cases/{SECRET}/n/007", None),  # registered relative template
        (f"/api/v1/t/cases/boom/{SECRET}", "/cases/boom/{case_id}"),
        (f"/tenant/{SECRET}/x/{SECRET}2", None),
    ],
)
def test_spans_carry_only_templates(
    spans: InMemorySpanExporter, url: str, expected: str | None
) -> None:
    build_app().get(url, headers={"Authorization": f"Bearer {SECRET}"})
    span = only_span(spans)
    dumped = span.to_json()
    assert SECRET not in dumped and "hunter2" not in dumped
    route = dict(span.attributes or {})["http.route"]
    assert not str(route).endswith("007") and "/007" not in str(route)
    assert span.name.endswith(str(route))
    if expected is not None:
        assert route == expected
    else:
        assert "{" in str(route) or route == UNMATCHED_ROUTE


def test_unmatched_and_method_not_allowed_use_the_constant(spans: InMemorySpanExporter) -> None:
    client = build_app()
    client.get(f"/nothing/{SECRET}")
    client.post("/api/v1/health")  # path exists, method does not
    names = [s.name for s in spans.get_finished_spans()]
    assert names[0] == "GET unmatched"
    assert all(SECRET not in s.to_json() for s in spans.get_finished_spans())
    assert names[1] in ("POST unmatched", "POST /health")


def test_no_exporter_means_no_spans_leave_the_process() -> None:
    set_tracer_provider(None)
    assert build_app().get(f"/api/v1/t/cases/{SECRET}/docs/x").status_code == 200
