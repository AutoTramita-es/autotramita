"""Compares a local full run with the GitHub Actions run of the same commit: the same jobs and
steps with the same outcome, and the same observable results (test counts, commits scanned,
audit verdict, imported realms, generated clients). Needs an authenticated `gh`; read only.

Counts are compared as counts. For the main suite and the Keycloak suite each side also prints a
digest of the identities of its tests, after checking its own results against its own collection;
an unequal digest is a difference. Other pytest steps are compared by their counts only.

Exit codes: 0 equivalent, 1 different, 2 cannot compare.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
# Steps GitHub adds itself; the local counterpart is the snapshot and the runner image.
PLATFORM_STEPS = ("Set up job", "Run actions/", "Run astral-sh/", "Post ", "Complete job")
PLATFORM_STEPS += ("Initialize containers", "Stop containers")
OUTCOME = {
    "PASS": {"success"},
    "FAIL": {"failure"},
    "NOT_APPLICABLE": {"skipped"},
    "NOT_RUN": {"skipped"},
}
EVIDENCE = (
    ("pytest summary", re.compile(r"\b(\d+ (?:passed|failed)(?:, \d+ [a-z]+)*) in [\d.]+s")),
    ("test counts", re.compile(r"\b(tests=\d+(?: [a-z]+=\d+)+)")),
    ("commits scanned", re.compile(r"(\d+) commits scanned")),
    ("secret scan", re.compile(r"(no leaks found|leaks found: \d+)")),
    ("dependency audit", re.compile(r"(No known vulnerabilities found|Found \d+ known vuln.*)")),
    ("realm import", re.compile(r"(autotramita-[a-z]+ imported and verified)")),
    ("client generation", re.compile(r"(Client generation check passed)")),
    # Printed by scripts/ci/inventory.py: the number of tests of a suite and a digest of their
    # identities. The only evidence here that names which tests ran, not how many.
    (
        "test inventory",
        re.compile(
            r"== inventory: all (\d+ selected tests have exactly one result, sha256=[0-9a-f]{64})"
        ),
    ),
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Printed by keycloak_shards.py. GitHub's runner has fewer CPUs and runs fewer shards, so the
# summaries of the shards are compared as their sum: the same number of tests of every outcome.
SHARDED = "== all shards:"


def total(summaries: list[str]) -> str:
    counts: Counter[str] = Counter()
    for summary in summaries:
        for number, outcome in re.findall(r"(\d+) ([a-z]+)", summary):
            counts[outcome] += int(number)
    return ", ".join(f"{counts[outcome]} {outcome}" for outcome in sorted(counts))


def evidence(text: str) -> dict[str, list[str]]:
    clean = ANSI.sub("", text)
    found = {name: pattern.findall(clean) for name, pattern in EVIDENCE}
    if SHARDED in clean and found["pytest summary"]:
        found["pytest summary"] = [total(found["pytest summary"])]
    return found


def gh(path: str, *, raw: bool = False) -> Any:
    done = subprocess.run(  # noqa: S603
        ["gh", "api", path], capture_output=True, text=True, errors="replace"
    )
    if done.returncode:
        raise RuntimeError(f"gh api {path} failed: {done.stderr.strip()}")
    return done.stdout if raw else json.loads(done.stdout)


def repository() -> str:
    url = subprocess.run(  # noqa: S603
        ["git", "-C", str(REPO), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    found = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not found:
        raise RuntimeError("origin is not a GitHub repository")
    return found[1]


def seconds(start: str, end: str) -> float:
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: E731
    return (parse(end) - parse(start)).total_seconds()


def compare(directory: Path, run_id: str | None) -> tuple[bool, list[str]]:
    local = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    commit = local["content"]["commit"]
    if local["profile"] != "all" or local["targeted"]:
        raise RuntimeError("only a full, untargeted run ('all') can be compared")
    if local.get("workers_override") is not None:
        raise RuntimeError("the local run overrode PYTEST_WORKERS; run without --workers")
    if local["content"]["dirty"]:
        raise RuntimeError("the local run tested uncommitted content; use run-all.sh --ref <sha>")
    repo = repository()
    if run_id:
        remote = gh(f"repos/{repo}/actions/runs/{run_id}")
    else:
        runs = gh(f"repos/{repo}/actions/runs?head_sha={commit}&event=push")["workflow_runs"]
        if not runs:
            raise RuntimeError(f"GitHub has no push run for {commit}")
        remote = max(runs, key=lambda r: r["id"])
    if remote["head_sha"] != commit:
        raise RuntimeError(f"GitHub run is for {remote['head_sha']}, local run for {commit}")
    if remote["status"] != "completed":
        raise RuntimeError(f"GitHub run {remote['id']} is still {remote['status']}")

    lines = [
        f"Commit          {commit}",
        f"Local run       {local['run_id']}  {local['status']}  {local['seconds']} s",
        f"GitHub run      {remote['id']}  {remote['conclusion']}  "
        f"{seconds(remote['run_started_at'], remote['updated_at']):.0f} s",
        f"                {remote['html_url']}",
    ]
    differences: list[str] = []
    if (local["status"] == "PASS") != (remote["conclusion"] == "success"):
        differences.append("overall result differs")
    jobs = {j["name"]: j for j in gh(f"repos/{repo}/actions/runs/{remote['id']}/jobs")["jobs"]}
    mine = {j["name"]: j for j in local["jobs"] if j["key"] != "runner"}
    if set(jobs) != set(mine):
        differences.append(f"jobs differ: GitHub {sorted(jobs)}, local {sorted(mine)}")
    for name in sorted(set(jobs) & set(mine)):
        theirs, ours = jobs[name], mine[name]
        lines += [
            "",
            f"Job '{name}': GitHub {theirs['conclusion']} "
            f"{seconds(theirs['started_at'], theirs['completed_at']):.0f} s, "
            f"local {ours['status']} {ours['seconds']:.0f} s",
        ]
        steps = {
            s["name"]: s["conclusion"]
            for s in theirs["steps"]
            if not s["name"].startswith(PLATFORM_STEPS)
        }
        checks = [c for c in ours["checks"] if not c["local_only"]]
        if list(steps) != [c["name"] for c in checks]:
            differences.append(f"{name}: step lists differ: {list(steps)}")
        for check in checks:
            other = steps.get(check["name"])
            same = other in OUTCOME[check["status"]]
            lines.append(
                f"  {'=' if same else '!'} {check['status']:<15}{other!s:<9}{check['name']}"
            )
            if not same:
                differences.append(f"{name}: '{check['name']}' local {check['status']}, {other}")
        remote_log = gh(f"repos/{repo}/actions/jobs/{theirs['id']}/logs", raw=True)
        local_log = "".join(Path(c["log"]).read_text("utf-8") for c in checks if c["log"])
        left, right = evidence(local_log), evidence(remote_log)
        for key in left:
            if not left[key] and not right[key]:
                continue
            same = left[key] == right[key]
            lines.append(f"  {'=' if same else '!'} {key}: local {left[key]} | GitHub {right[key]}")
            if not same:
                differences.append(f"{name}: {key} differs")
    lines.append("")
    lines += [f"DIFFERENCE: {d}" for d in differences]
    lines.append("RESULT: " + ("DIFFERENT" if differences else "EQUIVALENT"))
    return not differences, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=str(REPO / ".ci-results" / "latest-all"))
    parser.add_argument("--run", help="GitHub run id (default: the push run of the same commit)")
    options = parser.parse_args()
    directory = Path(options.directory).resolve()
    try:
        equivalent, lines = compare(directory, options.run)
    except (RuntimeError, OSError, KeyError) as problem:
        print(f"Cannot compare: {problem}", file=sys.stderr)
        return 2
    text = "\n".join(lines) + "\n"
    (directory / "github-comparison.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if equivalent else 1


if __name__ == "__main__":
    sys.exit(main())
