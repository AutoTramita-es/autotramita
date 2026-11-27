"""Runs one pytest command of the workflow in two parts (INFRA-CI-02):

1. everything not marked ``serial``, in ``--workers`` pytest-xdist processes, a whole file per
   worker (``--dist loadfile``);
2. the tests marked ``serial`` (tests/serial_tests.py), alone, after the first part has ended.

Together the two ``-m`` expressions select exactly what the single command selected
(``not keycloak``). Both parts always run; the exit code is the first failure. The two JUnit
files are joined into the one the command names. One worker (or 0) runs the single command
unchanged: the serial behaviour before INFRA-CI-02.

``--workers auto`` is one worker per usable CPU, at most ``AUTO_LIMIT``.
``--print-workers`` only prints that number, for the step that starts the workers' servers.

A part that selects no test fails the run, except in a targeted run (``PYTEST_ADDOPTS`` set),
where an empty part is left out as long as the other part runs something.

Identities, not totals (scripts/ci/inventory.py, INFRA-CI-02-REC-01): before the run the unsplit
command and both parts are collected; the two selections must be disjoint and together equal the
unsplit one. After the run every part must report exactly the tests it selected. A targeted run
with several workers takes ``not keycloak`` as the unsplit selection, because the parts replace
any ``-m`` of its own.

Usage: python scripts/ci/pytest_phases.py --workers N|auto -- pytest <args> --junitxml=<file>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import inventory
from junit_merge import merge

Collect = Callable[[Sequence[str], Mapping[str, str]], list[str]]
PARTS = {"parallel": "not keycloak and not serial", "serial": "serial and not keycloak"}
NO_TESTS = 5  # pytest exit code
MAX_WORKERS = 32  # the logical CPUs of the development server
# Measured on the development server (docs/infrastructure/INFRA-CI-02-BENCHMARK.md).
AUTO_LIMIT = 16


class Usage(Exception):
    pass


def split_command(command: Sequence[str]) -> tuple[list[str], Path]:
    """The pytest arguments without ``--junitxml``, and the file it names."""
    if not command or command[0] != "pytest":
        raise Usage("the command after -- must start with pytest")
    arguments: list[str] = []
    targets: list[str] = []
    for argument in command[1:]:
        if argument.startswith("--junitxml="):
            targets.append(argument.partition("=")[2])
        elif argument in ("-m", "-n", "--dist", "--junitxml"):
            raise Usage(f"{argument} is chosen by this script (write --junitxml=<file>)")
        else:
            arguments.append(argument)
    if len(targets) != 1 or not targets[0]:
        raise Usage("the command needs exactly one --junitxml=<file>")
    return arguments, Path(targets[0])


def usable_cpus() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        return os.cpu_count() or 1


def resolve_workers(value: str, cpus: int | None = None) -> int:
    """The number of workers that ``--workers`` names."""
    if value == "auto":
        return max(1, min(AUTO_LIMIT, usable_cpus() if cpus is None else cpus))
    if not value.isdigit() or int(value) > MAX_WORKERS:
        raise Usage(f"--workers must be 'auto' or between 0 and {MAX_WORKERS}")
    return int(value)


def part_command(arguments: Sequence[str], part: str, workers: int, junit: Path) -> list[str]:
    command = [sys.executable, "-m", "pytest", *arguments, "-m", PARTS[part]]
    if part == "parallel":
        command += ["-n", str(workers), "--dist", "loadfile"]
    return [*command, f"--junitxml={junit}"]


def selections(
    reference: list[str], planned: Mapping[str, list[str]], env: Mapping[str, str], collect: Collect
) -> tuple[list[str], dict[str, list[str]]]:
    """The identities of the unsplit selection and of every part, collected at the same time."""
    with ThreadPoolExecutor(max_workers=1 + len(planned)) as pool:
        whole = pool.submit(collect, reference, env)
        parts = {name: pool.submit(collect, command, env) for name, command in planned.items()}
        return inventory.identities(whole.result()), {
            name: inventory.identities(future.result()) for name, future in parts.items()
        }


def partition_problems(whole: Sequence[str], parts: Mapping[str, Sequence[str]]) -> list[str]:
    """The parts must be complementary: no test in two of them, together the unsplit selection."""
    problems = []
    chosen = [name for part in parts.values() for name in part]
    for title, names in (
        ("in both parts", sorted({name for name in chosen if chosen.count(name) > 1})),
        ("in no part", sorted(set(whole) - set(chosen))),
        ("only in a part", sorted(set(chosen) - set(whole))),
    ):
        if names:
            problems.append(f"{len(names)} tests {title}: {', '.join(names[: inventory.LISTED])}")
    if not whole:
        problems.append("the selection holds no test")
    return problems


def report(problems: Sequence[str]) -> None:
    for problem in problems:
        print(f"pytest_phases: inventory: {problem}", file=sys.stderr)


def run(
    command: Sequence[str],
    workers: int,
    environment: Mapping[str, str],
    call: Callable[[list[str]], int] = lambda c: subprocess.call(c),  # noqa: S603
    collect: Collect = inventory.collect,
) -> int:
    if not 0 <= workers <= MAX_WORKERS:
        raise Usage(f"--workers must be between 0 and {MAX_WORKERS}")
    arguments, target = split_command(command)
    target.unlink(missing_ok=True)
    unsplit = [sys.executable, "-m", "pytest", *arguments]
    if workers <= 1:
        expected = inventory.identities(collect(unsplit, environment))
        code = call([*unsplit, f"--junitxml={target}"])
        if code not in (0, 1):  # no test, interrupted or unusable: nothing to compare
            return code
        problems = inventory.differences(expected, [target])
        report(problems)
        if not problems:
            print(inventory.statement(expected))
        return code or int(bool(problems))
    targeted = bool(environment.get("PYTEST_ADDOPTS", "").strip())
    planned = {}
    junits = {}
    for part in PARTS:
        junits[part] = target.with_name(f"{target.stem}-{part}.xml")
        junits[part].unlink(missing_ok=True)
        planned[part] = part_command(arguments, part, workers, junits[part])
    reference = [*unsplit, "-m", "not keycloak"] if targeted else unsplit
    whole, parts = selections(reference, planned, environment, collect)
    if targeted:
        if not any(parts.values()):
            print("pytest_phases: the targeted selection holds no test", file=sys.stderr)
            return NO_TESTS
        planned = {name: full for name, full in planned.items() if parts[name]}
    problems = partition_problems(whole, parts)
    if problems:
        report(problems)
        return 1
    result = 0
    for part, full in planned.items():
        how = f"{workers} workers" if part == "parallel" else "one at a time"
        print(f"== {part} part ({how}): -m '{PARTS[part]}' ==", flush=True)
        code = call(full)
        result = result or code
        if code not in (0, 1, NO_TESTS):  # interrupted or unusable: do not go on
            return code
    totals = merge([junits[part] for part in planned], target)
    print("== both parts: " + " ".join(f"{k}={v}" for k, v in totals.items()) + " ==")
    for part in planned:
        if not parts[part]:
            problems.append(f"the {part} part selects no test")
            continue
        found = inventory.differences(parts[part], [junits[part]])
        problems += [f"{part} part: {problem}" for problem in found]
    report(problems)
    if not problems:
        print(inventory.statement(whole))
    return result or int(bool(problems))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", required=True)
    parser.add_argument("--print-workers", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    try:
        workers = resolve_workers(options.workers)
        if options.print_workers:
            print(workers)
            return 0
        return run(command, workers, os.environ)
    except inventory.InventoryError as problem:
        print(f"pytest_phases: inventory: {problem}", file=sys.stderr)
        return problem.code
    except (Usage, OSError, ValueError, SyntaxError) as problem:
        print(f"pytest_phases: {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
