"""KC-SP-12: the gate over the Trivy scan of the AutoTramita Keycloak image. No scanner needed:
synthetic reports and databases exercise every rule, the refusals above all (no false PASS)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.identity import scan_gate

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
IMAGE = "autotramita-keycloak:ci"


def cache(
    tmp: Path,
    *,
    vuln_age: timedelta = timedelta(hours=2),
    java_age: timedelta = timedelta(days=1),
    schemas: tuple[int, int] = (2, 1),
) -> Path:
    folder = tmp / "cache"
    for name, file, age, schema in (
        ("db", "trivy.db", vuln_age, schemas[0]),
        ("java-db", "trivy-java.db", java_age, schemas[1]),
    ):
        (folder / name).mkdir(parents=True)
        (folder / name / file).write_bytes(b"database")
        updated = (NOW - age).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
        meta = {"Version": schema, "UpdatedAt": updated, "DownloadedAt": updated}
        (folder / name / "metadata.json").write_text(json.dumps(meta))
    return folder


def report(tmp: Path, findings: list[tuple[str, str, str]] = (), **change: Any) -> Path:  # type: ignore[assignment]
    vulnerabilities = [
        {
            "VulnerabilityID": i,
            "PkgName": p,
            "Severity": s,
            "InstalledVersion": "1",
            "Status": "fixed",
        }
        for i, p, s in findings
    ]
    body: dict[str, Any] = {
        "SchemaVersion": 2,
        "Trivy": {"Version": scan_gate.SCANNER_VERSION},
        "Metadata": {"OS": {"Family": "redhat"}, "RepoTags": [f"atci-run-identity-{IMAGE}"]},
        "Results": [
            {
                "Target": "image (redhat 9.7)",
                "Class": "os-pkgs",
                "Type": "redhat",
                "Vulnerabilities": vulnerabilities,
            },
            {"Target": "Java", "Class": "lang-pkgs", "Type": "jar", "Vulnerabilities": []},
        ],
    }
    body.update(change)
    path = tmp / "report.json"
    path.write_text(json.dumps(body))
    return path


def accepted(tmp: Path, *entries: dict[str, Any]) -> Path:
    path = tmp / "acceptances.json"
    path.write_text(json.dumps({"acceptances": list(entries)}))
    return path


def run(
    tmp: Path, report_path: Path, cache_path: Path, acceptances: Path | None = None
) -> dict[str, Any]:
    return scan_gate.gate(report_path, cache_path, acceptances or accepted(tmp), IMAGE, now=NOW)


def test_a_fresh_scan_of_the_image_without_critical_or_high_findings_passes(tmp_path: Path) -> None:
    result = run(tmp_path, report(tmp_path, [("CVE-1", "libx", "MEDIUM")]), cache(tmp_path))
    assert result["gate"] == "PASS", result["reasons"]
    assert result["databases"]["vulnerabilities"]["sha256"]
    assert result["counts"] == {"os-pkgs:MEDIUM": 1}


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH"])
def test_a_critical_or_high_finding_blocks(tmp_path: Path, severity: str) -> None:
    result = run(tmp_path, report(tmp_path, [("CVE-1", "libx", severity)]), cache(tmp_path))
    assert result["gate"] == "FAIL" and [r["id"] for r in result["blocking"]] == ["CVE-1"]


def owner(**change: Any) -> dict[str, Any]:
    entry = {
        "id": "CVE-1",
        "package": "libx",
        "accepted_by": "owner",
        "decision": "owner order of 2026-11-30",
        "expires": (NOW.date() + timedelta(days=30)).isoformat(),
    }
    entry.update(change)
    return entry


def test_only_a_valid_time_limited_owner_acceptance_lets_a_finding_through(tmp_path: Path) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner()))
    assert result["gate"] == "PASS" and [r["id"] for r in result["accepted"]] == ["CVE-1"]


@pytest.mark.parametrize(
    "change",
    [
        {"accepted_by": "agent"},
        {"decision": " "},
        {"expires": (date(2026, 11, 24)).isoformat()},  # expired
        {"expires": (NOW.date() + timedelta(days=91)).isoformat()},  # too far ahead
        {"expires": "soon"},
        {"package": "liby"},  # another package: the finding stays unaccepted
    ],
    ids=["not_the_owner", "no_decision", "expired", "too_long", "bad_date", "other_package"],
)
def test_no_acceptance_can_be_made_up(tmp_path: Path, change: dict[str, Any]) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner(**change)))
    assert result["gate"] == "FAIL", result


def test_the_committed_acceptances_accept_nothing() -> None:
    committed = json.loads(
        (ROOT / "identity" / "keycloak" / "vulnerability-acceptances.json").read_text()
    )
    assert committed["acceptances"] == []


@pytest.mark.parametrize(
    ("ages", "schemas"),
    [
        ((timedelta(hours=49), timedelta(days=1)), (2, 1)),  # vulnerability database too old
        ((timedelta(hours=1), timedelta(days=8)), (2, 1)),  # Java database too old
        ((timedelta(hours=-3), timedelta(days=1)), (2, 1)),  # from the future
        ((timedelta(hours=1), timedelta(days=1)), (3, 1)),  # another schema
    ],
    ids=["old_vulnerability_db", "old_java_db", "future", "schema"],
)
def test_an_old_or_unknown_database_is_never_a_pass(
    tmp_path: Path, ages: tuple[timedelta, timedelta], schemas: tuple[int, int]
) -> None:
    folder = cache(tmp_path, vuln_age=ages[0], java_age=ages[1], schemas=schemas)
    assert run(tmp_path, report(tmp_path), folder)["gate"] == "FAIL"


def test_a_missing_database_or_report_is_never_a_pass(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run(tmp_path, report(tmp_path), empty)["gate"] == "FAIL"
    databases = cache(tmp_path)
    assert run(tmp_path, tmp_path / "missing.json", databases)["gate"] == "FAIL"
    (tmp_path / "broken.json").write_text("{")
    assert run(tmp_path, tmp_path / "broken.json", databases)["gate"] == "FAIL"


@pytest.mark.parametrize(
    "change",
    [
        {"SchemaVersion": 1},
        {"Trivy": {"Version": "0.50.0"}},
        {"Metadata": {"OS": {"Family": "redhat"}, "RepoTags": ["other:1"]}},
        {"Metadata": {"RepoTags": [IMAGE]}},  # no operating system detected
        {"Results": [{"Target": "x", "Class": "os-pkgs", "Type": "redhat"}]},  # no Java
    ],
    ids=["schema", "scanner", "other_image", "no_os", "no_java"],
)
def test_a_report_of_something_else_or_of_less_is_never_a_pass(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    assert run(tmp_path, report(tmp_path, **change), cache(tmp_path))["gate"] == "FAIL"


def test_the_command_line_exits_non_zero_and_writes_the_summary(tmp_path: Path) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "CRITICAL")])
    summary = tmp_path / "summary.json"
    code = scan_gate.main(
        ["--report", str(findings), "--cache", str(cache(tmp_path)), "--image", IMAGE,
         "--acceptances", str(accepted(tmp_path)), "--summary", str(summary)]
    )  # fmt: skip
    assert code == 1
    assert json.loads(summary.read_text())["gate"] == "FAIL"
