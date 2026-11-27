"""Which tests a suite selects and which tests its JUnit files report (INFRA-CI-02-REC-01).

A suite that runs as several pytest processes is accepted only when the *identities* of the
reported tests are exactly those pytest collects for the unsplit selection: none missing, none
twice, none unexpected. Equal totals are not enough. Anything that cannot be read as a complete
inventory raises ``InventoryError``. Standard library only.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

NO_TESTS = 5  # pytest exit code
LISTED = 20  # identities named in a message; the rest are counted
# The last line of ``pytest --collect-only`` at verbosity -1.
SUMMARY = re.compile(
    r"^(?:(?P<selected>\d+)(?:/\d+)? tests? collected(?: \(\d+ deselected\))?"
    r"|(?P<none>no tests collected)(?: \(\d+ deselected\))?)"
    r"(?:, \d+ warnings?)? in \d"
)
# As pytest's junitxml writes characters XML does not allow.
ILLEGAL_XML = re.compile(
    "[^\u0009\u000a\u000d -~\u0080-퟿-�\U00010000-\U0010ffff]"
)


class InventoryError(Exception):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _escape(match: re.Match[str]) -> str:
    number = ord(match.group())
    return f"#x{number:02X}" if number <= 0xFF else f"#x{number:04X}"


def identity(nodeid: str) -> str:
    """``classname::name`` as pytest's JUnit file reports the test with this node id. The
    parameters of a parametrized test stay part of the name."""
    path, separator, tail = nodeid.partition("::")
    if not separator or not path or not tail:
        raise InventoryError(f"{nodeid!r} is not the node id of a test")
    names_part, bracket, parameters = tail.partition("[")
    names = [re.sub(r"\.py$", "", path.replace("/", ".")), *names_part.split("::")]
    names[-1] += bracket + parameters
    return ".".join(names[:-1]) + "::" + ILLEGAL_XML.sub(_escape, names[-1])


def identities(nodeids: Sequence[str]) -> list[str]:
    """The identity of each node id; two tests that would be reported alike cannot be told apart,
    so such an inventory is refused."""
    found = [identity(nodeid) for nodeid in nodeids]
    repeated = sorted(name for name, count in Counter(found).items() if count > 1)
    if repeated:
        raise InventoryError(f"the selection names tests twice: {_named(repeated)}")
    return found


def parse_collection(output: str) -> list[str]:
    """The node ids of one ``--collect-only`` listing at verbosity -1: one per line up to the
    first empty line, as many as the summary line says."""
    lines = output.splitlines()
    summaries = [match for line in lines if (match := SUMMARY.match(line))]
    if len(summaries) != 1 or not lines or SUMMARY.match(lines[-1]) is None:
        raise InventoryError("the collection did not end in one summary line")
    if summaries[0]["none"]:
        return []
    end = lines.index("") if "" in lines else 0
    listed = lines[:end]
    stray = [line for line in listed if not line.startswith("tests/") or "::" not in line]
    if stray:
        raise InventoryError(f"the collection listing holds other lines: {_named(stray)}")
    if len(listed) != int(summaries[0]["selected"]):
        raise InventoryError(
            f"the collection lists {len(listed)} tests and reports {summaries[0]['selected']}"
        )
    return listed


def collect(command: Sequence[str], environment: Mapping[str, str]) -> list[str]:
    """The node ids that ``command`` (``[python, -m, pytest, ...]``) would run. Nothing runs and
    no result file is written. An empty selection is an empty list."""
    quiet = {k: v for k, v in environment.items() if k != "ATCI_JUNIT_DIR"}
    kept: list[str] = []
    skip = False
    for argument in command:
        if skip:
            skip = False
        elif argument in ("-n", "--dist"):
            skip = True
        elif not argument.startswith("--junitxml=") and argument not in ("-q", "-ra"):
            kept.append(argument)
    # Last, so it wins over any -q or -v before it (a targeted run may add its own).
    listing = [*kept, "--collect-only", "--color=no", "--verbosity=-1"]
    done = subprocess.run(  # noqa: S603
        listing, env=quiet, capture_output=True, text=True
    )
    if done.returncode not in (0, NO_TESTS):
        print(done.stdout[-4000:] + done.stderr[-4000:], file=sys.stderr)
        raise InventoryError("collecting the tests failed", done.returncode or 2)
    try:
        found = parse_collection(done.stdout)
    except InventoryError:
        print(done.stdout[-4000:] + done.stderr[-4000:], file=sys.stderr)
        raise
    if bool(found) == (done.returncode == NO_TESTS):
        raise InventoryError("the collection listing does not match pytest's exit code")
    return found


def reported(source: Path) -> list[str]:
    """``classname::name`` of every test a JUnit file reports. A file that is incomplete (counts
    that do not match its test cases, a case without a name) raises. One repeat is not one: pytest
    writes a test that fails in its call and again in its teardown as a failed case and a second
    case with that teardown error; such a pair is listed once."""
    try:
        root = ET.parse(source).getroot()  # noqa: S314  written by our own pytest run
    except (OSError, ET.ParseError) as problem:
        raise InventoryError(f"{source.name} cannot be read: {problem}") from None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise InventoryError(f"{source.name} holds no test suite")
    cases: dict[str, list[ET.Element]] = {}
    order: list[str] = []
    for suite in suites:
        found = suite.findall("testcase")
        if suite.get("tests") != str(len(found)):
            raise InventoryError(
                f"{source.name} is incomplete: it counts {suite.get('tests')} tests and holds "
                f"{len(found)} test cases"
            )
        for case in found:
            classname, name = case.get("classname"), case.get("name")
            if not classname or not name:
                raise InventoryError(f"{source.name} holds a test case without an identity")
            key = f"{classname}::{name}"
            cases.setdefault(key, []).append(case)
            order.append(key)
    result: list[str] = []
    taken: set[str] = set()
    for key in order:
        if key in taken and _failed_then_failed_teardown(cases[key]):
            continue
        taken.add(key)
        result.append(key)
    return result


def _failed_then_failed_teardown(cases: Sequence[ET.Element]) -> bool:
    if len(cases) != 2:
        return False
    failed = [c for c in cases if c.find("failure") is not None and c.find("error") is None]
    teardown = [
        c
        for c in cases
        if c.find("failure") is None
        and (error := c.find("error")) is not None
        and (error.get("message") or "").startswith("failed on teardown")
    ]
    return len(failed) == 1 and len(teardown) == 1


def _named(names: Sequence[str]) -> str:
    more = len(names) - LISTED
    return ", ".join(names[:LISTED]) + (f" and {more} more" if more > 0 else "")


def differences(expected: Iterable[str], sources: Sequence[Path]) -> list[str]:
    """How the tests the JUnit files report differ from the expected identities."""
    wanted = set(expected)
    if not wanted:
        return ["the selection holds no test"]
    try:
        seen = Counter(name for source in sources for name in reported(source))
    except InventoryError as problem:
        return [str(problem)]
    problems = []
    for title, names in (
        ("missing", sorted(wanted - set(seen))),
        ("duplicated", sorted(name for name, count in seen.items() if count > 1)),
        ("unexpected", sorted(set(seen) - wanted)),
    ):
        if names:
            problems.append(f"{len(names)} {title}: {_named(names)}")
    return problems


def statement(expected: Sequence[str]) -> str:
    """The line a successful check prints. The digest names the set of identities, so that
    compare-github.sh sees whether two machines ran the same tests."""
    digest = hashlib.sha256("\n".join(sorted(expected)).encode()).hexdigest()
    return (
        f"== inventory: all {len(expected)} selected tests have exactly one result, "
        f"sha256={digest} =="
    )
