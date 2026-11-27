"""Runs the Keycloak tests of the workflow as several pytest processes at the same time, each
against a Keycloak instance of its own (INFRA-CI-02).

The tests change realm settings and wait for mail and back-channel calls, so nothing is shared:
each shard has its own Keycloak container with its own in-memory database and realm, its own
SMTP and back-channel ports, and its own Redis logical database. PostgreSQL databases are
created per test, as always.

* ``shard1``, ``shard2``: the files ``LAYOUTS`` names for that number of shards, against the
  first, second URL of ``TEST_KEYCLOAK_SHARD_URLS``;
* ``primary``: every other file of the directory, new files included, against
  ``TEST_KEYCLOAK_URL`` and the two nodes of ``TEST_KEYCLOAK_NODE_URLS``.

``--shards auto`` is three shards on a host with at least ``LARGE_HOST_CPUS`` CPUs, otherwise
two; ``--shards 1`` runs the one command unchanged. ``--print-shards`` only prints the number,
for the step that starts the instances.

Before the run the directory is collected as one suite; afterwards the executed test cases must
be exactly as many, without repeats. The two JUnit files are joined into the one the command
names and the spike observations are merged.

Usage: python scripts/ci/keycloak_shards.py --shards N|auto -- pytest <args> <directory>
       --junitxml=<file>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from junit_merge import case_ids, merge

SPIKE = "tests/identity/test_keycloak_spike.py"
SECOND_FACTOR = "tests/identity/test_second_factor_keycloak.py"
RECOVERY = "tests/identity/test_recovery_codes_keycloak.py"
RECONCILIATION = "tests/identity/test_reconciliation_keycloak.py"
# Number of shards -> the files of the additional shards, balanced by measured durations
# (docs/infrastructure/INFRA-CI-02-BENCHMARK.md). None of these files uses the two cluster nodes.
LAYOUTS: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (),
    2: ((SPIKE, SECOND_FACTOR),),
    3: ((SECOND_FACTOR,), (SPIKE, RECOVERY, RECONCILIATION)),
}
LARGE_HOST_CPUS = 16
# Shard N has the sinks on these ports plus N; its realm names them (ci.yml).
SMTP_PORT = 18025
BACKCHANNEL_PORT = 18090


class Usage(Exception):
    pass


def split_command(command: Sequence[str]) -> tuple[list[str], str, Path]:
    if not command or command[0] != "pytest":
        raise Usage("the command after -- must start with pytest")
    arguments: list[str] = []
    directories: list[str] = []
    targets: list[str] = []
    for argument in command[1:]:
        if argument.startswith("--junitxml="):
            targets.append(argument.partition("=")[2])
        elif argument.startswith("tests/") and Path(argument).is_dir():
            directories.append(argument.rstrip("/"))
        else:
            arguments.append(argument)
    if len(targets) != 1 or len(directories) != 1 or not targets[0]:
        raise Usage("the command needs one test directory and one --junitxml=<file>")
    return arguments, directories[0], Path(targets[0])


def resolve_shards(value: str, cpus: int | None = None) -> int:
    if value == "auto":
        available = len(os.sched_getaffinity(0)) if cpus is None else cpus
        return 3 if available >= LARGE_HOST_CPUS else 2
    if not value.isdigit() or int(value) not in LAYOUTS:
        raise Usage(f"--shards must be 'auto' or one of {sorted(LAYOUTS)}")
    return int(value)


def shard_environment(environment: Mapping[str, str], number: int) -> dict[str, str]:
    urls = environment.get("TEST_KEYCLOAK_SHARD_URLS", "").split()
    if len(urls) < number or not environment.get("TEST_REDIS_URL"):
        raise Usage(f"shard {number} needs TEST_REDIS_URL and its TEST_KEYCLOAK_SHARD_URLS entry")
    redis = urlsplit(environment["TEST_REDIS_URL"])
    database = int(redis.path.strip("/") or "0")
    if database < number:
        raise Usage("TEST_REDIS_URL must leave a lower logical database for every shard")
    result = dict(environment)
    result.pop("TEST_KEYCLOAK_NODE_URLS", None)  # its files must not need the nodes
    result |= {
        "TEST_KEYCLOAK_URL": urls[number - 1],
        "TEST_KEYCLOAK_SMTP_PORT": str(SMTP_PORT + number),
        "TEST_KEYCLOAK_BACKCHANNEL_PORT": str(BACKCHANNEL_PORT + number),
        "TEST_REDIS_URL": urlunsplit(redis._replace(path=f"/{database - number}")),
    }
    return result


def shards(
    command: Sequence[str], environment: Mapping[str, str], work: Path, count: int
) -> list[tuple[str, list[str], dict[str, str], Path]]:
    """(name, command, environment, JUnit file) of each shard."""
    arguments, directory, target = split_command(command)
    moved = [file for files in LAYOUTS[count] for file in files]
    for file in moved:
        if not file.startswith(f"{directory}/") or not Path(file).is_file():
            raise Usage(f"{file} is not a file of {directory}; update LAYOUTS")
    selections = {"primary": [directory, *[f"--ignore={file}" for file in moved]]}
    environments = {"primary": dict(environment)}
    for number, files in enumerate(LAYOUTS[count], 1):
        selections[f"shard{number}"] = list(files)
        environments[f"shard{number}"] = shard_environment(environment, number)
    planned = []
    for name, selection in selections.items():
        junit = target.with_name(f"{target.stem}-{name}.xml")
        env = environments[name]
        env["SPIKE_RESULTS_PATH"] = str(work / f"spike-{name}.json")
        full = [sys.executable, "-m", "pytest", *arguments, *selection, f"--junitxml={junit}"]
        planned.append((name, full, env, junit))
    return planned


def collected(command: Sequence[str], environment: Mapping[str, str]) -> int:
    """How many tests the unsplit command selects."""
    arguments, directory, _ = split_command(command)
    quiet = {k: v for k, v in environment.items() if k != "ATCI_JUNIT_DIR"}
    # One -q and no other: then every selected test is listed as one ``file::name`` line.
    listing = [a for a in arguments if a not in ("-q", "-ra")]
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", *listing, directory, "--collect-only", "-q"],
        env=quiet,
        capture_output=True,
        text=True,
    )
    found = count_listed(done.stdout, directory)
    if done.returncode or not found:
        print(done.stdout[-4000:] + done.stderr[-4000:], file=sys.stderr)
        raise Usage("collecting the whole suite failed")
    return found


def count_listed(output: str, directory: str) -> int:
    lines = output.splitlines()
    return sum(1 for line in lines if line.startswith(f"{directory}/") and "::" in line)


def inventory_problem(expected: int, files: Sequence[Path]) -> str | None:
    ids = [case for file in files for case in case_ids(file)]
    unique = len(set(ids))
    # A test that fails in its call and again in its teardown is reported twice by pytest.
    if unique != expected:
        return f"{expected} tests selected, {unique} distinct tests in the shard results"
    return None


def merge_observations(sources: Sequence[Path], target: Path) -> None:
    data: dict[str, object] = {}
    for source in sources:
        if source.is_file():
            data |= json.loads(source.read_text(encoding="utf-8"))
    if data:
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def run(command: Sequence[str], environment: Mapping[str, str], count: int) -> int:
    _, _, target = split_command(command)
    target.unlink(missing_ok=True)
    if count == 1:
        return subprocess.call([sys.executable, "-m", *command])  # noqa: S603
    with tempfile.TemporaryDirectory(prefix="kc-shards-") as temporary:
        work = Path(temporary)
        planned = shards(command, environment, work, count)
        expected = collected(command, environment)
        running = []
        for name, full, env, junit in planned:
            junit.unlink(missing_ok=True)
            output = open(work / f"{name}.log", "w+", encoding="utf-8")  # noqa: SIM115
            process = subprocess.Popen(  # noqa: S603
                full, env=env, stdout=output, stderr=subprocess.STDOUT
            )
            running.append((name, process, output))
        result = 0
        try:
            # Printed one shard after the other, in a fixed order.
            for name, process, output in running:
                code = process.wait()
                output.seek(0)
                print(f"== Keycloak shard '{name}' (exit {code}) ==")
                print(output.read(), end="", flush=True)
                result = result or code
        finally:
            for _, process, output in running:
                if process.poll() is None:
                    process.kill()
                output.close()
        files = [junit for _, _, _, junit in planned]
        observations = environment.get("SPIKE_RESULTS_PATH")
        if observations:
            merge_observations(
                [Path(env["SPIKE_RESULTS_PATH"]) for _, _, env, _ in planned], Path(observations)
            )
        totals = merge(files, target)
        print("== all shards: " + " ".join(f"{k}={v}" for k, v in totals.items()) + " ==")
        problem = inventory_problem(expected, files)
        if problem:
            print(f"keycloak_shards: {problem}", file=sys.stderr)
            return result or 1
        print(f"== inventory: all {expected} selected tests have a result ==")
        return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", required=True)
    parser.add_argument("--print-shards", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    try:
        count = resolve_shards(options.shards)
        if options.print_shards:
            print(count)
            return 0
        return run(command, os.environ, count)
    except (Usage, OSError, ValueError, SyntaxError) as problem:
        print(f"keycloak_shards: {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
