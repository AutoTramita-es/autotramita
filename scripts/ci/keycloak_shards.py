"""Runs the Keycloak tests of the workflow as several pytest processes at the same time, each
against a Keycloak instance of its own (INFRA-CI-02).

The tests change realm settings and wait for mail and back-channel calls, so nothing is shared:
each shard has its own Keycloak container with its own in-memory database and realm, its own
SMTP and back-channel ports, its own Redis logical database and its own PostgreSQL server
(roles are global to a server and migrations inspect all of them, INFRA-CI-02-REC-01).
PostgreSQL databases and roles are created per test, as always. Shards that would share one of
these are refused, before the run also when two addresses turn out to be one server.

* ``shard1``, ``shard2``: the files ``LAYOUTS`` names for that number of shards, against the
  first, second URL of ``TEST_KEYCLOAK_SHARD_URLS`` and the first, second PostgreSQL server of
  ``TEST_PG_SHARD_URLS``;
* ``primary``: every other file of the directory, new files included, against
  ``TEST_KEYCLOAK_URL``, the two nodes of ``TEST_KEYCLOAK_NODE_URLS`` and the server of
  ``TEST_PG_ADMIN_URL``.

``--shards auto`` is three shards on a host with at least ``LARGE_HOST_CPUS`` CPUs, otherwise
two; ``--shards 1`` runs the one command unchanged. ``--print-shards`` only prints the number,
for the step that starts the instances.

Before the run the directory is collected as one suite; afterwards the shard results must report
exactly those test identities: none missing, none twice, none unexpected
(scripts/ci/inventory.py). The JUnit files are joined into the one the command names and the
spike observations are merged.

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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import inventory
from junit_merge import merge

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
POSTGRESQL_PORT = 5432


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


def server(url: str, default_port: int) -> tuple[str, int]:
    """Host and port a URL names. Every loopback name is the same host."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host in ("localhost", "::1") or host.startswith("127."):
        host = "loopback"
    return host, parts.port or default_port


def postgres_server(url: str) -> tuple[str, int]:
    """The server an admin URL names. A URL whose query could name another server (``?host=``,
    ``?port=``) or that lists several hosts is refused."""
    parts = urlsplit(url)
    if parts.scheme != "postgresql" or not parts.hostname or "," in parts.netloc:
        raise Usage("a PostgreSQL URL must be postgresql://user:password@host[:port]/database")
    if parts.query or parts.fragment:
        raise Usage("a PostgreSQL URL of a shard must not carry a query or fragment")
    return server(url, POSTGRESQL_PORT)


def shard_environment(environment: Mapping[str, str], number: int) -> dict[str, str]:
    urls = environment.get("TEST_KEYCLOAK_SHARD_URLS", "").split()
    if len(urls) < number or not environment.get("TEST_REDIS_URL"):
        raise Usage(f"shard {number} needs TEST_REDIS_URL and its TEST_KEYCLOAK_SHARD_URLS entry")
    servers = environment.get("TEST_PG_SHARD_URLS", "").split()
    if len(servers) < number or not environment.get("TEST_PG_ADMIN_URL"):
        raise Usage(
            f"shard {number} needs a PostgreSQL server of its own: TEST_PG_ADMIN_URL and its "
            "TEST_PG_SHARD_URLS entry"
        )
    redis = urlsplit(environment["TEST_REDIS_URL"])
    database = int(redis.path.strip("/") or "0")
    if database < number:
        raise Usage("TEST_REDIS_URL must leave a lower logical database for every shard")
    result = dict(environment)
    result.pop("TEST_KEYCLOAK_NODE_URLS", None)  # its files must not need the nodes
    result |= {
        "TEST_KEYCLOAK_URL": urls[number - 1],
        "TEST_PG_ADMIN_URL": servers[number - 1],
        "TEST_KEYCLOAK_SMTP_PORT": str(SMTP_PORT + number),
        "TEST_KEYCLOAK_BACKCHANNEL_PORT": str(BACKCHANNEL_PORT + number),
        "TEST_REDIS_URL": urlunsplit(redis._replace(path=f"/{database - number}")),
    }
    return result


def require_isolation(environments: Sequence[Mapping[str, str]]) -> None:
    """Refuses shards that would share an instance, a PostgreSQL server, a Redis database, a
    sink port or a result file."""
    resources: dict[str, Callable[[Mapping[str, str]], object]] = {
        "Keycloak instance": lambda e: server(e["TEST_KEYCLOAK_URL"], 80),
        "PostgreSQL server": lambda e: postgres_server(e["TEST_PG_ADMIN_URL"]),
        "Redis database": lambda e: (
            server(e["TEST_REDIS_URL"], 6379),
            int(urlsplit(e["TEST_REDIS_URL"]).path.strip("/") or "0"),
        ),
        "spike result file": lambda e: e["SPIKE_RESULTS_PATH"],
        "SMTP port": lambda e: int(e.get("TEST_KEYCLOAK_SMTP_PORT", SMTP_PORT)),
        "back-channel port": lambda e: int(
            e.get("TEST_KEYCLOAK_BACKCHANNEL_PORT", BACKCHANNEL_PORT)
        ),
    }
    for name, of in resources.items():
        try:
            found = {of(environment) for environment in environments}
        except KeyError as missing:
            raise Usage(f"a shard lacks {missing.args[0]}") from None
        if len(found) != len(environments):
            raise Usage(f"every shard needs a {name} of its own")


def server_identity(url: str) -> str:
    """The identifier PostgreSQL gave its data directory: equal means one server, whatever the
    two addresses look like."""
    import psycopg  # only needed in the workflow's environment

    with psycopg.connect(url, connect_timeout=10) as connection:
        row = connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()
    if row is None:
        raise Usage("a PostgreSQL server did not identify itself")
    return str(row[0])


def require_separate_servers(urls: Sequence[str], identify: Callable[[str], str]) -> None:
    try:
        found = [identify(url) for url in urls]
    except Usage:
        raise
    except Exception as problem:  # the driver's own errors: no shard starts without proof
        raise Usage(f"cannot identify the PostgreSQL servers: {type(problem).__name__}") from None
    if len(set(found)) != len(urls):
        raise Usage("two shards reach the same PostgreSQL server")


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
    require_isolation([env for _, _, env, _ in planned])
    return planned


def collected(command: Sequence[str], environment: Mapping[str, str]) -> list[str]:
    """The identities of the tests the unsplit command selects."""
    arguments, directory, _ = split_command(command)
    unsplit = [sys.executable, "-m", "pytest", *arguments, directory]
    found = inventory.identities(inventory.collect(unsplit, environment))
    if not found:
        raise Usage("the whole suite holds no test")
    return found


def verify(expected: Sequence[str], files: Sequence[Path]) -> bool:
    """Prints how the results differ from the selected tests; ``True`` when they do not."""
    problems = inventory.differences(expected, files)
    for problem in problems:
        print(f"keycloak_shards: inventory: {problem}", file=sys.stderr)
    if not problems:
        print(inventory.statement(expected))
    return not problems


def merge_observations(sources: Sequence[Path], target: Path) -> None:
    data: dict[str, object] = {}
    for source in sources:
        if source.is_file():
            data |= json.loads(source.read_text(encoding="utf-8"))
    if data:
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def run(
    command: Sequence[str],
    environment: Mapping[str, str],
    count: int,
    identify: Callable[[str], str] = server_identity,
) -> int:
    _, _, target = split_command(command)
    target.unlink(missing_ok=True)
    if count == 1:
        expected = collected(command, environment)
        code = subprocess.call([sys.executable, "-m", *command])  # noqa: S603
        if code not in (0, 1):  # interrupted or unusable: nothing to compare
            return code
        return code or int(not verify(expected, [target]))
    with tempfile.TemporaryDirectory(prefix="kc-shards-") as temporary:
        work = Path(temporary)
        planned = shards(command, environment, work, count)
        require_separate_servers([env["TEST_PG_ADMIN_URL"] for _, _, env, _ in planned], identify)
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
        if not verify(expected, files):
            return result or 1
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
    except inventory.InventoryError as problem:
        print(f"keycloak_shards: inventory: {problem}", file=sys.stderr)
        return problem.code
    except (Usage, OSError, ValueError, SyntaxError) as problem:
        print(f"keycloak_shards: {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
