"""OpenAPI contract tests: the committed spec is valid, current, and matches real responses."""

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
import redis
from app.api.app import create_app
from app.api.export_openapi import TARGET, render
from app.api.openapi import API_VERSION, PROBLEM_RESPONSES
from app.api.v1.health import Health
from app.core.ratelimit import Policy, RateLimiter, by_ip, create_redis, rate_limit
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from tests.test_api_conventions import ALL_ERRORS

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


BROWSER_REDIRECTS = {("get", "/api/v1/auth/login"), ("get", "/api/v1/auth/callback")}


def test_every_operation_is_described_and_has_a_success_response(spec: dict[str, Any]) -> None:
    assert spec["paths"], "the contract must not be empty"
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            assert operation.get("summary"), (path, method)
            codes = operation["responses"]
            if any(code.startswith("2") for code in codes):
                continue
            # Only the two browser navigations of the sign-in answer with a redirect instead of
            # a 2xx; every other operation keeps F1's rule (AC-CTX-01 equivalence).
            assert (method, path) in BROWSER_REDIRECTS and "302" in codes, (path, method)


def test_errors_are_problem_json_and_no_default_validation_schema(spec: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if status[0] in "23":  # success and redirects carry no problem body
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


# --- F1-T09: deterministic, versioned, matching the real application -----------------------

ROOT = Path(__file__).resolve().parents[1]
UUID_TEXT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_export_is_deterministic_across_runs_processes_and_environments() -> None:
    assert render() == render()
    outputs = set()
    for seed, extra in (("0", {}), ("12345", {"ENVIRONMENT": "prod", "POSTGRES_HOST": "x"})):
        env = {**os.environ, "PYTHONHASHSEED": seed, **extra}
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.api.export_openapi import render; print(render(), end='')",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.add(result.stdout)
    assert outputs == {render()}
    text = Path(TARGET).read_text()
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n" == text


def test_schema_is_versioned_consistently(spec: dict[str, Any]) -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", API_VERSION)
    assert spec["info"]["version"] == API_VERSION
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{API_VERSION}"' in pyproject  # one version for package and contract
    assert all(path.startswith("/api/v1/") for path in spec["paths"])


def test_schema_does_not_depend_on_runtime_configuration(spec: dict[str, Any]) -> None:
    assert "servers" not in spec
    assert "components" in spec and "securitySchemes" not in spec["components"]  # no auth in F1


F2_AUTH_PATHS = [
    "/api/v1/auth/callback",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/mobile/session",
    "/api/v1/auth/oidc/backchannel-logout",
    "/api/v1/auth/session",
    "/api/v1/auth/step-up",
    "/api/v1/sessions",
    "/api/v1/sessions/revoke-all",
    "/api/v1/sessions/revoke-others",
    "/api/v1/sessions/workspace",
    "/api/v1/sessions/{session_id}",
    "/api/v1/me",
    "/api/v1/me/workspaces",
    "/api/v1/auth/password-recovery",
    "/api/v1/auth/email-change-verification",
    "/api/v1/me/security/email-change-requests",
    "/api/v1/me/security/email-change-confirmations",
    "/api/v1/me/email-verification",
    "/api/v1/me/security",
    "/api/v1/me/security/mfa-enrollment-requests",
    "/api/v1/me/security/mfa-disable-requests",
    "/api/v1/me/security/password-change-requests",
    "/api/v1/me/security/second-factors/{credential_id}",
]


def test_only_the_documented_routes_are_exposed_and_nothing_else() -> None:
    app = create_app()
    paths = sorted(json.loads(render())["paths"])
    assert paths == sorted(
        [*F2_AUTH_PATHS, "/api/v1/health"]
    )  # F1 health; F2: T06 web sign-in, T07 mobile and sessions, T08 profile, T09 security
    plain = [getattr(route, "path", None) for route in app.routes]
    assert {p for p in plain if p} <= {"/openapi.json"}  # no hidden docs or test routes


def test_common_response_models(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert set(schemas) == {
        "Health", "Problem", "LogoutResult", "SessionInfo", "StepUpPurpose", "StepUpRequest",
        "StepUpResult", "UserSummary", "WorkspaceInfo", "CursorPage_SessionSummary_", "DeviceBody",
        "MobileSessionRequest", "Revoked", "SessionSummary", "CursorPage_WorkspaceOption_",
        "ProfilePatch", "UserProfile", "WorkspaceOption", "WorkspaceSwitch",
        "Accepted", "ActionStart", "MfaEnrollment", "MfaDisable", "PasswordChange",
        "RecoveryAccepted",
        "RecoveryRequest", "SecondFactor", "SecurityOverview",
        "EmailChangeRequest", "EmailChangeConfirmation",
    }  # fmt: skip
    assert set(schemas["Problem"]["required"]) == {"type", "title", "status", "code"}
    assert set(schemas["Problem"]["properties"]) == {
        "type",
        "title",
        "status",
        "detail",
        "code",
        "request_id",
        "errors",
    }
    assert set(spec["components"]["headers"]) == {
        "RequestId",
        "RetryAfter",
        "RateLimitLimit",
        "RateLimitRemaining",
        "RateLimitReset",
    }


def test_every_documented_response_declares_the_request_id_header(spec: dict[str, Any]) -> None:
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                header = response["headers"]["X-Request-ID"]
                assert header == {"$ref": "#/components/headers/RequestId"}, (path, method, status)


def test_documented_health_responses_match_real_responses(spec: dict[str, Any]) -> None:
    client = TestClient(create_app())
    ok = client.get("/api/v1/health")
    operation = spec["paths"]["/api/v1/health"]["get"]
    assert set(operation["responses"]) == {"200", "500"}  # no 429: health is exempt
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/json"
    assert UUID_TEXT.fullmatch(ok.headers["x-request-id"])


# --- documented problem responses and headers against real ones ----------------------------


def contract_app(limiter: RateLimiter | None = None) -> TestClient:
    """Test-only app: shared problem responses plus routes that produce every error status."""
    app = create_app(limiter)
    router = APIRouter(prefix="/api/v1/t", responses=PROBLEM_RESPONSES)
    errors = {status: (error, code) for error, status, code in ALL_ERRORS}

    @router.get("/errors/{status}", summary="Raise an error", tags=["test-only"])
    def _raise(status: int) -> Health:
        error, _ = errors[status]
        headers = {"Retry-After": "1"} if status in (409, 429, 503) else None
        raise error("Test error.", headers=headers)

    @router.get("/things/{thing_id}", summary="Typed path parameter", tags=["test-only"])
    def _thing(thing_id: uuid.UUID) -> Health:
        return Health()

    limited = rate_limit(Policy("contract", 1), by_ip())

    @router.get("/limited", summary="Rate limited", tags=["test-only"])
    def _limited(_: Annotated[None, Depends(limited)]) -> Health:
        return Health()

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def header_ok(value: str, schema: dict[str, Any]) -> bool:
    if schema["type"] == "integer":
        return value.isdigit() and int(value) >= schema.get("minimum", 0)
    return bool(UUID_TEXT.fullmatch(value))


def test_error_statuses_headers_and_bodies_match_the_declared_contract() -> None:
    client = contract_app()
    spec = client.app.openapi()  # type: ignore[attr-defined]
    validate(spec)
    problem = validator_for(spec, "Problem")
    operation = spec["paths"]["/api/v1/t/errors/{status}"]["get"]
    headers = spec["components"]["headers"]
    for _, status, code in ALL_ERRORS:
        declared = operation["responses"][str(status)]
        assert list(declared["content"]) == [PROBLEM], status
        response = client.get(f"/api/v1/t/errors/{status}")
        assert response.status_code == status
        assert response.headers["content-type"].startswith(PROBLEM)
        body = response.json()
        problem.validate(body)
        assert body["code"] == code
        for name, ref in declared["headers"].items():
            schema = headers[ref["$ref"].rsplit("/", 1)[1]]["schema"]
            if name == "X-Request-ID":
                assert header_ok(response.headers[name], schema)
            elif name in response.headers:
                assert header_ok(response.headers[name], schema), (status, name)


def test_validation_errors_are_documented_and_returned_as_problem() -> None:
    client = contract_app()
    spec = client.app.openapi()  # type: ignore[attr-defined]
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert "ValidationError" not in spec["components"]["schemas"]
    declared = spec["paths"]["/api/v1/t/things/{thing_id}"]["get"]["responses"]["422"]
    assert list(declared["content"]) == [PROBLEM]
    assert declared["content"][PROBLEM]["schema"] == {"$ref": "#/components/schemas/Problem"}
    response = client.get("/api/v1/t/things/not-a-uuid")
    assert response.status_code == 422
    validator_for(spec, "Problem").validate(response.json())
    assert "not-a-uuid" not in response.text


def test_503_rate_limit_unavailable_carries_the_documented_headers() -> None:
    dead = RateLimiter(create_redis("redis://127.0.0.1:1/0"), namespace="contract")
    client = contract_app(dead)
    spec = client.app.openapi()  # type: ignore[attr-defined]
    declared = spec["paths"]["/api/v1/t/limited"]["get"]["responses"]["503"]
    assert set(declared["headers"]) == {"X-Request-ID", "Retry-After"}
    response = client.get("/api/v1/t/limited")
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
    assert response.json()["code"] == "RATE_LIMIT_UNAVAILABLE"
    validator_for(spec, "Problem").validate(response.json())


@pytest.fixture
def contract_redis(redis_url: str) -> Iterator[redis.Redis]:
    client = create_redis(redis_url)
    yield client
    for key in client.scan_iter("rl:contract-429:*"):
        client.delete(key)
    client.close()


def test_429_carries_the_documented_headers(contract_redis: redis.Redis) -> None:
    client = contract_app(RateLimiter(contract_redis, namespace="contract-429"))
    spec = client.app.openapi()  # type: ignore[attr-defined]
    declared = spec["paths"]["/api/v1/t/limited"]["get"]["responses"]["429"]
    assert set(declared["headers"]) == {
        "X-Request-ID",
        "Retry-After",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
    }
    assert client.get("/api/v1/t/limited").status_code == 200
    denied = client.get("/api/v1/t/limited")
    assert denied.status_code == 429
    for name, ref in declared["headers"].items():
        schema = spec["components"]["headers"][ref["$ref"].rsplit("/", 1)[1]]["schema"]
        assert header_ok(denied.headers[name], schema), name
    validator_for(spec, "Problem").validate(denied.json())


# --- client generation is reproducible, pinned and never committed -------------------------


def test_client_generation_commands_are_pinned_and_write_only_temporary_output() -> None:
    script = (ROOT / "openapi" / "check-clients.sh").read_text()
    manifest = json.loads((ROOT / "openapi" / "toolchain" / "package.json").read_text())
    pinned = manifest["devDependencies"]
    for name, constant in (
        ("openapi-typescript", "TS_GENERATOR_VERSION"),
        ("typescript", "TS_COMPILER_VERSION"),
    ):
        assert re.fullmatch(r"\d+\.\d+\.\d+", pinned[name]), f"{name} must be an exact version"
        assert re.search(rf'^{constant}="{re.escape(pinned[name])}" ', script, re.M), constant
    assert set(pinned) == {"openapi-typescript", "typescript"}
    assert "npm ci --ignore-scripts" in script and "npx" not in script  # lockfile, no ad-hoc npx
    assert re.search(
        r'^DART_GENERATOR_IMAGE="[\w/.-]+:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}"$', script, re.M
    )
    assert "latest" not in script
    assert 'work="$(mktemp -d)"' in script and "trap 'rm -rf \"$work\"' EXIT" in script
    assert 'spec="$root/openapi/openapi.json"' in script  # the committed, real contract


def test_no_generated_clients_are_committed() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    try:
        tracked = subprocess.run(  # noqa: S603  fixed arguments, trusted git binary
            [git, "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    forbidden = re.compile(r"(\.dart$|pubspec\.yaml$|schema\.d\.ts$|/generated/|\.api-client)")
    assert [p for p in tracked if forbidden.search(p)] == []
    assert sorted(p for p in tracked if p.startswith("openapi/")) == [
        "openapi/check-clients.sh",
        "openapi/openapi.json",
        "openapi/toolchain/package-lock.json",
        "openapi/toolchain/package.json",
    ]


def test_npm_lockfile_pins_every_package_with_integrity_hashes() -> None:
    lock = json.loads((ROOT / "openapi" / "toolchain" / "package-lock.json").read_text())
    assert lock["lockfileVersion"] >= 3
    packages = {name: meta for name, meta in lock["packages"].items() if name}
    assert packages
    for name, meta in packages.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", meta["version"]), name
        assert meta["resolved"].startswith("https://registry.npmjs.org/"), name
        assert meta["integrity"].startswith("sha512-"), name
    root = lock["packages"][""]["devDependencies"]
    assert packages["node_modules/openapi-typescript"]["version"] == root["openapi-typescript"]
    assert packages["node_modules/typescript"]["version"] == root["typescript"]


def test_dart_generation_does_not_skip_spec_validation_without_a_documented_reason() -> None:
    script = (ROOT / "openapi" / "check-clients.sh").read_text()
    assert "--skip-validate-spec" not in script


# --- R09: the validator really rejects broken contracts (CI also runs the CLI on the file) ---


def broken(spec: dict[str, Any], mutate: Any) -> dict[str, Any]:
    clone: dict[str, Any] = json.loads(json.dumps(spec))
    mutate(clone)
    return clone


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.pop("info"),
        lambda s: s["info"].pop("version"),
        lambda s: s.update(openapi="9.9.9"),
        lambda s: s["paths"].update({"no-slash": {}}),
        lambda s: s["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"].update({"$ref": "#/components/schemas/DoesNotExist"}),
        lambda s: s["components"]["schemas"]["Problem"].update({"type": "not-a-type"}),
        lambda s: s["paths"]["/api/v1/health"]["get"]["responses"].update({"2xx0": {}}),
    ],
    ids=[
        "no-info",
        "no-version",
        "bad-openapi-version",
        "path-without-slash",
        "dangling-ref",
        "bad-schema-type",
        "bad-status-key",
    ],
)
def test_validator_rejects_broken_specs(spec: dict[str, Any], mutate: Any) -> None:
    with pytest.raises(Exception):  # noqa: B017  any validator error class is a failure
        validate(broken(spec, mutate))


def test_validator_cli_exit_codes_match_the_ci_step(spec: dict[str, Any], tmp_path: Path) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(spec))
    bad.write_text(json.dumps(broken(spec, lambda s: s.pop("info"))))
    cmd = [sys.executable, "-m", "openapi_spec_validator"]
    assert subprocess.run([*cmd, str(good)], capture_output=True).returncode == 0  # noqa: S603
    assert subprocess.run([*cmd, str(bad)], capture_output=True).returncode != 0  # noqa: S603
    committed = subprocess.run([*cmd, str(TARGET)], capture_output=True)  # noqa: S603
    assert committed.returncode == 0
