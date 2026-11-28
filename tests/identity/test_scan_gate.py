"""KC-SP-12 and PROD-SEC-01 (D49): the gate over the Trivy scan of the AutoTramita Keycloak image.
No scanner needed: synthetic reports, databases and image archives exercise every rule, the
refusals above all (no false PASS). The tests marked "fail-open" are the cases the gate before
D49 (``3fd4e4a``) let through; the implementation record shows them failing against it."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.identity import scan_gate

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
IMAGE = "autotramita-keycloak:ci"
LOCAL_TAG = f"atci-20261125-120000-0a1b2c-image-scan-{IMAGE}"  # Local CI's form of the tag
CONFIG = b'{"architecture":"amd64","os":"linux","rootfs":{"type":"layers","diff_ids":[]}}'
IMAGE_ID = f"sha256:{hashlib.sha256(CONFIG).hexdigest()}"
LEVEL = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
DROP = object()  # a field the finding does not carry


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


def finding(
    cve: str,
    package: str,
    severity: Any,
    *,
    installed: str = "1",
    fixed: str | None = None,
    source: str = "redhat",
    **change: Any,
) -> dict[str, Any]:
    """A finding as Trivy writes it: the severity, its source and the vendor ratings agree."""
    body: dict[str, Any] = {
        "VulnerabilityID": cve,
        "PkgName": package,
        "InstalledVersion": installed,
        "Status": "affected" if fixed is None else "fixed",
        "Severity": severity,
        "SeveritySource": source,
        "VendorSeverity": {source: LEVEL.get(severity, 0), "nvd": 4},
    }
    if fixed is not None:
        body["FixedVersion"] = fixed
    for key, value in change.items():
        if value is DROP:
            body.pop(key, None)
        else:
            body[key] = value
    return body


def _findings(items: Any) -> list[dict[str, Any]]:
    return [item if isinstance(item, dict) else finding(*item) for item in items]


def report(
    tmp: Path,
    findings: Any = (),
    java: Any = (),
    *,
    tags: list[str] | None = None,
    image_id: str = IMAGE_ID,
    **change: Any,
) -> Path:
    body: dict[str, Any] = {
        "SchemaVersion": 2,
        "Trivy": {"Version": scan_gate.SCANNER_VERSION},
        "Metadata": {
            "OS": {"Family": "redhat"},
            "ImageID": image_id,
            "RepoTags": [IMAGE] if tags is None else tags,
        },
        "Results": [
            {
                "Target": "image (redhat 9.7)",
                "Class": "os-pkgs",
                "Type": "redhat",
                "Vulnerabilities": _findings(findings),
            },
            {
                "Target": "Java",
                "Class": "lang-pkgs",
                "Type": "jar",
                "Vulnerabilities": _findings(java),
            },
        ],
    }
    body.update(change)
    path = tmp / "report.json"
    path.write_text(json.dumps(body))
    return path


def saved(
    tmp: Path,
    *,
    tags: list[str] | None = None,
    config: bytes = CONFIG,
    images: int = 1,
    name: str = "image.tar",
) -> Path:
    """An image archive as ``docker save`` writes it (OCI layout with a Docker manifest)."""
    path = tmp / name
    blob = f"blobs/sha256/{hashlib.sha256(config).hexdigest()}"
    manifest = [{"Config": blob, "RepoTags": [IMAGE] if tags is None else tags, "Layers": []}]
    with tarfile.open(path, "w") as tar:
        for member, data in (("manifest.json", json.dumps(manifest * images).encode()),
                             (blob, config)):  # fmt: skip
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def accepted(tmp: Path, *entries: Any) -> Path:
    path = tmp / "acceptances.json"
    path.write_text(json.dumps({"acceptances": list(entries)}))
    return path


def run(
    tmp: Path,
    report_path: Path,
    cache_path: Path,
    acceptances: Path | None = None,
    archive: Path | None = None,
) -> dict[str, Any]:
    return scan_gate.gate(
        report_path, cache_path, acceptances or accepted(tmp), IMAGE, archive or saved(tmp),
        now=NOW,
    )  # fmt: skip


def owner(**change: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "CVE-1",
        "package": "libx",
        "severity": "HIGH",
        "installed": "1",
        "fixed": None,
        "accepted_by": "owner",
        "decision": "owner order of 2026-11-30",
        "expires": (NOW.date() + timedelta(days=30)).isoformat(),
    }
    for key, value in change.items():
        if value is DROP:
            entry.pop(key)
        else:
            entry[key] = value
    return entry


def test_a_fresh_scan_of_the_image_without_critical_or_high_findings_passes(tmp_path: Path) -> None:
    result = run(tmp_path, report(tmp_path, [("CVE-1", "libx", "MEDIUM")]), cache(tmp_path))
    assert result["gate"] == "PASS", result["reasons"]
    assert result["databases"]["vulnerabilities"]["sha256"]
    assert result["counts"] == {"os-pkgs:MEDIUM": 1}
    assert result["image"]["image_id"] == result["archive"]["config_digest"] == IMAGE_ID


@pytest.mark.parametrize("severity", ["CRITICAL", "HIGH"])
def test_a_critical_or_high_finding_blocks(tmp_path: Path, severity: str) -> None:
    result = run(tmp_path, report(tmp_path, [("CVE-1", "libx", severity)]), cache(tmp_path))
    assert result["gate"] == "FAIL" and [r["id"] for r in result["blocking"]] == ["CVE-1"]


def test_only_a_valid_time_limited_owner_acceptance_lets_a_finding_through(tmp_path: Path) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner()))
    assert result["gate"] == "PASS" and [r["id"] for r in result["accepted"]] == ["CVE-1"]


def test_an_acceptance_binds_a_fix_exactly(tmp_path: Path) -> None:
    findings = report(tmp_path, [finding("CVE-1", "libx", "HIGH", fixed="2")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner(fixed="2")))
    assert result["gate"] == "PASS", result["reasons"]


@pytest.mark.parametrize(
    "change",
    [
        {"accepted_by": "agent"},
        {"decision": " "},
        {"expires": (date(2026, 11, 24)).isoformat()},  # expired
        {"expires": (NOW.date() + timedelta(days=91)).isoformat()},  # too far ahead
        {"expires": "soon"},
        {"package": "liby"},  # another package: the finding stays unaccepted
        # PS-AC-01: the severity it was accepted at; only HIGH can be accepted
        {"severity": DROP},
        {"severity": None},
        {"severity": "UNKNOWN"},
        {"severity": "high"},
        {"severity": "CRITICAL"},
        {"severity": "MEDIUM"},
        # PS-AC-04: the exact installed version and fix state, both recorded
        {"installed": DROP},
        {"installed": ""},
        {"installed": 1},
        {"fixed": DROP},  # absent is not "no fix": null must be written
        {"fixed": ""},
        {"fixed": 2},
        {"id": ["CVE-1"]},
    ],
    ids=["not_the_owner", "no_decision", "expired", "too_long", "bad_date", "other_package",
         "no_severity", "null_severity", "unknown_severity", "lowercase_severity",
         "critical_acceptance", "medium_acceptance", "no_installed", "empty_installed",
         "numeric_installed", "no_fixed", "empty_fixed", "numeric_fixed", "malformed_id"],
)  # fmt: skip
def test_no_acceptance_can_be_made_up(tmp_path: Path, change: dict[str, Any]) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner(**change)))
    assert result["gate"] == "FAIL", result
    assert result["accepted"] == [], result


@pytest.mark.parametrize(
    "entries",
    [
        [owner(), owner()],  # fail-open: the second copy silently replaced the first
        [owner(), owner(expires=(NOW.date() + timedelta(days=60)).isoformat())],
        [owner(), owner(installed="2")],
    ],
    ids=["identical", "other_expiry", "other_version"],
)
def test_an_acceptance_listed_twice_is_refused_with_every_copy(
    tmp_path: Path, entries: list[dict[str, Any]]
) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, *entries))
    assert result["gate"] == "FAIL" and result["accepted"] == [], result
    assert any("listed 2 times" in reason for reason in result["reasons"]), result["reasons"]


# --- PS-AC-02: severity binding and the authoritative vendor (D49 Q1) -----------------------------
@pytest.mark.parametrize(
    "reported",
    [
        # fail-open: an accepted HIGH finding reported CRITICAL passed
        finding("CVE-1", "libx", "CRITICAL"),
        # fail-open: an accepted finding with severity UNKNOWN passed (skipped as not blocking)
        finding("CVE-1", "libx", "UNKNOWN"),
        finding("CVE-1", "libx", None),
        finding("CVE-1", "libx", "HIGH", SeveritySource="nvd"),
        finding("CVE-1", "libx", "HIGH", SeveritySource=DROP),
        finding("CVE-1", "libx", "HIGH", VendorSeverity={"redhat": 4}),
        finding("CVE-1", "libx", "HIGH", VendorSeverity=DROP),
    ],
    ids=["escalated_to_critical", "unknown", "null", "foreign_source", "no_source",
         "vendor_critical", "no_vendor_rating"],
)  # fmt: skip
def test_an_accepted_finding_passes_only_at_its_accepted_and_consistent_severity(
    tmp_path: Path, reported: dict[str, Any]
) -> None:
    result = run(
        tmp_path, report(tmp_path, [reported]), cache(tmp_path), accepted(tmp_path, owner())
    )
    assert result["gate"] == "FAIL" and [r["id"] for r in result["blocking"]] == ["CVE-1"], result
    assert result["accepted"] == []


def test_a_critical_finding_names_why_it_cannot_be_accepted(tmp_path: Path) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "CRITICAL")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner()))
    assert result["blocking"][0]["problem"] == "CRITICAL cannot be accepted"


@pytest.mark.parametrize(
    "reported",
    [
        # fail-open: a new finding without a severity was not counted at all
        finding("CVE-9", "liby", "HIGH", Severity=DROP),
        finding("CVE-9", "liby", ""),
        finding("CVE-9", "liby", "UNKNOWN"),
        finding("CVE-9", "liby", "SEVERE"),
        # fail-open: Trivy MEDIUM while the authoritative vendor says CRITICAL
        finding("CVE-9", "liby", "MEDIUM", VendorSeverity={"redhat": 4}),
        finding("CVE-9", "liby", "LOW", VendorSeverity={"redhat": 0}),
        finding("CVE-9", "liby", "LOW", VendorSeverity={"redhat": "1"}),
        finding("CVE-9", "liby", "LOW", VendorSeverity={"redhat": True}),
        finding("CVE-9", "liby", "LOW", VendorSeverity={"redhat": 9}),
        finding("CVE-9", "liby", "LOW", VendorSeverity=[1]),
        finding("CVE-9", "liby", "LOW", VendorSeverity={"ghsa": 1}),  # not the OS vendor
        finding("CVE-9", "liby", "LOW", source="ghsa"),
        finding("CVE-9", "liby", "LOW", source="nvd"),
        finding("CVE-9", "liby", "LOW", VulnerabilityID=DROP),
        finding("CVE-9", "liby", "LOW", PkgName=""),
        finding("CVE-9", "liby", "LOW", InstalledVersion=DROP),
        finding("CVE-9", "liby", "LOW", FixedVersion=3),
    ],
    ids=["no_severity", "empty", "unknown", "made_up", "scanner_below_vendor", "vendor_unknown",
         "vendor_text", "vendor_bool", "vendor_out_of_range", "vendor_not_a_map",
         "other_vendor_only", "java_vendor_on_os", "nvd_source", "no_id", "no_package",
         "no_installed", "malformed_fix"],
)  # fmt: skip
def test_missing_unknown_malformed_or_inconsistent_severity_fails_on_every_finding(
    tmp_path: Path, reported: dict[str, Any]
) -> None:
    result = run(tmp_path, report(tmp_path, [reported]), cache(tmp_path))
    assert result["gate"] == "FAIL" and len(result["blocking"]) == 1, result
    assert result["blocking"][0]["problem"], result


def test_java_findings_are_rated_by_ghsa_and_os_findings_by_red_hat(tmp_path: Path) -> None:
    good = report(
        tmp_path,
        [finding("CVE-1", "libx", "LOW")],
        [finding("CVE-2", "org.x:y", "MEDIUM", source="ghsa")],
    )
    databases = cache(tmp_path)
    assert run(tmp_path, good, databases)["gate"] == "PASS"
    swapped = report(tmp_path, [], [finding("CVE-2", "org.x:y", "MEDIUM")])  # source redhat
    assert run(tmp_path, swapped, databases)["gate"] == "FAIL"


def test_a_finding_in_a_result_without_an_authoritative_vendor_fails(tmp_path: Path) -> None:
    other = {
        "Target": "usr/bin/tool",
        "Class": "lang-pkgs",
        "Type": "gobinary",
        "Vulnerabilities": [finding("CVE-3", "golang.org/x/net", "LOW", source="ghsa")],
    }
    path = report(tmp_path)
    body = json.loads(path.read_text())
    body["Results"].append(other)
    path.write_text(json.dumps(body))
    result = run(tmp_path, path, cache(tmp_path))
    assert result["gate"] == "FAIL", result
    assert "no authoritative vendor" in result["blocking"][0]["problem"]


@pytest.mark.parametrize(
    "results",
    [
        [{"Class": "os-pkgs", "Type": "redhat", "Vulnerabilities": {"x": 1}},
         {"Class": "lang-pkgs", "Type": "jar"}],
        [{"Class": "os-pkgs", "Type": "redhat", "Vulnerabilities": ["CVE-1"]},
         {"Class": "lang-pkgs", "Type": "jar"}],
        ["os-pkgs"],
        {"Class": "os-pkgs"},
    ],
    ids=["findings_not_a_list", "finding_not_an_object", "result_not_an_object",
         "results_not_a_list"],
)  # fmt: skip
def test_a_malformed_report_is_never_a_pass(tmp_path: Path, results: Any) -> None:
    result = run(tmp_path, report(tmp_path, Results=results), cache(tmp_path))
    assert result["gate"] == "FAIL", result


# --- PS-AC-04: installed version and fix state (D49 Q2) -------------------------------------------
@pytest.mark.parametrize(
    ("reported", "entry"),
    [
        # fail-open: the acceptance survived a change of the installed version
        (finding("CVE-1", "libx", "HIGH", installed="2"), owner()),
        (finding("CVE-1", "libx", "HIGH", fixed="2"), owner()),  # a fix appears
        (finding("CVE-1", "libx", "HIGH", fixed="3"), owner(fixed="2")),  # another fix
        (finding("CVE-1", "libx", "HIGH"), owner(fixed="2")),  # the fix disappears
        (finding("CVE-1", "libx", "HIGH", installed="1.0"), owner()),  # no loose comparison
    ],
    ids=["other_installed", "fix_appears", "other_fix", "fix_withdrawn", "not_exact"],
)
def test_an_acceptance_does_not_survive_a_change_of_version_or_fix(
    tmp_path: Path, reported: dict[str, Any], entry: dict[str, Any]
) -> None:
    result = run(tmp_path, report(tmp_path, [reported]), cache(tmp_path), accepted(tmp_path, entry))
    assert result["gate"] == "FAIL" and result["accepted"] == [], result
    assert "accepted for installed" in result["blocking"][0]["problem"]


def test_an_empty_fixed_version_reads_as_no_fix(tmp_path: Path) -> None:
    findings = report(tmp_path, [finding("CVE-1", "libx", "HIGH", FixedVersion="")])
    result = run(tmp_path, findings, cache(tmp_path), accepted(tmp_path, owner()))
    assert result["gate"] == "PASS", result["reasons"]


# The owner's time-limited acceptances of 2026-11-25 (commit cfbc8f7, recorded in the F2
# decision register), with the severity, installed version and fix state the owner added under
# D49 (2026-11-28): exactly these, with exactly these expiry dates. Any other entry, an
# extended date, another value or a second copy is an acceptance nobody authorized.
AUTHORIZED = {
    ("CVE-2026-102554", "com.google.guava:guava"): ("2026-12-31", "HIGH", "33.6.0-jre", "33.7.2"),
    ("CVE-2026-91403", "java-21-openjdk-headless"): (
        "2027-02-22", "HIGH", "1:21.0.13.1.2-1.2.el9", None,
    ),
    ("CVE-2026-119373", "sqlite-libs"): ("2027-02-22", "HIGH", "3.34.1-11.el9_8", None),
    ("CVE-2026-119374", "sqlite-libs"): ("2027-02-22", "HIGH", "3.34.1-11.el9_8", None),
    ("CVE-2026-119379", "sqlite-libs"): ("2027-02-22", "HIGH", "3.34.1-11.el9_8", None),
    ("CVE-2026-119586", "sqlite-libs"): ("2027-02-22", "HIGH", "3.34.1-11.el9_8", None),
}  # fmt: skip
JAVA = {"com.google.guava:guava"}
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
    assert {
        (e["id"], e["package"]): (e["expires"], e["severity"], e["installed"], e["fixed"])
        for e in entries
    } == AUTHORIZED
    for entry in entries:
        assert set(entry) == {*scan_gate.ACCEPTANCE_FIELDS, "reason"}, entry
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
        assert findings[key]["severity"] == "HIGH" == entry["severity"], entry
        assert findings[key]["installed"] == entry["installed"], entry
        assert date.fromisoformat(entry["expires"]) <= date.fromisoformat(
            findings[key]["recommended_expiry"]
        ), entry
        assert entry["expires"] == proposed[key], entry


def committed_findings(tmp: Path, *extra: dict[str, Any], **change: Any) -> Path:
    """The scan of 2026-11-25/28: the six accepted findings exactly as Trivy reports them."""
    os_rows: list[dict[str, Any]] = []
    java_rows: list[dict[str, Any]] = []
    for (cve, package), (_, severity, installed, fixed) in AUTHORIZED.items():
        source = "ghsa" if package in JAVA else "redhat"
        row = finding(cve, package, severity, installed=installed, fixed=fixed, source=source)
        (java_rows if package in JAVA else os_rows).append(row)
    return report(tmp, [*os_rows, *extra], java_rows, **change)


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
        committed_findings(tmp_path), cache(tmp_path, at=moment), COMMITTED, IMAGE,
        saved(tmp_path), now=moment,
    )  # fmt: skip
    assert sorted(str(r["id"]) for r in result["blocking"]) == expired, result
    assert result["gate"] == ("FAIL" if expired else "PASS"), result
    if expired:
        assert any("invalid or expired entry" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "extra",
    [
        finding("CVE-2026-0001", "sqlite-libs", "HIGH", installed="3.34.1-11.el9_8"),
        finding("CVE-2026-102554", "com.example:other", "HIGH"),  # accepted id, other package
        finding("CVE-2026-0002", "com.google.guava:guava", "CRITICAL"),
        # the same accepted finding in a second copy of the package at another version
        finding("CVE-2026-119373", "sqlite-libs", "HIGH", installed="3.34.1-12.el9_8"),
    ],
    ids=["other_finding", "other_package", "critical_in_accepted_package", "second_version"],
)
def test_the_committed_acceptances_let_nothing_else_through(
    tmp_path: Path, extra: dict[str, Any]
) -> None:
    result = run(tmp_path, committed_findings(tmp_path, extra), cache(tmp_path), COMMITTED)
    blocked = [(r["id"], r["package"]) for r in result["blocking"]]
    assert result["gate"] == "FAIL" and blocked == [(extra["VulnerabilityID"], extra["PkgName"])]
    assert len(result["accepted"]) == len(AUTHORIZED)


@pytest.mark.parametrize(
    ("cve", "change"),
    [
        ("CVE-2026-91403", {"Severity": "CRITICAL", "VendorSeverity": {"redhat": 4}}),
        ("CVE-2026-91403", {"InstalledVersion": "1:21.0.14.0.7-1.el9"}),
        ("CVE-2026-119373", {"FixedVersion": "3.34.1-12.el9_8"}),
        ("CVE-2026-102554", {"FixedVersion": "33.7.3"}),
        ("CVE-2026-102554", {"InstalledVersion": "33.7.2-jre"}),
    ],
    ids=["91403_escalated", "openjdk_updated", "sqlite_fix_appears", "guava_other_fix",
         "guava_updated"],
)  # fmt: skip
def test_a_change_to_a_committed_finding_invalidates_its_acceptance(
    tmp_path: Path, cve: str, change: dict[str, Any]
) -> None:
    path = committed_findings(tmp_path)
    body = json.loads(path.read_text())
    for result in body["Results"]:
        for row in result["Vulnerabilities"]:
            if row["VulnerabilityID"] == cve:
                row.update(change)
    path.write_text(json.dumps(body))
    result = run(tmp_path, path, cache(tmp_path), COMMITTED)
    assert result["gate"] == "FAIL" and [r["id"] for r in result["blocking"]] == [cve], result


# --- PS-AC-05: the image is bound by exact tag and by the saved archive ---------------------------
@pytest.mark.parametrize("tag", [IMAGE, LOCAL_TAG])
def test_the_image_of_github_and_of_local_ci_passes_by_its_exact_tag(
    tmp_path: Path, tag: str
) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "LOW")], tags=[tag])
    result = run(tmp_path, findings, cache(tmp_path), archive=saved(tmp_path, tags=[tag]))
    assert result["gate"] == "PASS", result["reasons"]


@pytest.mark.parametrize(
    "tags",
    [
        ["evil-autotramita-keycloak:ci"],  # fail-open: the tag merely ended in the name
        [f"x{LOCAL_TAG}"],
        ["atci-run-identity-autotramita-keycloak:ci"],
        [LOCAL_TAG.replace("image-scan", "identity")],  # the image of another job
        [LOCAL_TAG.replace("0a1b2c", "0a1b2")],
        [f"{IMAGE}-old"],
        [f"docker.io/library/{IMAGE}"],
        [IMAGE, "other:1"],  # one archive, two images' names
        [],
        ["autotramita-keycloak:latest"],
    ],
    ids=["suffix_match", "prefixed_local_form", "loose_local_form", "other_job", "bad_run_id",
         "longer_tag", "registry_form", "two_tags", "no_tag", "other_tag"],
)  # fmt: skip
def test_an_image_whose_tag_is_not_exactly_the_expected_one_fails(
    tmp_path: Path, tags: list[str]
) -> None:
    findings = report(tmp_path, tags=tags)
    result = run(tmp_path, findings, cache(tmp_path), archive=saved(tmp_path, tags=tags))
    assert result["gate"] == "FAIL", result
    assert any("not exactly the image" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    ("image_id", "archive"),
    [
        (f"sha256:{hashlib.sha256(b'other').hexdigest()}", {}),  # the report of another image
        (IMAGE_ID, {"config": b"{}"}),  # the archive of another image
        ("", {}),
        (IMAGE_ID.removeprefix("sha256:"), {}),
        (IMAGE_ID, {"tags": [LOCAL_TAG]}),  # the archive names another tag than the report
    ],
    ids=["other_report", "other_archive", "no_image_id", "bare_digest", "other_archive_tag"],
)
def test_a_report_of_another_image_than_the_saved_archive_fails(
    tmp_path: Path, image_id: str, archive: dict[str, Any]
) -> None:
    path = report(tmp_path, image_id=image_id)
    result = run(tmp_path, path, cache(tmp_path), archive=saved(tmp_path, **archive))
    assert result["gate"] == "FAIL", result


@pytest.mark.parametrize("kind", ["missing", "not_a_tar", "empty_tar", "two_images", "no_config"])
def test_a_missing_or_unreadable_archive_is_never_a_pass(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "image.tar"
    if kind == "not_a_tar":
        archive.write_bytes(b"not a tar")
    elif kind == "empty_tar":
        with tarfile.open(archive, "w"):
            pass
    elif kind == "two_images":
        saved(tmp_path, images=2)
    elif kind == "no_config":
        saved(tmp_path)
        with tarfile.open(archive) as tar:
            manifest = tar.extractfile("manifest.json").read()  # type: ignore[union-attr]
        with tarfile.open(archive, "w") as tar:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            tar.addfile(info, io.BytesIO(manifest))
    result = run(tmp_path, report(tmp_path), cache(tmp_path), archive=archive)
    assert result["gate"] == "FAIL" and not result["archive"]["present"], result
    assert any(reason.startswith("archive:") for reason in result["reasons"])


# --- freshness and completeness of the scan (unchanged rules) -------------------------------------
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
        {"Metadata": {"OS": {"Family": "redhat"}, "ImageID": IMAGE_ID, "RepoTags": ["other:1"]}},
        {"Metadata": {"ImageID": IMAGE_ID, "RepoTags": [IMAGE]}},  # no operating system detected
        {"Results": [{"Target": "x", "Class": "os-pkgs", "Type": "redhat"}]},  # no Java
    ],
    ids=["schema", "scanner", "other_image", "no_os", "no_java"],
)
def test_a_report_of_something_else_or_of_less_is_never_a_pass(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    assert run(tmp_path, report(tmp_path, **change), cache(tmp_path))["gate"] == "FAIL"


# --- PS-AC-06: the whole summary goes into the job log -------------------------------------------
def gate_command(tmp: Path, findings: Path, acceptances: Path, summary: Path) -> list[str]:
    """The command line runs on the real clock: databases fresh as of now."""
    databases = cache(tmp, at=datetime.now(UTC))
    return [
        *("--report", str(findings), "--archive", str(saved(tmp)), "--cache", str(databases)),
        *("--image", IMAGE, "--acceptances", str(acceptances), "--summary", str(summary)),
    ]


def test_the_command_line_exits_non_zero_and_writes_the_summary(tmp_path: Path) -> None:
    findings = report(tmp_path, [("CVE-1", "libx", "CRITICAL")])
    summary = tmp_path / "summary.json"
    code = scan_gate.main(gate_command(tmp_path, findings, accepted(tmp_path), summary))
    assert code == 1
    assert json.loads(summary.read_text())["gate"] == "FAIL"


def test_the_log_holds_the_whole_summary_with_the_accepted_findings_and_the_image(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AT_SECRET_PROBE", "s3cr3t-value")
    findings = report(tmp_path, [("CVE-1", "libx", "HIGH")])
    summary = tmp_path / "summary.json"
    expires = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    acceptances = accepted(tmp_path, owner(expires=expires))
    code = scan_gate.main(gate_command(tmp_path, findings, acceptances, summary))
    out = capsys.readouterr().out
    assert code == 0 and out.rstrip().endswith("scan gate: PASS")
    logged = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert logged == json.loads(summary.read_text())
    assert [(r["id"], r["installed"], r["severity"]) for r in logged["accepted"]] == [
        ("CVE-1", "1", "HIGH")
    ]
    assert logged["image"]["image_id"] == logged["archive"]["config_digest"] == IMAGE_ID
    assert re.fullmatch(r"[0-9a-f]{64}", logged["archive"]["sha256"])
    assert (
        logged["inputs"]["acceptances_sha256"]
        == hashlib.sha256(acceptances.read_bytes()).hexdigest()
    )
    assert logged["inputs"]["report_sha256"] == hashlib.sha256(findings.read_bytes()).hexdigest()
    assert "s3cr3t-value" not in out  # the gate reads no environment


def test_the_ci_gate_step_scans_and_binds_the_archive_it_saved() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = ci.split("\n  image-scan:\n")[1]
    saved_to = re.search(r'docker save --output "([^"]+)" autotramita-keycloak:ci', job)
    scanned = re.search(r'-v "([^"]+):/image\.tar:ro"', job)
    bound = re.search(r'--archive "([^"]+)"', job)
    assert saved_to and scanned and bound
    assert saved_to.group(1) == scanned.group(1) == bound.group(1)
    assert "--image autotramita-keycloak:ci" in job
