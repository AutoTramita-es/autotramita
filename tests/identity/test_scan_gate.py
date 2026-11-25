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
    at: datetime = NOW,
) -> Path:
    folder = tmp / "cache"
    for name, file, age, schema in (
        ("db", "trivy.db", vuln_age, schemas[0]),
        ("java-db", "trivy-java.db", java_age, schemas[1]),
    ):
        (folder / name).mkdir(parents=True)
        (folder / name / file).write_bytes(b"database")
        updated = (at - age).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
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


# The owner's time-limited acceptances of 2026-11-25 (commit cfbc8f7, recorded in the F2
# decision register): exactly these finding/package pairs, with exactly these expiry dates.
# Any other entry, an extended date or a second copy is an acceptance nobody authorized.
AUTHORIZED = {
    ("CVE-2026-102554", "com.google.guava:guava"): "2026-12-31",
    ("CVE-2026-91403", "java-21-openjdk-headless"): "2027-02-22",
    ("CVE-2026-119373", "sqlite-libs"): "2027-02-22",
    ("CVE-2026-119374", "sqlite-libs"): "2027-02-22",
    ("CVE-2026-119379", "sqlite-libs"): "2027-02-22",
    ("CVE-2026-119586", "sqlite-libs"): "2027-02-22",
}
OWNER_DECISION = "owner authorization 2026-11-25"
REVIEW = ROOT / "identity" / "keycloak" / "vulnerability-review-26.8.2.json"
COMMITTED = ROOT / "identity" / "keycloak" / "vulnerability-acceptances.json"


def committed_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(COMMITTED.read_text())["acceptances"]
    return entries


def test_the_committed_acceptances_are_exactly_the_authorized_ones() -> None:
    entries = committed_entries()
    pairs = [(entry["id"], entry["package"]) for entry in entries]
    assert len(pairs) == len(set(pairs)), "an acceptance is listed twice"
    assert {(e["id"], e["package"]): e["expires"] for e in entries} == AUTHORIZED
    for entry in entries:
        assert entry["accepted_by"] == "owner", entry
        assert OWNER_DECISION in entry["decision"], entry
        assert REVIEW.name in entry["decision"], entry  # the analysis it rests on
        assert str(entry.get("reason", "")).strip(), entry


def test_every_committed_acceptance_rests_on_the_review_and_its_dates() -> None:
    review = json.loads(REVIEW.read_text())
    findings = {(f["id"], f["package"]): f for f in review["findings"]}
    proposed = {
        (p["id"], p["package"]): p["expires"]
        for p in review["proposed_acceptances_for_the_owner"]["entries"]
    }
    for entry in committed_entries():
        key = (entry["id"], entry["package"])
        assert key in findings and key in proposed, entry
        assert findings[key]["severity"] == "HIGH", entry  # nothing CRITICAL is accepted
        assert date.fromisoformat(entry["expires"]) <= date.fromisoformat(
            findings[key]["recommended_expiry"]
        ), entry
        assert entry["expires"] == proposed[key], entry


def committed_findings(tmp: Path, *extra: tuple[str, str, str]) -> Path:
    six = [(cve, package, "HIGH") for cve, package in AUTHORIZED]
    return report(tmp, [*six, *extra])


@pytest.mark.parametrize(
    ("moment", "expired"),
    [
        (NOW, []),
        (datetime(2026, 12, 31, 23, 0, tzinfo=UTC), []),  # the last day still counts
        (datetime(2027, 1, 1, 0, 30, tzinfo=UTC), ["CVE-2026-102554"]),
        (
            datetime(2027, 2, 23, 0, 30, tzinfo=UTC),
            sorted(cve for cve, _ in AUTHORIZED),
        ),
    ],
    ids=["today", "last_day_of_guava", "guava_expired", "all_expired"],
)
def test_the_committed_acceptances_pass_their_findings_only_until_they_expire(
    tmp_path: Path, moment: datetime, expired: list[str]
) -> None:
    result = scan_gate.gate(
        committed_findings(tmp_path), cache(tmp_path, at=moment), COMMITTED, IMAGE, now=moment
    )
    assert sorted(str(r["id"]) for r in result["blocking"]) == expired, result
    assert result["gate"] == ("FAIL" if expired else "PASS"), result
    if expired:
        assert any("invalid or expired entry" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "extra",
    [
        ("CVE-2026-0001", "sqlite-libs", "HIGH"),  # another finding of an accepted package
        ("CVE-2026-102554", "com.example:other", "HIGH"),  # the accepted id in another package
        ("CVE-2026-0002", "com.google.guava:guava", "CRITICAL"),
    ],
    ids=["other_finding", "other_package", "critical_in_accepted_package"],
)
def test_the_committed_acceptances_let_nothing_else_through(
    tmp_path: Path, extra: tuple[str, str, str]
) -> None:
    result = scan_gate.gate(
        committed_findings(tmp_path, extra), cache(tmp_path), COMMITTED, IMAGE, now=NOW
    )
    blocked = [(r["id"], r["package"]) for r in result["blocking"]]
    assert result["gate"] == "FAIL" and blocked == [extra[:2]], result
    assert len(result["accepted"]) == len(AUTHORIZED)


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
