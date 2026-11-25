"""F1-T10: the CI workflow stays pinned, least-privilege, verification-only and complete.

Plain text checks on purpose (no YAML parser needed): they guard the properties the owner
approved, so a later edit cannot silently loosen them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
# Comments explain choices (and may mention forbidden words); only real configuration is checked.
WORKFLOW = "\n".join(
    re.sub(r"\s+#(?!\s*v\d).*$", "", line)
    for line in RAW.splitlines()
    if not line.lstrip().startswith("#")
)
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}")


def test_only_one_workflow_and_no_dependabot_or_deploy_files() -> None:
    names = sorted(p.name for p in (ROOT / ".github").rglob("*") if p.is_file())
    assert names == ["ci.yml"]  # no deploy workflow, no Dependabot configuration


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", WORKFLOW, re.M)
    assert uses
    for reference in uses:
        name, _, ref = reference.partition("@")
        assert SHA.fullmatch(ref), f"{name} must be pinned to a commit SHA, not '{ref}'"
    assert len(re.findall(r"# v\d+\.\d+\.\d+", WORKFLOW)) >= len(uses)  # readable version


def test_permissions_are_read_only_and_triggers_are_safe() -> None:
    assert re.search(r"^permissions:\n  contents: read\n", WORKFLOW, re.M)
    assert not re.search(r"^\s+[a-z-]+: write\b", WORKFLOW, re.M)
    assert "pull_request_target" not in WORKFLOW
    assert "persist-credentials: false" in WORKFLOW
    assert "${{ secrets." not in WORKFLOW  # no secret is used at all
    for forbidden in ("deploy", "environment:", "ssh", "kubectl", "docker push", "registry"):
        assert forbidden not in WORKFLOW.lower().replace("pull_request", ""), forbidden


def test_runners_images_and_tools_are_pinned() -> None:
    assert "ubuntu-latest" not in WORKFLOW
    for image in re.findall(r"^\s+image:\s*(\S+)", WORKFLOW, re.M):
        assert DIGEST.search(image), f"service image {image} must be pinned by digest"
    assert re.search(r"image: postgres:16@sha256:", WORKFLOW)
    assert re.search(r"image: redis:7@sha256:", WORKFLOW)
    assert re.search(r"zricethezav/gitleaks:v8\.21\.2@sha256:[0-9a-f]{64}", WORKFLOW)
    assert re.search(r"uvx pip-audit==\d+\.\d+\.\d+ ", WORKFLOW)
    assert "latest" not in WORKFLOW


def test_toolchain_versions_match_the_project() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()
    uv = re.search(r'required-version = "==([\d.]+)"', pyproject)
    assert uv
    python = (ROOT / ".python-version").read_text().strip()
    assert re.findall(r'^\s+version: "([\d.]+)"', WORKFLOW, re.M) == [uv.group(1)] * 3
    assert re.findall(r'python-version: "([\d.]+)"', WORKFLOW) == [python] * 3
    assert "uv sync --locked" in WORKFLOW and "--locked" in WORKFLOW


def test_every_job_has_a_timeout_and_the_required_checks_exist() -> None:
    # F2-T01 added the identity job, the Keycloak security provider order the image scan
    assert len(re.findall(r"timeout-minutes:", WORKFLOW)) == 5
    for required in (
        "uv sync --locked",
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "pytest -q -ra --junitxml",
        "no skipped tests",
        "export_openapi --check",
        "./openapi/check-clients.sh",
        "gitleaks",
        "pip-audit",
        "test_upgrade_downgrade_upgrade_and_schema_contents",
        "Wait for PostgreSQL and Redis",
        "--health-cmd",
        "TEST_PG_ADMIN_URL",
        "TEST_REDIS_URL",
    ):
        assert required in WORKFLOW, required
    assert 'CI: "true"' in WORKFLOW  # a missing integration variable fails instead of skipping
    assert "ci-throwaway-password" in WORKFLOW  # disposable credentials only


def test_node_is_pinned_to_an_exact_version_and_clients_use_the_lockfile() -> None:
    assert re.search(r'node-version: "\d+\.\d+\.\d+"', WORKFLOW)  # R10: exact patch, not "20"
    engines = (ROOT / "openapi" / "toolchain" / "package.json").read_text()
    assert '"node": ">=20.19.0 <21"' in engines


def test_spec_validation_runs_independently_and_warnings_are_errors() -> None:
    assert "openapi-spec-validator openapi/openapi.json" in WORKFLOW  # R09
    assert "-W error" in WORKFLOW  # R15: no new warning can pass unnoticed
    allowed = re.findall(r"-W 'ignore:([^']+)'", WORKFLOW)
    assert set(allowed) == {"Using `httpx` with `starlette.testclient` is deprecated:Warning"}


def test_rate_limit_timing_regression_is_repeated_in_ci() -> None:
    assert re.search(
        r"for run in 1 2 3; do\s+uv run --locked pytest -q tests/test_ratelimit.py", WORKFLOW
    )
