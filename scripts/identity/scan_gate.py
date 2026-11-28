"""The gate over the Trivy scan of the AutoTramita Keycloak image (KC-SP-12, PROD-SEC-01 / D49).
Standard library only and Python 3.10 or later, so it runs the same way in Local CI and on GitHub.

It fails (exit 1) unless every one of these holds:

* the vulnerability database (schema 2) is at most ``MAX_VULN_DB_AGE`` old and the Java
  database (schema 1) at most ``MAX_JAVA_DB_AGE`` (measured from their ``UpdatedAt``); a
  missing, unreadable or older database is never a pass;
* the report is a Trivy schema-2 report by the pinned scanner version, and it covers the
  operating-system packages **and** the Java components;
* the report is of the saved image archive the scanner read: its ``ImageID`` is the SHA-256 of
  the configuration blob in that archive, its ``RepoTags`` are the archive's, and that is exactly
  one tag, the expected image or its exact Local CI form (``LOCAL_CI_TAG``);
* every finding carries a known severity (``SEVERITIES``) whose source is the authoritative
  package-level vendor of its result (``AUTHORITATIVE``: ``redhat`` for the operating-system
  packages, ``ghsa`` for the Java components), and that vendor's rating in ``VendorSeverity``
  is the same severity. Anything missing, unknown, malformed or inconsistent fails;
* no CRITICAL finding, ever: CRITICAL cannot be accepted;
* no HIGH finding without a matching acceptance by the owner. There are no automatic
  exceptions: an acceptance names the finding (id and package), ``severity: "HIGH"``, the exact
  ``installed`` version and the exact ``fixed`` version (``null``: no fix), ``accepted_by:
  "owner"``, the decision that accepted it and an expiry at most ``MAX_ACCEPTANCE_DAYS`` ahead.
  A finding whose installed or fixed version differs from its acceptance is not accepted. An
  entry listed twice is refused, and so is every copy of it.

It writes the summary (``--summary``) and prints all of it, with the accepted findings, the image
identity and the hashes of its inputs, into the job log: that log is the gate's evidence (D49 Q3).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_VULN_DB_AGE = timedelta(hours=48)  # Trivy publishes this database every six hours
MAX_JAVA_DB_AGE = timedelta(days=7)  # and this one about every three days
MAX_ACCEPTANCE_DAYS = 90
SCANNER_VERSION = "0.76.2"
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
BLOCKING = ("CRITICAL", "HIGH")
ACCEPTABLE = "HIGH"  # the only severity an acceptance may carry; CRITICAL always fails
# Trivy's numeric vendor ratings; 0 (UNKNOWN) is not a severity the gate can judge.
VENDOR_LEVELS = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
# The authoritative package-level vendor of each result kind (D49 Q1). A finding in any other
# kind of result has no authoritative rating and fails.
AUTHORITATIVE = {("os-pkgs", "redhat"): "redhat", ("lang-pkgs", "jar"): "ghsa"}
# Local CI builds the image under the job's prefix (scripts/ci/lib/broker.py): atci-<run>-<job>-.
LOCAL_CI_TAG = r"atci-\d{8}-\d{6}-[0-9a-f]{6}-image-scan-"
MAX_CONFIG_BYTES = 4 << 20
ACCEPTANCE_FIELDS = ("id", "package", "severity", "installed", "fixed", "accepted_by",
                     "decision", "expires")  # fmt: skip


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


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def archive(path: Path, reasons: list[str]) -> dict[str, Any]:
    """The identity of the saved image the scanner read: the digest of its configuration blob
    (what Trivy reports as ``ImageID``) and its tags. Exactly one image, uncompressed."""
    try:
        with tarfile.open(path, "r:") as tar:
            manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ValueError("the archive must hold exactly one image")
            entry = manifest[0]
            member = tar.getmember(str(entry["Config"]))
            if not member.isfile() or member.size > MAX_CONFIG_BYTES:
                raise ValueError("the configuration is not a regular file of sensible size")
            config = tar.extractfile(member).read()  # type: ignore[union-attr]
            tags = entry.get("RepoTags")
            if not isinstance(tags, list):
                raise ValueError("the archive names no tags")
        identity = _sha256(path)
    except (OSError, tarfile.TarError, ValueError, KeyError, TypeError, AttributeError) as error:
        reasons.append(f"archive: missing or unreadable ({type(error).__name__}: {error})")
        return {"present": False}
    return {
        "present": True,
        "config_digest": f"sha256:{hashlib.sha256(config).hexdigest()}",
        "repo_tags": tags,
        "sha256": identity,
    }


def image_binding(metadata: dict[str, Any], saved: dict[str, Any], image: str,
                  reasons: list[str]) -> None:  # fmt: skip
    tags = metadata.get("RepoTags")
    expected = re.compile(rf"(?:{LOCAL_CI_TAG})?{re.escape(image)}")
    if not (isinstance(tags, list) and len(tags) == 1 and isinstance(tags[0], str)
            and expected.fullmatch(tags[0])):  # fmt: skip
        reasons.append(f"report: not exactly the image {image} (tags {tags})")
    if not saved.get("present"):
        return
    if metadata.get("ImageID") != saved["config_digest"]:
        reasons.append(
            f"report: image id {metadata.get('ImageID')!r} is not the saved image "
            f"{saved['config_digest']}"
        )
    if tags != saved["repo_tags"]:
        reasons.append(f"report: tags {tags} are not those of the saved image")


def acceptances(
    path: Path, today: date, reasons: list[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["acceptances"]
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("acceptances: file missing or unreadable")
        return {}
    if not isinstance(entries, list):
        reasons.append("acceptances: 'acceptances' must be a list")
        return {}
    valid: dict[tuple[str, str], dict[str, Any]] = {}
    seen: Counter[tuple[str, str]] = Counter()
    for entry in entries:
        try:
            expires = date.fromisoformat(str(entry["expires"]))
            key = (entry["id"], entry["package"])
            ok = (
                all(field in entry for field in ACCEPTANCE_FIELDS)
                and _text(entry["id"])
                and _text(entry["package"])
                and entry["severity"] == ACCEPTABLE
                and _text(entry["installed"])
                and (entry["fixed"] is None or _text(entry["fixed"]))
                and entry["accepted_by"] == "owner"
                and _text(entry["decision"])
                and today <= expires <= today + timedelta(days=MAX_ACCEPTANCE_DAYS)
            )
        except (KeyError, ValueError, TypeError):
            ok = False
        if not ok:
            reasons.append(f"acceptances: invalid or expired entry {entry!r:.160}")
            continue
        seen[key] += 1
        valid[key] = entry
    for key, times in seen.items():
        if times > 1:
            reasons.append(f"acceptances: {key[0]} in {key[1]} is listed {times} times")
            del valid[key]
    return valid


def severity_problem(kind: tuple[Any, Any], finding: dict[str, Any]) -> str | None:
    """Why the finding's severity cannot be trusted, or None (D49 Q1)."""
    vendor = AUTHORITATIVE.get(kind)
    if vendor is None:
        return f"no authoritative vendor for {kind[0]}/{kind[1]}"
    severity = finding.get("Severity")
    if severity not in SEVERITIES:
        return f"severity {severity!r} is not one of {', '.join(SEVERITIES)}"
    if finding.get("SeveritySource") != vendor:
        return f"severity source {finding.get('SeveritySource')!r}, expected {vendor!r}"
    ratings = finding.get("VendorSeverity")
    level = ratings.get(vendor) if isinstance(ratings, dict) else None
    if type(level) is not int or VENDOR_LEVELS.get(level) != severity:
        return f"{vendor} rates it {level!r}, the scanner {severity}"
    return None


def judge(finding: dict[str, Any], kind: tuple[Any, Any],
          valid: dict[tuple[str, str], dict[str, Any]]) -> tuple[dict[str, Any], str | None]:  # fmt: skip
    """The summary row of a finding and why it blocks (None: it does not)."""
    fixed = finding.get("FixedVersion")
    row = {
        "id": finding.get("VulnerabilityID"),
        "package": finding.get("PkgName"),
        "installed": finding.get("InstalledVersion"),
        "fixed": None if fixed == "" else fixed,
        "status": finding.get("Status"),
        "severity": finding.get("Severity"),
        "source": finding.get("SeveritySource"),
        "class": kind[0],
    }
    if not (_text(row["id"]) and _text(row["package"]) and _text(row["installed"])
            and (row["fixed"] is None or _text(row["fixed"]))):  # fmt: skip
        return row, "the finding does not name its id, package and versions"
    problem = severity_problem(kind, finding)
    if problem:
        return row, problem
    if row["severity"] not in BLOCKING:
        return row, None
    entry = valid.get((row["id"], row["package"]))
    if row["severity"] != ACCEPTABLE:
        return row, "CRITICAL cannot be accepted" if entry else "not accepted by the owner"
    if entry is None:
        return row, "not accepted by the owner"
    if (entry["installed"], entry["fixed"]) != (row["installed"], row["fixed"]):
        return row, (
            f"accepted for installed {entry['installed']!r} and fix {entry['fixed']!r}, "
            f"reported {row['installed']!r} and {row['fixed']!r}"
        )
    return row, None


def gate(report_path: Path, cache: Path, accepted_path: Path, image: str, archive_path: Path,
         now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    summary: dict[str, Any] = {
        "databases": {
            "vulnerabilities": database(cache, "db", "trivy.db", 2, MAX_VULN_DB_AGE, now, reasons),
            "java": database(cache, "java-db", "trivy-java.db", 1, MAX_JAVA_DB_AGE, now, reasons),
        }
    }
    saved = archive(archive_path, reasons)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        results = report["Results"]
        metadata = report["Metadata"]
        if not isinstance(results, list) or not isinstance(metadata, dict):
            raise TypeError("Results or Metadata")
        if not all(isinstance(r, dict) for r in results):
            raise TypeError("Results")
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("report: missing or unreadable")
        summary.update(gate="FAIL", reasons=reasons, archive=saved)
        return summary
    if report.get("SchemaVersion") != 2:
        reasons.append("report: not a Trivy schema-2 report")
    scanner = (report.get("Trivy") or {}).get("Version")
    if scanner != SCANNER_VERSION:
        reasons.append(f"report: scanner {scanner!r}, expected the pinned {SCANNER_VERSION}")
    image_binding(metadata, saved, image, reasons)
    classes = {(r.get("Class"), r.get("Type")) for r in results}
    if not any(c == "os-pkgs" for c, _ in classes) or not metadata.get("OS"):
        reasons.append("report: the operating-system packages were not scanned")
    if ("lang-pkgs", "jar") not in classes:
        reasons.append("report: no Java component was scanned")
    valid = acceptances(accepted_path, now.date(), reasons)
    counts: Counter[str] = Counter()
    blocking: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    used: set[tuple[str, str]] = set()
    for result in results:
        kind = (result.get("Class"), result.get("Type"))
        findings = result.get("Vulnerabilities") or []
        if not isinstance(findings, list):
            reasons.append(f"report: the findings of {kind[0]}/{kind[1]} are not a list")
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                reasons.append(f"report: a finding of {kind[0]}/{kind[1]} is not an object")
                continue
            row, problem = judge(finding, kind, valid)
            counts[f"{kind[0]}:{row['severity']}"] += 1
            if problem:
                blocking.append({**row, "problem": problem})
            elif row["severity"] in BLOCKING:
                accepted.append(row)
                used.add((row["id"], row["package"]))
    if blocking:
        reasons.append(f"{len(blocking)} findings block (see 'blocking')")
    summary.update(
        gate="FAIL" if reasons else "PASS",
        reasons=reasons,
        scanner=scanner,
        image={
            "tags": metadata.get("RepoTags"),
            "image_id": metadata.get("ImageID"),
            "os": metadata.get("OS"),
        },
        archive=saved,
        inputs={"report_sha256": _sha256(report_path), "acceptances_sha256": _file(accepted_path)},
        counts=dict(sorted(counts.items())),
        blocking=sorted(blocking, key=lambda r: (str(r["severity"]), str(r["package"]),
                                                 str(r["id"]))),  # fmt: skip
        accepted=accepted,
        unused_acceptances=sorted(f"{i} {p}" for i, p in valid if (i, p) not in used),
        limits={
            "vulnerability_db_hours": MAX_VULN_DB_AGE.total_seconds() / 3600,
            "java_db_hours": MAX_JAVA_DB_AGE.total_seconds() / 3600,
            "acceptance_days": MAX_ACCEPTANCE_DAYS,
        },
    )
    return summary


def _file(path: Path) -> str | None:
    try:
        return _sha256(path)
    except OSError:
        return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True, help="the image the scanner read")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--acceptances", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    options = parser.parse_args(argv)
    result = gate(options.report, options.cache, options.acceptances, options.image,
                  options.archive)  # fmt: skip
    text = json.dumps(result, indent=2) + "\n"
    options.summary.write_text(text, encoding="utf-8")
    print("Scan gate summary (retained in this log, D49):")
    print(text, end="")
    for row in result.get("blocking", []):
        print(
            f"{row['severity']!s:8} {row['id']!s:18} {row['package']} {row['installed']} -> "
            f"{row['fixed']}: {row['problem']}"
        )
    print(f"scan gate: {result['gate']}")
    for reason in result["reasons"]:
        print(f"GATE: {reason}", file=sys.stderr)
    return 0 if result["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
