"""The gate over the Trivy scan of the AutoTramita Keycloak image (KC-SP-12). Standard library
only and Python 3.10 or later, so it runs the same way in Local CI and on GitHub.

It fails (exit 1) unless every one of these holds:

* the vulnerability database (schema 2) is at most ``MAX_VULN_DB_AGE`` old and the Java
  database (schema 1) at most ``MAX_JAVA_DB_AGE`` (measured from their ``UpdatedAt``); a
  missing, unreadable or older database is never a pass;
* the report is a Trivy schema-2 report of the image built by this job, by the pinned scanner
  version, and it covers the operating-system packages **and** the Java components;
* no CRITICAL or HIGH finding is left without an acceptance by the owner. There are no automatic
  exceptions: an acceptance names the finding (id and package), ``accepted_by: "owner"``, the
  decision that accepted it and an expiry at most ``MAX_ACCEPTANCE_DAYS`` ahead.

It writes a machine-readable summary (``--summary``) and prints the blocking findings."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_VULN_DB_AGE = timedelta(hours=48)  # Trivy publishes this database every six hours
MAX_JAVA_DB_AGE = timedelta(days=7)  # and this one about every three days
MAX_ACCEPTANCE_DAYS = 90
BLOCKING = ("CRITICAL", "HIGH")
SCANNER_VERSION = "0.76.2"


def _moment(text: str) -> datetime:
    """Trivy writes nanoseconds; Python reads microseconds."""
    head, _, rest = text.rstrip("Z").partition(".")
    fraction = (rest or "0")[:6]
    return datetime.fromisoformat(f"{head}.{fraction}").replace(tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def database(cache: Path, name: str, file: str, version: int, limit: timedelta, now: datetime,
             reasons: list[str]) -> dict[str, Any]:  # fmt: skip
    folder = cache / name
    try:
        meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        updated = _moment(str(meta["UpdatedAt"]))
        found_version = meta["Version"]
        identity = _sha256(folder / file)
    except (OSError, ValueError, KeyError, TypeError) as error:
        reasons.append(f"{name}: database missing or unreadable ({type(error).__name__})")
        return {"present": False}
    age = now - updated
    if found_version != version:
        reasons.append(f"{name}: schema {found_version}, expected {version}")
    if age > limit or age < -timedelta(hours=1):
        reasons.append(
            f"{name}: updated {updated.isoformat()}, older than {limit} (or in the future)"
        )
    return {
        "present": True,
        "schema": found_version,
        "updated_at": updated.isoformat(),
        "downloaded_at": meta.get("DownloadedAt"),
        "age_hours": round(age.total_seconds() / 3600, 1),
        "max_age_hours": limit.total_seconds() / 3600,
        "sha256": identity,
    }


def acceptances(
    path: Path, today: date, reasons: list[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["acceptances"]
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("acceptances: file missing or unreadable")
        return {}
    valid: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries if isinstance(entries, list) else []:
        try:
            expires = date.fromisoformat(str(entry["expires"]))
            key = (str(entry["id"]), str(entry["package"]))
            ok = (
                entry.get("accepted_by") == "owner"
                and str(entry.get("decision", "")).strip()
                and today <= expires <= today + timedelta(days=MAX_ACCEPTANCE_DAYS)
            )
        except (KeyError, ValueError, TypeError):
            ok = False
        if not ok:
            reasons.append(f"acceptances: invalid or expired entry {entry!r:.120}")
            continue
        valid[key] = entry
    if not isinstance(entries, list):
        reasons.append("acceptances: 'acceptances' must be a list")
    return valid


def gate(report_path: Path, cache: Path, accepted_path: Path, image: str,
         now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    summary: dict[str, Any] = {
        "databases": {
            "vulnerabilities": database(cache, "db", "trivy.db", 2, MAX_VULN_DB_AGE, now, reasons),
            "java": database(cache, "java-db", "trivy-java.db", 1, MAX_JAVA_DB_AGE, now, reasons),
        }
    }
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        results = report["Results"]
        metadata = report["Metadata"]
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("report: missing or unreadable")
        summary.update(gate="FAIL", reasons=reasons)
        return summary
    if report.get("SchemaVersion") != 2:
        reasons.append("report: not a Trivy schema-2 report")
    scanner = (report.get("Trivy") or {}).get("Version")
    if scanner != SCANNER_VERSION:
        reasons.append(f"report: scanner {scanner!r}, expected the pinned {SCANNER_VERSION}")
    tags = metadata.get("RepoTags") or []
    if not any(str(tag).endswith(image) for tag in tags):
        reasons.append(f"report: not the image {image} (tags {tags})")
    classes = {(r.get("Class"), r.get("Type")) for r in results}
    if not any(c == "os-pkgs" for c, _ in classes) or not metadata.get("OS"):
        reasons.append("report: the operating-system packages were not scanned")
    if ("lang-pkgs", "jar") not in classes:
        reasons.append("report: no Java component was scanned")
    valid = acceptances(accepted_path, now.date(), reasons)
    counts: Counter[str] = Counter()
    blocking: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for result in results:
        for finding in result.get("Vulnerabilities") or []:
            severity = str(finding.get("Severity"))
            counts[f"{result.get('Class')}:{severity}"] += 1
            if severity not in BLOCKING:
                continue
            row = {
                "id": finding.get("VulnerabilityID"),
                "package": finding.get("PkgName"),
                "installed": finding.get("InstalledVersion"),
                "fixed": finding.get("FixedVersion"),
                "status": finding.get("Status"),
                "severity": severity,
                "class": result.get("Class"),
            }
            (accepted if (row["id"], row["package"]) in valid else blocking).append(row)
    if blocking:
        reasons.append(f"{len(blocking)} CRITICAL or HIGH findings are not accepted by the owner")
    summary.update(
        gate="FAIL" if reasons else "PASS",
        reasons=reasons,
        scanner=scanner,
        image={"tags": tags, "image_id": metadata.get("ImageID"), "os": metadata.get("OS")},
        counts=dict(sorted(counts.items())),
        blocking=sorted(blocking, key=lambda r: (r["severity"], str(r["package"]), str(r["id"]))),
        accepted=accepted,
        limits={
            "vulnerability_db_hours": MAX_VULN_DB_AGE.total_seconds() / 3600,
            "java_db_hours": MAX_JAVA_DB_AGE.total_seconds() / 3600,
            "acceptance_days": MAX_ACCEPTANCE_DAYS,
        },
    )
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--acceptances", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    options = parser.parse_args(argv)
    result = gate(options.report, options.cache, options.acceptances, options.image)
    options.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({k: result.get(k) for k in ("gate", "scanner", "databases", "counts")}, indent=2)
    )
    for row in result.get("blocking", []):
        print(
            f"{row['severity']:8} {row['id']:18} {row['package']} {row['installed']} -> {row['fixed']}"
        )
    for reason in result["reasons"]:
        print(f"GATE: {reason}", file=sys.stderr)
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
