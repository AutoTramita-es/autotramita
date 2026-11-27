"""INFRA-CI-02-REC-01 (REC-05): a suite that ran in parts is accepted by the identities of its
tests, not by their number. Every way an inventory can be wrong has a test here."""

import importlib
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest
from _pytest.junitxml import bin_xml_escape, mangle_test_address

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scripts(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], ModuleType]:
    """Modules of scripts/ci, which is outside the application packages (and their typing)."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "ci"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    return importlib.import_module


@pytest.fixture
def inventory(scripts: Callable[[str], ModuleType]) -> ModuleType:
    return scripts("inventory")


def junit(path: Path, *cases: tuple[str, str] | str, counted: int | None = None) -> Path:
    """A result file of the tests ``t::<name>``; a case may carry the XML of its outcome."""
    body = ""
    for case in cases:
        name, outcome = (case, "") if isinstance(case, str) else case
        body += f'<testcase classname="t" name="{name}">{outcome}</testcase>'
    count = len(cases) if counted is None else counted
    path.write_text(f'<testsuites><testsuite tests="{count}">{body}</testsuite></testsuites>')
    return path


def suite(case: str, attributes: str) -> str:
    return f"<testsuites><testsuite{attributes}>{case}</testsuite></testsuites>"


FAILURE = '<failure message="assert 0"/>'
TEARDOWN = '<error message="failed on teardown with &quot;boom&quot;"/>'
EXPECTED = ["t::a[1]", "t::a[2]", "t::b"]


# --- identities --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nodeid",
    [
        "tests/a.py::test_x",
        "tests/auth/web/test_web_flow.py::test_x[a-b]",
        "tests/a.py::test_x[p/q.py::r[0]]",
        "tests/a.py::TestGroup::test_x[ x y ]",
        "tests/a.py::test_x[\\x00-\\u00e9]",
        "tests/a.py::test_x[bell\x07]",
    ],
)
def test_an_identity_is_what_pytest_writes_into_its_result_file(
    inventory: ModuleType, nodeid: str
) -> None:
    names = mangle_test_address(nodeid)
    expected = ".".join(names[:-1]) + "::" + bin_xml_escape(names[-1])
    assert inventory.identity(nodeid) == expected


def test_parametrized_tests_keep_their_own_identity(inventory: ModuleType) -> None:
    found = inventory.identities(["tests/a.py::test_x[1]", "tests/a.py::test_x[2]"])
    assert found == ["tests.a::test_x[1]", "tests.a::test_x[2]"]


@pytest.mark.parametrize("nodeid", ["tests/a.py", "", "::test_x", "tests/a.py::"])
def test_what_names_no_test_has_no_identity(inventory: ModuleType, nodeid: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.identity(nodeid)


def test_a_selection_that_names_a_test_twice_is_refused(inventory: ModuleType) -> None:
    with pytest.raises(inventory.InventoryError, match="twice"):
        inventory.identities(["tests/a.py::test_x", "tests/a.py::test_x"])


# --- results against the selection -------------------------------------------------------------
def test_exactly_the_selected_tests_in_any_files_are_no_difference(
    inventory: ModuleType, tmp_path: Path
) -> None:
    files = [junit(tmp_path / "1.xml", "b", "a[2]"), junit(tmp_path / "2.xml", "a[1]")]
    assert inventory.differences(EXPECTED, files) == []


@pytest.mark.parametrize(
    ("reported", "found"),
    [
        (("a[1]", "a[2]"), ["1 missing: t::b"]),
        # the two cases the count-only check accepted
        (("a[1]", "a[2]", "a[2]"), ["1 missing: t::b", "1 duplicated: t::a[2]"]),
        (("a[1]", "a[2]", "c"), ["1 missing: t::b", "1 unexpected: t::c"]),
        # every test there and one of them twice
        (("a[1]", "a[2]", "b", "b"), ["1 duplicated: t::b"]),
        (("a[1]", "a[2]", "b", "c"), ["1 unexpected: t::c"]),
        # one parameter set in place of another
        (("a[1]", "a[3]", "b"), ["1 missing: t::a[2]", "1 unexpected: t::a[3]"]),
    ],
)
def test_a_missing_duplicated_or_unexpected_test_is_a_difference(
    inventory: ModuleType, tmp_path: Path, reported: tuple[str, ...], found: list[str]
) -> None:
    assert inventory.differences(EXPECTED, [junit(tmp_path / "r.xml", *reported)]) == found


def test_a_test_reported_by_two_parts_is_duplicated(inventory: ModuleType, tmp_path: Path) -> None:
    files = [junit(tmp_path / "1.xml", "a[1]", "a[2]", "b"), junit(tmp_path / "2.xml", "b")]
    assert inventory.differences(EXPECTED, files) == ["1 duplicated: t::b"]


def test_a_failure_followed_by_a_teardown_error_is_one_test(
    inventory: ModuleType, tmp_path: Path
) -> None:
    file = junit(tmp_path / "r.xml", ("b", FAILURE), ("b", TEARDOWN), "a[1]", "a[2]")
    assert inventory.differences(EXPECTED, [file]) == []


@pytest.mark.parametrize(
    "pair",
    [
        ("", ""),
        ("", TEARDOWN),
        (FAILURE, FAILURE),
        (TEARDOWN, TEARDOWN),
        (FAILURE, '<error message="failed on setup"/>'),
    ],
)
def test_no_other_repeat_is_taken_for_one_test(
    inventory: ModuleType, tmp_path: Path, pair: tuple[str, str]
) -> None:
    file = junit(tmp_path / "r.xml", ("b", pair[0]), ("b", pair[1]), "a[1]", "a[2]")
    assert inventory.differences(EXPECTED, [file]) == ["1 duplicated: t::b"]


def test_a_third_report_of_a_failed_test_is_a_repeat(inventory: ModuleType, tmp_path: Path) -> None:
    cases: list[tuple[str, str] | str] = [("b", FAILURE), ("b", TEARDOWN), ("b", "")]
    file = junit(tmp_path / "r.xml", *cases, "a[1]", "a[2]")
    assert inventory.differences(EXPECTED, [file]) == ["1 duplicated: t::b"]


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "<testsuites><testsuite tests='3'><testcase classname='t' name='b'/>",
        "<testsuites/>",
        suite("<testcase classname='t' name='b'/>", " tests='3'"),
        suite("<testcase classname='t' name='b'/>", ""),
        suite("<testcase classname='t'/>", " tests='1'"),
        suite("<testcase classname='' name='b'/>", " tests='1'"),
    ],
    ids=[
        "no file",
        "empty",
        "cut off",
        "no suite",
        "too few cases",
        "no count",
        "no name",
        "no class",
    ],
)
def test_an_incomplete_or_unreadable_result_file_fails_the_check(
    inventory: ModuleType, tmp_path: Path, content: str | None
) -> None:
    file = tmp_path / "r.xml"
    if content is not None:
        file.write_text(content)
    assert inventory.differences(EXPECTED, [file])
    with pytest.raises(inventory.InventoryError):
        inventory.reported(file)


def test_an_empty_selection_never_passes(inventory: ModuleType, tmp_path: Path) -> None:
    assert inventory.differences([], [junit(tmp_path / "r.xml")]) == ["the selection holds no test"]


def test_the_printed_line_names_the_set_of_tests(inventory: ModuleType) -> None:
    line = inventory.statement(EXPECTED)
    assert "all 3 selected tests" in line
    assert inventory.statement(list(reversed(EXPECTED))) == line
    assert inventory.statement(["t::a[1]", "t::a[2]", "t::c"]) != line


# --- the collection listing --------------------------------------------------------------------
ONE = "tests/a.py::test_x"
TWO = "tests/a.py::test_y[a b]"


@pytest.mark.parametrize(
    "summary",
    [
        "2 tests collected in 0.01s",
        "2/9 tests collected (7 deselected) in 61.00s (0:01:01)",
        "2 tests collected, 1 warning in 0.01s",
    ],
)
def test_a_complete_listing_is_read(inventory: ModuleType, summary: str) -> None:
    assert inventory.parse_collection(f"{ONE}\n{TWO}\n\n{summary}\n") == [ONE, TWO]


def test_an_empty_selection_is_read_as_one(inventory: ModuleType) -> None:
    assert inventory.parse_collection("\nno tests collected (9 deselected) in 0.01s\n") == []


@pytest.mark.parametrize(
    "output",
    [
        "",
        f"{ONE}\n{TWO}\n",
        f"{ONE}\n\n2 tests collected in 0.01s\n",
        f"{ONE}\n{TWO}\n\n1 test collected in 0.01s\n",
        f"{ONE}\nplugin: hello\n\n2 tests collected in 0.01s\n",
        f"{ONE}\n\n{TWO}\n\n2 tests collected in 0.01s\n",
        f"{ONE}\n{TWO}\n\n2 tests collected, 1 error in 0.01s\n",
        f"{ONE}\n{TWO}\n2 tests collected in 0.01s\n",
        f"{ONE}\n\n1 test collected in 0.01s\nmore output\n",
        f"{ONE}\n\n1 test collected in 0.01s\n1 test collected in 0.01s\n",
    ],
)
def test_an_incomplete_listing_is_refused(inventory: ModuleType, output: str) -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.parse_collection(output)


# --- against pytest itself ---------------------------------------------------------------------
SAMPLE = """
import pytest

@pytest.mark.parametrize("value", ["a b", "x::y", "p/q", "[0]", "\\u00e9"])
def test_param(value):
    pass

class TestGroup:
    def test_method(self):
        pass

@pytest.fixture
def broken():
    yield
    raise RuntimeError("teardown")

def test_fails_twice(broken):
    assert False

def test_passes_then_breaks(broken):
    pass

@pytest.mark.slow
def test_marked():
    pass
"""


def sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str = SAMPLE) -> dict[str, str]:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(source)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    slow: slow\n")
    monkeypatch.chdir(tmp_path)
    return {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "ATCI_"))}


@pytest.mark.parametrize("workers", [(), ("-n", "2")], ids=["one process", "two workers"])
def test_a_real_collection_matches_a_real_result_file(
    inventory: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workers: tuple[str, ...],
) -> None:
    environment = sample(tmp_path, monkeypatch)
    command = [sys.executable, "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider", "tests"]
    expected = inventory.identities(inventory.collect([*command, *workers], environment))
    assert len(expected) == 9
    target = tmp_path / "junit.xml"
    done = subprocess.run(  # noqa: S603
        [*command, *workers, f"--junitxml={target}"], env=environment, capture_output=True
    )
    assert done.returncode == 1  # the two tests that break on purpose
    assert inventory.differences(expected, [target]) == []
    # and a selection that differs by one marker is noticed
    fewer = inventory.identities(inventory.collect([*command, "-m", "not slow"], environment))
    extra = "1 unexpected: tests.test_sample::test_marked"
    assert inventory.differences(fewer, [target]) == [extra]


def test_a_collection_that_fails_or_finds_nothing_is_told_apart(
    inventory: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = sample(tmp_path, monkeypatch)
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "tests", "-vv"]
    assert inventory.collect([*command, "-k", "nothing_has_this_name"], environment) == []
    (tmp_path / "tests" / "test_broken.py").write_text("def test_(:\n")
    with pytest.raises(inventory.InventoryError) as problem:
        inventory.collect(command, environment)
    assert problem.value.code == 2


# --- the two parts of the main suite -----------------------------------------------------------
Selected = dict[str, Sequence[str]]
GOOD: Selected = {
    "whole": ["t::p1", "t::p2", "t::s1"],
    "parallel": ["t::p1", "t::p2"],
    "serial": ["t::s1"],
}


def run_parts(
    scripts: Callable[[str], ModuleType],
    tmp_path: Path,
    selected: Selected,
    reported: dict[str, Sequence[str]],
) -> tuple[int, list[str]]:
    """``pytest_phases.run`` with a given collection and given results of the parts."""
    phases = scripts("pytest_phases")
    ran: list[str] = []

    def collect(command: Sequence[str], environment: object) -> list[str]:
        for name, expression in phases.PARTS.items():
            if expression in command:
                return list(selected[name])
        return list(selected["whole"])

    def call(command: list[str]) -> int:
        target = Path(command[-1].partition("=")[2])
        part = target.stem.rpartition("-")[2]
        ran.append(part)
        junit(target, *[name.removeprefix("t::") for name in reported[part]])
        return 0

    command = ["pytest", f"--junitxml={tmp_path / 'junit.xml'}"]
    return phases.run(command, 2, {}, call=call, collect=collect), ran


def test_complementary_parts_that_report_their_selection_pass(
    scripts: Callable[[str], ModuleType], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_parts(scripts, tmp_path, GOOD, GOOD) == (0, ["parallel", "serial"])
    assert "all 3 selected tests have exactly one result" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"serial": ["t::s1", "t::p1"]}, "in both parts: t::p1"),
        ({"parallel": ["t::p1"]}, "in no part: t::p2"),
        ({"serial": ["t::s1", "t::extra"]}, "only in a part: t::extra"),
        ({"serial": ["t::other"]}, "in no part: t::s1"),
        ({"whole": [], "parallel": [], "serial": []}, "holds no test"),
    ],
)
def test_parts_that_do_not_make_up_the_selection_fail_before_any_test(
    scripts: Callable[[str], ModuleType],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: Selected,
    message: str,
) -> None:
    assert run_parts(scripts, tmp_path, GOOD | change, GOOD) == (1, [])
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"parallel": ["t::p1"]}, "parallel part: 1 missing: t::p2"),
        ({"parallel": ["t::p1", "t::p1"]}, "parallel part: 1 duplicated: t::p1"),
        ({"serial": ["t::other"]}, "serial part: 1 unexpected: t::other"),
        # the same tests in the wrong parts: the total is right, the parts are not
        ({"parallel": ["t::p1", "t::s1"], "serial": ["t::p2"]}, "parallel part: 1 missing"),
    ],
)
def test_a_part_that_reports_other_tests_than_it_selected_fails_the_run(
    scripts: Callable[[str], ModuleType],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: Selected,
    message: str,
) -> None:
    code, ran = run_parts(scripts, tmp_path, GOOD, GOOD | change)
    output = capsys.readouterr()
    assert (code, ran) == (1, ["parallel", "serial"])
    assert message in output.err and "selected tests have exactly" not in output.out


@pytest.mark.parametrize("workers", [1, 4])
def test_a_selection_that_cannot_be_collected_runs_nothing(
    scripts: Callable[[str], ModuleType], tmp_path: Path, workers: int
) -> None:
    phases, inventory = scripts("pytest_phases"), scripts("inventory")

    def collect(command: Sequence[str], environment: object) -> list[str]:
        raise inventory.InventoryError("collecting the tests failed", 2)

    def never(command: list[str]) -> int:
        raise AssertionError("tests were run")

    command = ["pytest", f"--junitxml={tmp_path / 'junit.xml'}"]
    with pytest.raises(inventory.InventoryError):
        phases.run(command, workers, {}, call=never, collect=collect)


def test_one_worker_is_checked_by_identity_too(
    scripts: Callable[[str], ModuleType], tmp_path: Path
) -> None:
    phases = scripts("pytest_phases")
    target = tmp_path / "junit.xml"

    def call(command: list[str]) -> int:
        junit(target, "a", "c")
        return 0

    command = ["pytest", f"--junitxml={target}"]
    assert phases.run(command, 1, {}, call=call, collect=lambda *_: ["t::a", "t::b"]) == 1


def test_one_keycloak_process_is_checked_by_identity_too(
    scripts: Callable[[str], ModuleType], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards = scripts("keycloak_shards")
    target = tmp_path / "junit-identity.xml"
    names = ["a", "b"]

    def call(command: list[str]) -> int:
        junit(target, *names)
        return 0

    monkeypatch.setattr(shards, "collected", lambda *_: ["t::a", "t::b"])
    monkeypatch.setattr(shards.subprocess, "call", call)
    command = ["pytest", "tests/identity", f"--junitxml={target}"]
    assert shards.run(command, {}, 1) == 0
    names = ["a", "a"]
    assert shards.run(command, {}, 1) == 1


def test_the_repeated_rate_limit_runs_are_separate_pytest_runs() -> None:
    """Each of the three repetitions runs every rate-limit test again, on purpose: they are no
    part of a suite whose inventory is checked, and nothing joins or deduplicates them."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    step = workflow.split("- name: Rate-limit timing regression")[1].split("- name:")[0]
    assert "for run in 1 2 3; do" in step
    assert "uv run --locked pytest -q tests/test_ratelimit.py" in step
    assert "pytest_phases" not in step and "keycloak_shards" not in step
