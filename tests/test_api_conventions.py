import json
import logging
import re

import pytest
from app.api.app import create_app
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.logging import REDACTED, JsonFormatter, redact
from app.core.request_context import get_request_id, new_request_id, set_request_id
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class Item(BaseModel):
    name: str = Field(min_length=3)


def make_app() -> FastAPI:
    app = create_app()

    @app.get("/t/not-found")
    def _nf() -> None:
        raise NotFound()

    @app.get("/t/forbidden")
    def _fb() -> None:
        raise Forbidden("No access")

    @app.get("/t/conflict")
    def _cf() -> None:
        raise Conflict("Version changed", code="version_conflict")

    @app.get("/t/boom")
    def _boom() -> None:
        raise RuntimeError("password=hunter2 SELECT * FROM secret")

    @app.post("/t/item")
    def _item(item: Item) -> Item:
        return item

    @app.get("/t/request-id")
    def _rid() -> dict[str, str | None]:
        return {"id": get_request_id()}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app(), raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/t/not-found", 404, "not_found"),
        ("/t/forbidden", 403, "forbidden"),
        ("/t/conflict", 409, "version_conflict"),
        ("/t/missing-route", 404, "not_found"),
    ],
)
def test_errors_are_problem_json(client: TestClient, path: str, status: int, code: str) -> None:
    r = client.get(path)
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == code
    assert body["status"] == status
    assert body["request_id"] == r.headers["x-request-id"]


def test_method_not_allowed_is_problem_json(client: TestClient) -> None:
    r = client.delete("/t/not-found")
    assert r.status_code == 405
    assert r.json()["code"] == "method_not_allowed"


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    r = client.post("/t/item", json={"name": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "body.name"
    assert '"x"' not in r.text


def test_unhandled_errors_are_generic(client: TestClient) -> None:
    r = client.get("/t/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert "hunter2" not in r.text
    assert "SELECT" not in r.text


def test_request_id_generated_and_propagated(client: TestClient) -> None:
    r = client.get("/t/request-id")
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])
    assert r.json()["id"] == r.headers["x-request-id"]
    r2 = client.get("/t/request-id", headers={"X-Request-ID": "client-supplied-1234"})
    assert r2.headers["x-request-id"] == "client-supplied-1234"


def test_unsafe_request_id_is_replaced() -> None:
    assert new_request_id("bad\nid with spaces") != "bad\nid with spaces"
    assert new_request_id("short") != "short"
    assert re.fullmatch(r"[0-9a-f]{32}", new_request_id(None))


def test_redaction_masks_sensitive_keys_recursively() -> None:
    data = {
        "Authorization": "Bearer abc",
        "nested": {"password": "x", "ok": 1, "list": [{"api_key": "k", "v": 2}]},
        "NIF": "12345678Z",
        "Idempotency-Key": "abc",
    }
    out = redact(data)
    assert out["Authorization"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert out["nested"]["list"][0]["api_key"] == REDACTED
    assert out["NIF"] == REDACTED
    assert out["Idempotency-Key"] == REDACTED
    assert out["nested"]["ok"] == 1


def test_json_log_formatter_redacts_and_omits_exception_message() -> None:
    set_request_id("rid-123456789")
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "msg", None, None)
    record.fields = {"token": "secret", "k": "v"}
    try:
        raise ValueError("password=hunter2")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    line = JsonFormatter().format(record)
    set_request_id(None)
    parsed = json.loads(line)
    assert parsed["request_id"] == "rid-123456789"
    assert parsed["fields"]["token"] == REDACTED
    assert parsed["exception"] == "ValueError"
    assert "hunter2" not in line
