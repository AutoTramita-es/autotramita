import json
import logging
import uuid

import pytest
from app.api.app import create_app
from app.core.errors import (
    AppError,
    BadRequest,
    Conflict,
    Forbidden,
    InternalError,
    NotFound,
    PayloadTooLarge,
    PreconditionFailed,
    PreconditionRequired,
    ServiceUnavailable,
    TooManyRequests,
    Unauthenticated,
    UnprocessableEntity,
    UnsupportedMediaType,
)
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
        raise Conflict("Version changed", code="VERSION_CONFLICT")

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
        ("/t/not-found", 404, "NOT_FOUND"),
        ("/t/forbidden", 403, "FORBIDDEN"),
        ("/t/conflict", 409, "VERSION_CONFLICT"),
        ("/t/missing-route", 404, "NOT_FOUND"),
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
    assert r.json()["code"] == "METHOD_NOT_ALLOWED"


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    r = client.post("/t/item", json={"name": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["field"] == "body.name"
    assert '"x"' not in r.text


def test_unhandled_errors_are_generic(client: TestClient) -> None:
    r = client.get("/t/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert "hunter2" not in r.text
    assert "SELECT" not in r.text


def test_request_id_generated_and_propagated(client: TestClient) -> None:
    r = client.get("/t/request-id")
    assert str(uuid.UUID(r.headers["x-request-id"])) == r.headers["x-request-id"]
    assert r.json()["id"] == r.headers["x-request-id"]
    supplied = "5d1e2c3b-4a59-4f68-8a7b-9c0d1e2f3a4b"
    r2 = client.get("/t/request-id", headers={"X-Request-ID": supplied})
    assert r2.headers["x-request-id"] == supplied


def test_unsafe_request_id_is_replaced() -> None:
    for bad in ("bad\nid with spaces", "short", "client-supplied-1234", "x" * 200):
        replaced = new_request_id(bad)
        assert replaced != bad
        assert str(uuid.UUID(replaced)) == replaced
    generated = new_request_id(None)
    assert str(uuid.UUID(generated)) == generated


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


# --- F1-T06 contract additions -------------------------------------------------------------

ALL_ERRORS = [
    (BadRequest, 400, "BAD_REQUEST"),
    (Unauthenticated, 401, "UNAUTHENTICATED"),
    (Forbidden, 403, "FORBIDDEN"),
    (NotFound, 404, "NOT_FOUND"),
    (Conflict, 409, "CONFLICT"),
    (PreconditionFailed, 412, "PRECONDITION_FAILED"),
    (PayloadTooLarge, 413, "PAYLOAD_TOO_LARGE"),
    (UnsupportedMediaType, 415, "UNSUPPORTED_MEDIA_TYPE"),
    (UnprocessableEntity, 422, "VALIDATION_ERROR"),
    (PreconditionRequired, 428, "PRECONDITION_REQUIRED"),
    (TooManyRequests, 429, "RATE_LIMIT_EXCEEDED"),
    (InternalError, 500, "INTERNAL_ERROR"),
    (ServiceUnavailable, 503, "SERVICE_UNAVAILABLE"),
]


@pytest.mark.parametrize(("error", "status", "code"), ALL_ERRORS)
def test_status_mapping_and_problem_shape(error: type[AppError], status: int, code: str) -> None:
    app = create_app()

    @app.get("/t/raise")
    def _raise() -> None:
        raise error("Something specific.")

    r = TestClient(app, raise_server_exceptions=False).get("/t/raise")
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert set(body) == {"type", "title", "status", "detail", "code", "request_id"}
    assert body["status"] == status
    assert body["code"] == code
    assert body["detail"] == "Something specific."
    assert body["type"] == "https://docs.autotramita.es/errors/" + code.lower().replace("_", "-")
    assert str(uuid.UUID(body["request_id"])) == body["request_id"] == r.headers["x-request-id"]


def test_codes_must_be_upper_snake_case() -> None:
    for bad in ("not_found", "Not_Found", "NOT-FOUND", "1BAD", "", "TRAILING_"):
        with pytest.raises(ValueError):
            BadRequest("x", code=bad)
    assert BadRequest("x", code="IDEMPOTENCY_KEY_REUSE").code == "IDEMPOTENCY_KEY_REUSE"


def test_validation_errors_never_quote_submitted_values() -> None:
    app = make_app()

    @app.get("/t/things/{thing_id}")
    def _get(thing_id: uuid.UUID) -> dict[str, str]:
        return {"id": str(thing_id)}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/t/things/secret-value-12345")
    assert r.status_code == 422
    assert "secret-value-12345" not in r.text
    assert r.json()["errors"] == [{"field": "path.thing_id", "message": "Must be a valid UUID"}]
    typed = client.post("/t/item", json={"name": 12345, "extra": "leak-me-999"})
    assert typed.status_code == 422
    assert "12345" not in typed.text
    assert "leak-me-999" not in typed.text
    broken = client.post(
        "/t/item", content=b'{"name": "pii-9876"', headers={"content-type": "application/json"}
    )
    assert broken.status_code == 422
    assert "pii-9876" not in broken.text


def test_request_id_is_in_every_response_including_framework_errors(client: TestClient) -> None:
    for r in (client.get("/t/missing-route"), client.delete("/t/not-found"), client.get("/t/boom")):
        assert r.headers["x-request-id"]
        assert r.json()["request_id"] == r.headers["x-request-id"]


def test_redaction_covers_idempotency_key_and_personal_identifiers() -> None:
    out = redact({"idempotency_key": "k", "vin": "V", "iban": "I", "cookie": "c", "safe": "s"})
    assert out == {
        "idempotency_key": REDACTED,
        "vin": REDACTED,
        "iban": REDACTED,
        "cookie": REDACTED,
        "safe": "s",
    }
