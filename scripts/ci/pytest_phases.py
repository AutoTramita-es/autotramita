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

Usage: python scripts/ci/pytest_phases.py --workers N|auto -- pytest <args> --junitxml=<file>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from junit_merge import merge

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


def selects_tests(command: Sequence[str], environment: Mapping[str, str]) -> bool:
    """Collection only, for targeted runs. It must leave no result file behind."""
    quiet = {k: v for k, v in environment.items() if k != "ATCI_JUNIT_DIR"}
    probe = [a for a in command if not a.startswith("--junitxml=")]
    for flag in ("-n", "--dist"):
        if flag in probe:
            del probe[probe.index(flag) : probe.index(flag) + 2]
    done = subprocess.run(  # noqa: S603
        [*probe, "--collect-only", "-q"], env=quiet, capture_output=True, text=True
    )
    if done.returncode not in (0, NO_TESTS):
        return True  # let the real run report the error
    return done.returncode == 0


def run(
    command: Sequence[str],
    workers: int,
    environment: Mapping[str, str],
    call: Callable[[list[str]], int] = lambda c: subprocess.call(c),  # noqa: S603
    probe: Callable[[Sequence[str], Mapping[str, str]], bool] = selects_tests,
) -> int:
    if not 0 <= workers <= MAX_WORKERS:
        raise Usage(f"--workers must be between 0 and {MAX_WORKERS}")
    arguments, target = split_command(command)
    target.unlink(missing_ok=True)
    if workers <= 1:
        return call([sys.executable, "-m", "pytest", *arguments, f"--junitxml={target}"])
    targeted = bool(environment.get("PYTEST_ADDOPTS", "").strip())
    planned = []
    for part in PARTS:
        junit = target.with_name(f"{target.stem}-{part}.xml")
        junit.unlink(missing_ok=True)
        planned.append((part, junit, part_command(arguments, part, workers, junit)))
    if targeted:
        planned = [entry for entry in planned if probe(entry[2], environment)]
        if not planned:
            print("pytest_phases: the targeted selection holds no test", file=sys.stderr)
            return NO_TESTS
    result = 0
    for part, _, full in planned:
        how = f"{workers} workers" if part == "parallel" else "one at a time"
        print(f"== {part} part ({how}): -m '{PARTS[part]}' ==", flush=True)
        code = call(full)
        result = result or code
        if code not in (0, 1, NO_TESTS):  # interrupted or unusable: do not go on
            return code
    totals = merge([junit for _, junit, _ in planned], target)
    print("== both parts: " + " ".join(f"{k}={v}" for k, v in totals.items()) + " ==")
    return result


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
    except (Usage, OSError, ValueError, SyntaxError) as problem:
        print(f"pytest_phases: {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
