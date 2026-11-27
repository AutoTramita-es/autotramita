"""INFRA-CI-02: guards of the parallel test run. A test that races threads, sleeps or measures
time must run serially (checked only as far as a text search sees it), and parallel workers and
Keycloak shards must share neither a PostgreSQL server nor Redis keys."""

import ast
import importlib
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit, urlunsplit

import pytest
from tests.conftest import FileScheduling, worker_pg_url, worker_redis_url
from tests.serial_tests import SPLIT_FILES, TESTS, WHOLE_FILES, is_serial

ROOT = Path(__file__).resolve().parents[1]
PRIMITIVE = re.compile(
    r"\b(Thread|ThreadPoolExecutor|ProcessPoolExecutor|Barrier|Timer|Process)\("
    r"|\b(time|asyncio)\.sleep\(|perf_counter|time\.monotonic|asyncio\.gather"
    r"|ThreadingTCPServer|serve_forever"
)
Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


class Module:
    def __init__(self, path: Path) -> None:
        self.source = path.read_text(encoding="utf-8")
        tree = ast.parse(self.source)
        self.definitions = {n.name: n for n in tree.body if isinstance(n, Definition)}
        self.imports = {
            alias.asname or alias.name: (str(node.module), alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and str(node.module).startswith("tests")
            for alias in node.names
        }


def modules() -> dict[str, Module]:
    """Every module of the main suite. The Keycloak tests never run in parallel workers."""
    found = {}
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name.endswith("_keycloak.py") or path.name.startswith("test_keycloak"):
            continue
        found[".".join(path.relative_to(ROOT).with_suffix("").parts)] = Module(path)
    return found


def reaches(known: dict[str, Module], module: str, name: str, seen: set[tuple[str, str]]) -> bool:
    """Does this function, class or fixture use a primitive, directly or through anything of the
    tests package that it names (its fixtures included)?"""
    if (module, name) in seen or module not in known:
        return False
    seen.add((module, name))
    here = known[module]
    node = here.definitions.get(name)
    if node is None:
        target = here.imports.get(name)
        return target is not None and reaches(known, *target, seen)
    if PRIMITIVE.search(ast.get_source_segment(here.source, node) or ""):
        return True
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    names |= {
        argument.arg
        for n in ast.walk(node)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        for argument in n.args.args
    }
    return any(
        reaches(known, module, other, seen)
        for other in names - {name}
        if other in here.definitions or other in here.imports
    )


def test_every_concurrent_or_timed_test_runs_serially() -> None:
    known = modules()
    unlisted = []
    for module, content in known.items():
        file = module.replace(".", "/") + ".py"
        if not Path(file).name.startswith("test_"):
            continue
        for name, node in content.definitions.items():
            if not name.startswith("test_") or isinstance(node, ast.ClassDef):
                continue
            if reaches(known, module, name, set()) and not is_serial(file, name):
                unlisted.append(f"{file}::{name}")
    assert not unlisted, f"add to tests/serial_tests.py: {unlisted}"


def test_every_serial_entry_names_an_existing_test() -> None:
    for file in WHOLE_FILES:
        assert (ROOT / file).is_file(), file
    for file, names in TESTS.items():
        defined = set(Module(ROOT / file).definitions)
        assert names and names <= defined, f"{file}: unknown {sorted(names - defined)}"


def test_the_guard_sees_a_primitive_behind_a_helper_and_a_fixture() -> None:
    known = modules()
    cases = {
        "tests.auth.security.test_password_check": (
            "test_the_application_wires_the_check_into_its_worker"
        ),
        "tests.test_ratelimit": "test_remaining_and_reset",
    }
    for module, name in cases.items():
        assert reaches(known, module, name, set()), name


def test_split_files_share_no_wider_fixture_between_their_tests() -> None:
    wider = re.compile(r"scope=.(module|class|package|session)")
    for file in SPLIT_FILES - {"tests/auth/test_token_mutations.py"}:
        assert not wider.search((ROOT / file).read_text()), file


def test_workers_take_whole_files_except_the_split_ones() -> None:
    scheduling = FileScheduling.__new__(FileScheduling)  # the grouping needs no worker nodes
    assert scheduling._split_scope("tests/test_config.py::test_a[1]") == "tests/test_config.py"
    for file in SPLIT_FILES:
        assert (ROOT / file).is_file(), file
        assert scheduling._split_scope(f"{file}::test_a[x::y]") == f"{file}::test_a[x::y]"


@pytest.mark.parametrize(
    ("worker", "expected"),
    [
        (None, "6379/15"),
        ("gw0", "6379/15"),
        ("gw1", "6440/1"),
        ("gw15", "6440/15"),
        ("gw31", "6440/31"),
    ],
)
def test_every_worker_has_a_redis_database_of_its_own(worker: str | None, expected: str) -> None:
    first, others = "redis://127.0.0.1:6379/15", "redis://127.0.0.1:6440/0"
    assert worker_redis_url(first, worker, others) == f"redis://127.0.0.1:{expected}"


def test_workers_never_share_a_redis_database_silently() -> None:
    with pytest.raises(ValueError, match="TEST_REDIS_WORKERS_URL"):
        worker_redis_url("redis://127.0.0.1:6379/15", "gw1", None)


def test_the_redis_of_the_workers_has_a_database_for_every_possible_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    databases = re.search(r"redis-server .*--databases (\d+)", workflow)
    assert databases and int(databases[1]) >= phases.MAX_WORKERS
    assert "redis-server --bind 127.0.0.1 --port 6440" in workflow


@pytest.mark.parametrize(
    ("value", "cpus", "workers"),
    [("auto", 1, 1), ("auto", 4, 4), ("auto", 32, 16), ("0", 4, 0), ("1", 4, 1), ("32", 4, 32)],
)
def test_the_number_of_workers_follows_the_cpus_up_to_the_measured_limit(
    monkeypatch: pytest.MonkeyPatch, value: str, cpus: int, workers: int
) -> None:
    assert script(monkeypatch, "pytest_phases").resolve_workers(value, cpus) == workers


@pytest.mark.parametrize("value", ["33", "-1", "many", ""])
def test_an_impossible_number_of_workers_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    with pytest.raises(phases.Usage):
        phases.resolve_workers(value, 4)


@pytest.mark.parametrize(
    ("worker", "port"), [(None, 5432), ("gw0", 5432), ("gw1", 5441), ("gw3", 5443)]
)
def test_every_worker_has_a_postgresql_server_of_its_own(worker: str | None, port: int) -> None:
    url = worker_pg_url("postgresql://postgres:p%40ss@127.0.0.1:5432/postgres", worker, "5440")
    assert url == f"postgresql://postgres:p%40ss@127.0.0.1:{port}/postgres"


def test_workers_never_share_a_postgresql_server_silently() -> None:
    with pytest.raises(ValueError, match="TEST_PG_WORKER_PORT_BASE"):
        worker_pg_url("postgresql://postgres@127.0.0.1/postgres", "gw1", None)


def test_the_worker_servers_run_the_pinned_image_of_the_service() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    images = re.findall(r"postgres:16@sha256:[0-9a-f]{64}", workflow)
    # two services, the worker servers and the servers of the Keycloak shards
    assert len(images) == 4 and len(set(images)) == 1
    redis = re.findall(r"redis:7@sha256:[0-9a-f]{64}", workflow)
    assert len(redis) == 3 and len(set(redis)) == 1
    assert workflow.count("-c listen_addresses=127.0.0.1") == 2


# --- the two scripts the workflow runs the suites with ----------------------------------------
def script(monkeypatch: pytest.MonkeyPatch, name: str) -> ModuleType:
    """A module of scripts/ci, which is outside the application packages (and their typing)."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "ci"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    return importlib.import_module(name)


def write_junit(path: Path, *names: str, failed: str = "") -> None:
    cases = "".join(
        f'<testcase classname="t" name="{n}">{"<failure/>" if n == failed else ""}</testcase>'
        for n in names
    )
    path.write_text(
        f'<testsuites><testsuite tests="{len(names)}" failures="{int(bool(failed))}" '
        f'errors="0" skipped="0" time="1.5">{cases}</testsuite></testsuites>'
    )


def fake_collect(
    monkeypatch: pytest.MonkeyPatch, **selected: Sequence[str]
) -> Callable[[Sequence[str], object], list[str]]:
    """The node ids of the two parts, matching what ``fake_pytest`` reports unless ``selected``
    says otherwise; the unsplit command selects both."""
    parts = script(monkeypatch, "pytest_phases").PARTS
    tests = {name: [f"t::{name}-1", f"t::{name}-2"] for name in parts}
    tests |= {name: list(ids) for name, ids in selected.items() if name != "whole"}

    def collect(command: Sequence[str], environment: object) -> list[str]:
        for name, expression in parts.items():
            if expression in command:
                return tests[name]
        if "whole" in selected:
            return list(selected["whole"])
        return [test for ids in tests.values() for test in ids]

    return collect


def fake_pytest(codes: dict[str, int], calls: list[list[str]]) -> Callable[[list[str]], int]:
    def call(command: list[str]) -> int:
        calls.append(command)
        junit = Path(command[-1].partition("=")[2])
        part = junit.stem.rpartition("-")[2]
        write_junit(junit, f"{part}-1", f"{part}-2", failed=f"{part}-1" if codes.get(part) else "")
        return codes.get(part, 0)

    return call


def test_the_two_parts_select_complementary_tests_and_join_one_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    calls: list[list[str]] = []
    target = tmp_path / "junit.xml"
    command = ["pytest", "-q", "-W", "error", f"--junitxml={target}"]
    collect = fake_collect(monkeypatch)
    assert phases.run(command, 4, {}, call=fake_pytest({}, calls), collect=collect) == 0
    parallel, serial = calls
    assert parallel[parallel.index("-m", 3) + 1] == "not keycloak and not serial"
    assert serial[serial.index("-m", 3) + 1] == "serial and not keycloak"
    assert parallel[parallel.index("-n") + 1] == "4" and "-n" not in serial
    assert parallel[parallel.index("--dist") + 1] == "loadfile"
    for call in calls:
        assert call[3:6] == ["-q", "-W", "error"]  # the workflow's own arguments, unchanged
    merge = script(monkeypatch, "junit_merge")
    expected = ("parallel-1", "parallel-2", "serial-1", "serial-2")
    assert merge.case_ids(target) == [f"t::{name}" for name in expected]
    assert 'tests="4"' in target.read_text()


def test_a_failure_in_the_parallel_part_fails_the_run_and_the_serial_part_still_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    calls: list[list[str]] = []
    command = ["pytest", f"--junitxml={tmp_path / 'junit.xml'}"]
    call = fake_pytest({"parallel": 1}, calls)
    assert phases.run(command, 2, {}, call=call, collect=fake_collect(monkeypatch)) == 1
    assert len(calls) == 2 and 'failures="1"' in (tmp_path / "junit.xml").read_text()


@pytest.mark.parametrize("code", [2, 3, 4])
def test_an_interrupted_or_broken_part_stops_the_run_without_a_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    calls: list[list[str]] = []
    target = tmp_path / "junit.xml"
    target.write_text("stale")
    command = ["pytest", f"--junitxml={target}"]
    call = fake_pytest({"parallel": code}, calls)
    assert phases.run(command, 2, {}, call=call, collect=fake_collect(monkeypatch)) == code
    assert len(calls) == 1 and not target.exists()


def test_an_empty_part_fails_a_full_run_and_is_left_out_of_a_targeted_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    command = ["pytest", f"--junitxml={tmp_path / 'junit.xml'}"]
    no_serial = fake_collect(monkeypatch, serial=[])
    assert phases.run(command, 2, {}, call=fake_pytest({"serial": 5}, []), collect=no_serial) == 5

    calls: list[list[str]] = []
    targeted = {"PYTEST_ADDOPTS": "tests/test_config.py"}
    code = phases.run(command, 2, targeted, call=fake_pytest({}, calls), collect=no_serial)
    assert code == 0 and len(calls) == 1
    empty = fake_collect(monkeypatch, parallel=[], serial=[])
    nothing = phases.run(command, 2, targeted, call=fake_pytest({}, []), collect=empty)
    assert nothing == 5


@pytest.mark.parametrize("workers", [0, 1])
def test_one_worker_is_the_single_unchanged_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workers: int
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    calls: list[list[str]] = []
    command = ["pytest", "-q", f"--junitxml={tmp_path / 'junit.xml'}"]

    def call(full: list[str]) -> int:
        calls.append(full)
        write_junit(tmp_path / "junit.xml", "one")
        return 0

    code = phases.run(command, workers, {}, call=call, collect=lambda *_: ["t::one"])
    assert code == 0
    assert calls[0][1:] == ["-m", "pytest", "-q", command[-1]]


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["ruff", "check"],
        ["pytest", "-q"],
        ["pytest", "-m", "serial", "--junitxml=x.xml"],
        ["pytest", "-n", "2", "--junitxml=x.xml"],
    ],
)
def test_the_phases_script_refuses_a_command_it_would_change_the_meaning_of(
    monkeypatch: pytest.MonkeyPatch, command: list[str]
) -> None:
    phases = script(monkeypatch, "pytest_phases")
    with pytest.raises(phases.Usage):
        phases.run(command, 2, {}, call=lambda _: 0)


KEYCLOAK_ENVIRONMENT = {
    "TEST_PG_ADMIN_URL": "postgresql://postgres:x@127.0.0.1:5432/postgres",
    "TEST_PG_SHARD_URLS": (
        "postgresql://postgres:x@127.0.0.1:5451/postgres "
        "postgresql://postgres:x@127.0.0.1:5452/postgres"
    ),
    "TEST_KEYCLOAK_URL": "http://127.0.0.1:18081",
    "TEST_KEYCLOAK_SHARD_URLS": "http://127.0.0.1:18086 http://127.0.0.1:18088",
    "TEST_KEYCLOAK_NODE_URLS": "a b",
    "TEST_REDIS_URL": "redis://127.0.0.1:6379/14",
}


@pytest.mark.parametrize("count", [2, 3])
def test_the_keycloak_shards_share_no_instance_port_or_redis_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    monkeypatch.chdir(ROOT)
    command = ["pytest", "-m", "keycloak", "tests/identity", "--junitxml=/x/junit-identity.xml"]
    planned = shards.shards(command, KEYCLOAK_ENVIRONMENT, tmp_path, count)
    assert len(planned) == count
    (_, primary, first, _), others = planned[0], planned[1:]
    moved = [
        file for _, selection, _, _ in others for file in selection if file.startswith("tests/")
    ]
    # every file is selected exactly once: the first shard ignores exactly what the others run
    ignored = [a.partition("=")[2] for a in primary if a.startswith("--ignore=")]
    assert sorted(ignored) == sorted(moved) and len(set(moved)) == len(moved)
    assert "tests/identity" in primary
    environments = [environment for _, _, environment, _ in planned]
    for key in ("TEST_KEYCLOAK_URL", "TEST_PG_ADMIN_URL", "TEST_REDIS_URL", "SPIKE_RESULTS_PATH"):
        assert len({environment[key] for environment in environments}) == count, key
    assert len({junit for *_, junit in planned}) == count
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert first["TEST_KEYCLOAK_NODE_URLS"]
    # the first shard keeps the service, which also holds the database of the two nodes
    assert first["TEST_PG_ADMIN_URL"] == KEYCLOAK_ENVIRONMENT["TEST_PG_ADMIN_URL"]
    servers = KEYCLOAK_ENVIRONMENT["TEST_PG_SHARD_URLS"].split()
    for number, (_, _, environment, _) in enumerate(others, 1):
        assert "TEST_KEYCLOAK_NODE_URLS" not in environment
        assert environment["TEST_KEYCLOAK_SMTP_PORT"] == str(18025 + number)
        assert environment["TEST_KEYCLOAK_BACKCHANNEL_PORT"] == str(18090 + number)
        assert environment["TEST_KEYCLOAK_URL"] in workflow
        assert environment["TEST_PG_ADMIN_URL"] == servers[number - 1]
    # no file moved away from the first shard needs the two cluster nodes
    for file in moved:
        assert "TEST_KEYCLOAK_NODE_URLS" not in (ROOT / file).read_text()
    assert "smtp=$((18025 + shard)); backchannel=$((18090 + shard))" in workflow


@pytest.mark.parametrize(("value", "cpus", "count"), [("auto", 4, 2), ("auto", 32, 3), ("1", 4, 1)])
def test_a_large_host_runs_three_keycloak_shards(
    monkeypatch: pytest.MonkeyPatch, value: str, cpus: int, count: int
) -> None:
    assert script(monkeypatch, "keycloak_shards").resolve_shards(value, cpus) == count


@pytest.mark.parametrize("value", ["0", "4", "two", ""])
def test_an_impossible_number_of_shards_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    with pytest.raises(shards.Usage):
        shards.resolve_shards(value, 32)


def test_a_shard_without_an_instance_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    monkeypatch.chdir(ROOT)
    one = KEYCLOAK_ENVIRONMENT | {"TEST_KEYCLOAK_SHARD_URLS": "http://127.0.0.1:18086"}
    command = ["pytest", "tests/identity", "--junitxml=/x/junit-identity.xml"]
    with pytest.raises(shards.Usage):
        shards.shards(command, one, tmp_path, 3)


def test_the_keycloak_inventory_check_notices_a_missing_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    first, second = tmp_path / "a.xml", tmp_path / "b.xml"
    write_junit(first, "one", "two")
    write_junit(second, "three")
    expected = ["t::one", "t::two", "t::three"]
    assert shards.verify(expected, [first, second])
    assert not shards.verify([*expected, "t::four"], [first, second])
    write_junit(second, "two")
    assert not shards.verify(expected, [first, second])


def test_the_keycloak_suite_is_counted_from_the_collected_test_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = script(monkeypatch, "inventory")
    output = (
        "tests/identity/a.py::test_x[p/q]\ntests/identity/a.py::test_y\n\n"
        "2 tests collected in 0.01s\n"
    )
    assert len(inventory.parse_collection(output)) == 2
    with pytest.raises(inventory.InventoryError):
        inventory.parse_collection("tests/identity/a.py: 14\n\n14 tests collected in 0.01s\n")


def test_a_part_without_a_result_file_cannot_be_joined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    merge = script(monkeypatch, "junit_merge")
    present = tmp_path / "a.xml"
    write_junit(present, "one")
    with pytest.raises(OSError):
        merge.merge([present, tmp_path / "missing.xml"], tmp_path / "out.xml")


# --- REC-01: a PostgreSQL server for every additional Keycloak shard ----------------------------
PRIMARY = "postgresql://postgres:x@127.0.0.1:5432/postgres"
SHARD1 = "postgresql://postgres:x@127.0.0.1:5451/postgres"


@pytest.mark.parametrize(
    "changed",
    [
        {"TEST_PG_SHARD_URLS": ""},
        {"TEST_PG_SHARD_URLS": SHARD1},  # one server for two additional shards
        {"TEST_PG_ADMIN_URL": ""},
        {"TEST_PG_SHARD_URLS": f"{PRIMARY} {SHARD1}"},  # the primary's server
        {"TEST_PG_SHARD_URLS": f"{SHARD1} {SHARD1}"},
        # the same server under other spellings
        {"TEST_PG_SHARD_URLS": f"{SHARD1} postgresql://postgres:x@localhost:5451/other"},
        {"TEST_PG_SHARD_URLS": f"{SHARD1} postgresql://other:y@[::1]:5451/postgres"},
        {"TEST_PG_SHARD_URLS": f"{SHARD1} postgresql://postgres:x@127.0.0.2/postgres"},
        # addresses that could lead anywhere
        {"TEST_PG_SHARD_URLS": f"{SHARD1} {PRIMARY.replace('5432', '5452')}?port=5432"},
        {"TEST_PG_SHARD_URLS": f"{SHARD1} postgresql://postgres:x@a:5452,b:5432/postgres"},
        {"TEST_PG_SHARD_URLS": f"{SHARD1} mysql://postgres:x@127.0.0.1:5452/postgres"},
        {"TEST_PG_SHARD_URLS": f"{SHARD1} not-a-url"},
        # and every other resource a shard must not share
        {"TEST_KEYCLOAK_SHARD_URLS": "http://127.0.0.1:18086 http://localhost:18086"},
        {"TEST_KEYCLOAK_SHARD_URLS": "http://127.0.0.1:18081 http://127.0.0.1:18088"},
        {"TEST_KEYCLOAK_URL": ""},
    ],
)
def test_shards_that_would_share_a_server_or_instance_are_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: dict[str, str]
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    monkeypatch.chdir(ROOT)
    command = ["pytest", "tests/identity", "--junitxml=/x/junit-identity.xml"]
    environment = {k: v for k, v in (KEYCLOAK_ENVIRONMENT | changed).items() if v}
    with pytest.raises(shards.Usage):
        shards.shards(command, environment, tmp_path, 3)


def test_two_addresses_of_one_server_are_refused_by_what_the_server_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    answers = {"a": "1", "b": "2", "c": "1"}
    shards.require_separate_servers(["a", "b"], answers.__getitem__)
    with pytest.raises(shards.Usage, match="same PostgreSQL server"):
        shards.require_separate_servers(["a", "b", "c"], answers.__getitem__)
    with pytest.raises(shards.Usage, match="cannot identify"):
        shards.require_separate_servers(["a", "unreachable"], answers.__getitem__)


def test_a_real_server_identifies_itself_the_same_under_any_of_its_names(
    monkeypatch: pytest.MonkeyPatch, pg_admin_url: str
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    parts = urlsplit(pg_admin_url)
    other = "localhost" if parts.hostname != "localhost" else "127.0.0.1"
    netloc = parts.netloc.replace(f"@{parts.hostname}", f"@{other}")
    again = urlunsplit(parts._replace(netloc=netloc))
    assert again != pg_admin_url
    with pytest.raises(shards.Usage, match="same PostgreSQL server"):
        shards.require_separate_servers([pg_admin_url, again], shards.server_identity)


def test_no_shard_starts_before_the_servers_are_proven_separate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    monkeypatch.chdir(ROOT)

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test process was started")

    monkeypatch.setattr(shards.subprocess, "Popen", never)
    monkeypatch.setattr(shards.subprocess, "run", never)
    command = ["pytest", "tests/identity", f"--junitxml={tmp_path / 'junit-identity.xml'}"]
    with pytest.raises(shards.Usage, match="same PostgreSQL server"):
        shards.run(command, KEYCLOAK_ENVIRONMENT, 3, identify=lambda url: "one")


def test_the_workflow_starts_a_loopback_server_for_every_additional_shard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shards = script(monkeypatch, "keycloak_shards")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    identity = workflow.split("\n  identity:\n")[1].split("\n  secrets:\n")[0]
    declared = identity.split("TEST_PG_SHARD_URLS: >-\n")[1]
    urls = re.findall(r"^\s+(postgresql://\S+)$", declared.split("TEST_KEYCLOAK_ADMIN")[0], re.M)
    assert len(urls) == max(shards.LAYOUTS) - 1
    admin = re.search(r"TEST_PG_ADMIN_URL: (\S+)", identity)
    assert admin
    servers = [shards.postgres_server(url) for url in [admin[1], *urls]]
    assert len(set(servers)) == len(servers) and {host for host, _ in servers} == {"loopback"}
    step = identity.split("- name: Start the PostgreSQL servers of the additional test shards")[1]
    step = step.split("- name:")[0]
    for required in (
        "for url in $TEST_PG_SHARD_URLS",
        '--name "postgres-shard$shard" --network host --user 1001:1001',
        'data="$RUNNER_TEMP/postgres-shard$shard"',
        '-v "$data:/var/lib/postgresql/data"',
        "-c listen_addresses=127.0.0.1",
    ):
        assert required in step, required
    assert identity.index("PostgreSQL servers of the additional") < identity.index(
        'keycloak_shards.py --shards "$KEYCLOAK_SHARDS" -- pytest'
    )


# --- REC-04: what the guard of the serial list can and cannot see ------------------------------
# The synthetic sources are module constants: the guard searches the text of functions, and these
# tests run no thread, sleep or clock themselves.
SYNTHETIC_HELPER = "def wait():\n    time.sleep(1)\n"
SYNTHETIC_CLASS = "class TestX:\n    def test_inside(self):\n        time.sleep(1)\n"
SEEN = {
    "thread": "def test_x():\n    threading.Thread(target=f).start()\n",
    "pool": "def test_x():\n    ThreadPoolExecutor(max_workers=2)\n",
    "barrier": "def test_x():\n    threading.Barrier(2)\n",
    "sleep": "def test_x():\n    time.sleep(1)\n",
    "async sleep": "async def test_x():\n    await asyncio.sleep(1)\n",
    "clock": "def test_x():\n    assert time.monotonic()\n",
    "port server": "def test_x():\n    socketserver.ThreadingTCPServer(('', 1), H)\n",
    "helper": "def wait():\n    time.sleep(1)\ndef test_x():\n    wait()\n",
    "fixture of the module": (
        "@pytest.fixture\ndef slow():\n    time.sleep(1)\ndef test_x(slow):\n    pass\n"
    ),
    "imported helper": "from tests.helper import wait\ndef test_x():\n    wait()\n",
}
NOT_SEEN = {
    "imported name": "from time import sleep\ndef test_x():\n    sleep(1)\n",
    "module alias": "import time as clock\ndef test_x():\n    clock.sleep(1)\n",
    "event wait": "def test_x():\n    threading.Event().wait(1)\n",
    "wall clock": "def test_x():\n    assert time.time()\n",
    "database lease": (
        "def test_x(db):\n    db.execute(\"UPDATE t SET lease_until = now() + interval '1s'\")\n"
    ),
    "redis expiry": "def test_x(cache):\n    cache.set('k', 1, px=5)\n",
    "fixture from a conftest": "def test_x(wait):\n    pass\n",
    "module attribute": "from tests import helper\ndef test_x():\n    helper.wait()\n",
    "application code": "from app.worker import wait\ndef test_x():\n    wait()\n",
}


def reached(tmp_path: Path, source: str) -> bool:
    test, helper = tmp_path / "test_synthetic.py", tmp_path / "helper.py"
    test.write_text(source)
    helper.write_text(SYNTHETIC_HELPER)
    known = {"tests.synthetic": Module(test), "tests.helper": Module(helper)}
    return reaches(known, "tests.synthetic", "test_x", set())


@pytest.mark.parametrize("source", SEEN.values(), ids=SEEN)
def test_the_guard_sees_these_dependencies(tmp_path: Path, source: str) -> None:
    assert reached(tmp_path, source)


@pytest.mark.parametrize("source", NOT_SEEN.values(), ids=NOT_SEEN)
def test_the_guard_does_not_see_these_dependencies(tmp_path: Path, source: str) -> None:
    """Documented limits (LOCAL-CI.md, "Writing tests"): such a test must be listed by its
    author. Whoever teaches the guard one of these moves it to ``SEEN`` and edits that text."""
    assert not reached(tmp_path, source)


def test_the_guard_does_not_look_inside_test_classes(tmp_path: Path) -> None:
    path = tmp_path / "test_synthetic.py"
    path.write_text(SYNTHETIC_CLASS)
    assert "test_inside" not in Module(path).definitions


def test_ci_runs_the_suites_through_the_scripts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert 'python scripts/ci/pytest_phases.py --workers "$PYTEST_WORKERS" --' in workflow
    assert 'PYTEST_WORKERS: "auto"' in workflow
    assert 'python scripts/ci/keycloak_shards.py --shards "$KEYCLOAK_SHARDS" -- pytest' in workflow
