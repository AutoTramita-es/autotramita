"""OpenAPI contract tests: the committed spec is valid, current, and matches real responses."""

import json
from pathlib import Path
from typing import Any

import pytest
from app.api.app import create_app
from app.api.export_openapi import TARGET, render
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

PROBLEM = "application/problem+json"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(Path(TARGET).read_text())
    return loaded


def validator_for(spec: dict[str, Any], schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]}
    )


def test_committed_spec_is_valid_openapi_31(spec: dict[str, Any]) -> None:
    validate(spec)
    assert spec["openapi"].startswith("3.1")


def test_committed_spec_is_current() -> None:
    assert Path(TARGET).read_text() == render(), "run: python -m app.api.export_openapi"


def test_every_operation_is_described_and_has_a_success_response(spec: dict[str, Any]) -> None:
    assert spec["paths"], "the contract must not be empty"
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            assert operation.get("summary"), (path, method)
            assert any(code.startswith("2") for code in operation["responses"]), (path, method)


def test_errors_are_problem_json_and_no_default_validation_schema(spec: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if status.startswith("2"):
                    continue
                assert list(response["content"]) == [PROBLEM], (path, method, status)


def test_operation_ids_are_unique(spec: dict[str, Any]) -> None:
    ids = [op["operationId"] for ops in spec["paths"].values() for op in ops.values()]
    assert len(ids) == len(set(ids))


def test_health_responses_match_the_declared_schemas(spec: dict[str, Any]) -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    declared = spec["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"]
    schema_ref = declared["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
    validator_for(spec, schema_ref).validate(response.json())


def test_real_error_responses_match_the_problem_schema(spec: dict[str, Any]) -> None:
    client = TestClient(create_app())
    validator = validator_for(spec, "Problem")
    for response in (client.get("/api/v1/nope"), client.delete("/api/v1/health")):
        assert response.headers["content-type"].startswith(PROBLEM)
        validator.validate(response.json())
