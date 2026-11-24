"""Redaction, JUnit reading and the report files of one run."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PASS, FAIL, NOT_RUN, NOT_APPLICABLE = "PASS", "FAIL", "NOT_RUN", "NOT_APPLICABLE"
COUNTS = ("tests", "passed", "failed", "errors", "skipped", "deselected")
_PATTERNS = (
    (re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*"), "[REDACTED-JWT]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"([a-z][a-z0-9+.-]*://[^\s/:@'\"]*:)[^\s/@'\"]+(@)"), r"\1[REDACTED]\2"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*"), "[REDACTED-PRIVATE-KEY]"),
)


class Redactor:
    """Removes the values of credential-like variables and anything shaped like a token."""

    def __init__(self, environments: list[dict[str, str]]) -> None:
        values: set[str] = set()
        for environment in environments:
            for key, value in environment.items():
                if re.search(r"PASSWORD|SECRET|TOKEN|PRIVATE", key):
                    values.add(value)
                if "://" in value:
                    password = urlsplit(value).password
                    if password:
                        values.add(password)
        self.values = sorted((v for v in values if len(v) >= 6), key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "[REDACTED]")
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text


def read_junit(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()  # noqa: S314  produced by our own pytest run
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    counts = {key: 0 for key in COUNTS}
    seconds = 0.0
    for suite in suites:
        counts["tests"] += int(suite.get("tests", 0))
        counts["failed"] += int(suite.get("failures", 0))
        counts["errors"] += int(suite.get("errors", 0))
        counts["skipped"] += int(suite.get("skipped", 0))
        seconds += float(suite.get("time", 0))
    counts["passed"] = counts["tests"] - counts["failed"] - counts["errors"] - counts["skipped"]
    return {**counts, "seconds": round(seconds, 2)}


def checks_junit(summary: dict[str, Any], path: Path) -> None:
    """One test case per CI check, so that non-pytest checks have JUnit evidence too."""
    root = ET.Element("testsuites")
    for job in summary["jobs"]:
        suite = ET.SubElement(root, "testsuite", name=job["key"])
        for check in job["checks"]:
            if check["status"] == NOT_APPLICABLE:
                continue
            case = ET.SubElement(
                suite,
                "testcase",
                classname=job["key"],
                name=check["name"],
                time=str(check["seconds"]),
            )
            if check["status"] == FAIL:
                ET.SubElement(case, "failure", message=f"exit code {check['exit_code']}")
            elif check["status"] == NOT_RUN:
                ET.SubElement(case, "error", message="required check was not executed")
        suite.set("tests", str(len(suite)))
        suite.set("failures", str(len(suite.findall("testcase/failure"))))
        suite.set("errors", str(len(suite.findall("testcase/error"))))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def verdict(summary: dict[str, Any]) -> tuple[str, list[str]]:
    """PASS only when every required check ran and passed and no test was skipped."""
    reasons: list[str] = []
    if summary.get("error"):
        reasons.append(summary["error"])
    if summary.get("interrupted"):
        reasons.append("the run was interrupted")
    checks = 0
    for job in summary["jobs"]:
        if job.get("error"):
            reasons.append(f"{job['key']}: {job['error']}")
        for check in job["checks"]:
            checks += 1
            if check["status"] in (FAIL, NOT_RUN):
                reasons.append(f"{job['key']}: {check['name']} -> {check['status']}")
        for suite in job["suites"]:
            bad = suite["failed"] + suite["errors"] + suite["skipped"]
            if bad or not suite["tests"]:
                reasons.append(
                    f"{job['key']}: {suite['file']}: tests={suite['tests']} "
                    f"failed={suite['failed']} errors={suite['errors']} skipped={suite['skipped']}"
                )
    if not checks:
        reasons.append("no check was executed")
    return (FAIL if reasons else PASS), reasons


def text_report(summary: dict[str, Any]) -> str:
    snap = summary["content"]
    lines = [
        f"AutoTramita Local CI - {summary['status']}",
        "",
        f"Run ID        {summary['run_id']}",
        f"Profile       {summary['profile']}"
        + ("  (TARGETED: not acceptance evidence)" if summary["targeted"] else ""),
        f"Started       {summary['started']}",
        f"Finished      {summary['finished']}",
        f"Duration      {summary['seconds']} s",
        f"Git SHA       {snap['commit']}",
        f"Git branch    {snap['branch']}",
        f"Working tree  {'DIRTY' if snap['dirty'] else 'clean content (equals the commit)'}",
        f"Tested tree   {snap['tree']}",
        f"Runner code   {summary['runner_hash']}",
    ]
    if snap["changes"]:
        lines.append(f"Uncommitted changes in the tested tree ({len(snap['changes'])}):")
        lines += [f"    {change}" for change in snap["changes"]]
    if snap["excluded"]:
        lines.append("Untracked sensitive-looking files NOT copied into CI:")
        lines += [f"    {path}" for path in snap["excluded"]]
    lines += ["", "Tools and images"]
    lines += [f"    {key:<24}{value}" for key, value in summary["versions"].items()]
    for job in summary["jobs"]:
        lines += ["", f"Job '{job['key']}' - {job['name']} - {job['status']} ({job['seconds']} s)"]
        if job.get("error"):
            lines.append(f"    ERROR: {job['error']}")
        for check in job["checks"]:
            lines.append(f"    {check['status']:<15}{check['seconds']:>8.1f} s  {check['name']}")
        for suite in job["suites"]:
            counts = " ".join(f"{key}={suite[key]}" for key in COUNTS)
            lines.append(f"      suite {suite['file']}: {counts}")
    totals = " ".join(f"{key}={summary['totals'][key]}" for key in COUNTS)
    lines += [
        "",
        f"All pytest invocations (a test run twice counts twice): {totals}",
    ]
    for name, suite in summary["primary_suites"].items():
        counts = " ".join(f"{key}={suite[key]}" for key in COUNTS)
        lines.append(f"Primary suite {name}: {counts}")
    resources = summary.get("resources") or {}
    if resources:
        lines += ["", "Resources"]
        lines += [f"    {key:<28}{value}" for key, value in resources.items()]
    if summary["reasons"]:
        lines += ["", "Why this run is not a PASS"]
        lines += [f"    {reason}" for reason in summary["reasons"]]
    lines += ["", f"RESULT: {summary['status']}", ""]
    return "\n".join(lines)


def write(summary: dict[str, Any], directory: Path) -> None:
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (directory / "report.txt").write_text(text_report(summary), encoding="utf-8")
    checks_junit(summary, directory / "junit" / "checks.xml")
