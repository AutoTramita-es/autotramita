"""AutoTramita Local CI: runs the jobs of .github/workflows/ci.yml on this machine.

Usage is through the wrappers in scripts/ci/. See docs/infrastructure/LOCAL-CI.md.
Exit codes: 0 PASS, 1 FAIL, 2 the run could not be carried out, 130 interrupted.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import profiles
import report
import snapshot as snapshots
import workflow as workflows
from broker import RUNNER_USER, Broker, Policy

LIB = Path(__file__).resolve().parent
CI_DIR = LIB.parent
sys.path.append(str(CI_DIR))
import pytest_phases  # noqa: E402  the workflow's own script: how "auto" workers are counted
REPO = CI_DIR.parents[1]
RESULTS = REPO / ".ci-results"
DEFAULT_STATE = Path("/var/tmp/autotramita-ci")  # noqa: S108
STATE = Path(os.environ.get("ATCI_STATE_DIR", DEFAULT_STATE))
# One file for the whole host, whatever ATCI_STATE_DIR says: every run holds it while it lives,
# so that the shared caches are never removed under a run of another state directory.
ACTIVITY_LOCK = DEFAULT_STATE / "activity.lock"
# Who created a workspace or a result directory. Written by the runner outside every directory a
# job can write to.
OWNER_FILE = ".atci-owner.json"
RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
COMPOSE_FILE = REPO / "compose.ci.yml"
LABEL = "com.autotramita.ci"
# The state directory whose run created a container, network or image: only a cleanup of the same
# state directory can tell whether that run is still active.
STATE_LABEL = f"{LABEL}.state"
PREFIX = "atci"
CACHE_VOLUMES = {"atci-uv-cache": "/cache/uv", "atci-npm-cache": "/cache/npm"}
RUNNER_UID = 1001
MIN_FREE_BYTES = 10 * 1024**3
# Workspaces, and with them the databases of the test workers, live in memory when the shared
# memory file system has this much room; several runs fit beside each other.
TMPFS = Path("/dev/shm")  # noqa: S108
TMPFS_WORK = TMPFS / "autotramita-ci-work"
MIN_TMPFS_BYTES = 16 * 1024**3
# Left to the operating system, development agents and other sessions.
RESERVED_CPUS = 4
# A targeted run has few tests: more workers, each with its own server, cost more than they save.
TARGETED_WORKERS = 4
NEEDS_EGRESS = re.compile(r"\buv sync\b|check-clients\.sh|\buvx\b")
# A step that has the pinned scanner download its databases: the job gets an egress network,
# used by that scanner container only (the broker), never by the step container itself.
SCANNER_DOWNLOAD = re.compile(r"--download-(?:java-)?db-only\b")
NEEDS_DOCKER = re.compile(r"\bdocker\b|check-clients\.sh")
# Docker's answer when none of its default subnets is free, and how long a job waits for one.
NO_FREE_SUBNET = "predefined address pools have been fully subnetted"
NETWORK_WAIT_SECONDS = 600
NETWORK_RETRY_SECONDS = 5
IMAGE_REF = re.compile(r"[a-z0-9./_-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}")

cancelled = threading.Event()
console_lock = threading.Lock()


def say(message: str) -> None:
    with console_lock:
        print(message, flush=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def docker(*args: str, check: bool = True, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(  # noqa: S603
        ["docker", *args], capture_output=True, text=True, errors="replace", **kwargs
    )
    if check and done.returncode:
        raise RuntimeError(f"docker {' '.join(args[:3])} failed: {done.stderr.strip()[-2000:]}")
    return done


def create_network(name: str, labels: list[str], job: str, wait: float) -> None:
    """Creates the egress network of a job. Docker has a fixed number of subnets, shared with
    the other stacks of the host and with simultaneous runs, so wait for one to be released. A
    job asks for one network, once, before it starts any step: waiting jobs cannot block each
    other. Any other failure, and a wait that ends without a subnet, fails the job."""
    deadline = time.monotonic() + wait
    announced = False
    while True:
        done = docker("network", "create", *labels, name, check=False)
        if not done.returncode:
            return
        if NO_FREE_SUBNET not in done.stderr or time.monotonic() >= deadline:
            break
        if not announced:
            say(f"[{job}] no free Docker subnet, waiting up to {wait:.0f} s")
            announced = True
        if cancelled.wait(NETWORK_RETRY_SECONDS):
            break
    raise RuntimeError(f"docker network create failed: {done.stderr.strip()[-2000:]}")


def owned(run_id: str | None = None) -> list[str]:
    selector = f"label={LABEL}.run={run_id}" if run_id else f"label={LABEL}=1"
    return docker("ps", "-aq", "--filter", selector).stdout.split()


def remove_containers(ids: list[str]) -> None:
    if ids:
        docker("rm", "-f", "-v", *ids, check=False)


# --- locks ---------------------------------------------------------------------------------


@contextmanager
def run_lock(run_id: str) -> Iterator[None]:
    """Held for the life of a run, so cleanup never removes the resources of a live one."""
    path = STATE / "locks" / f"{run_id}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        handle = open(path, "a", encoding="utf-8")  # noqa: SIM115  closed below
        # Only a short look by status or cleanup can hold it: this run's id is new.
        fcntl.flock(handle, fcntl.LOCK_EX)
        if same_file(handle.fileno(), path):
            break
        handle.close()  # removed between open and lock: a lock nobody could find again
    with handle:
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def same_file(descriptor: int, path: Path) -> bool:
    try:
        there = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return os.path.samestat(os.fstat(descriptor), there)


def is_active(run_id: str) -> bool:
    path = STATE / "locks" / f"{run_id}.lock"
    try:
        handle = open(path, encoding="utf-8")  # noqa: SIM115  closed below
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
    return False


def remove_stale_lock(path: Path) -> None:
    """Removes the lock file of a finished run, holding it, so a run starting under that name at
    this moment keeps a lock that can be found."""
    try:
        handle = open(path, encoding="utf-8")  # noqa: SIM115  closed below
    except FileNotFoundError:
        return
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        if same_file(handle.fileno(), path):
            path.unlink()


@contextmanager
def host_activity(exclusive: bool = False) -> Iterator[bool]:
    """Runs share this lock; removing the caches needs it alone. ``False``: it was not free."""
    private_directory(ACTIVITY_LOCK.parent)
    with open(ACTIVITY_LOCK, "a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH)
        except OSError:
            yield False
            return
        yield True


# --- ownership -----------------------------------------------------------------------------


def write_owner(directory: Path, run_id: str) -> None:
    record = {"run": run_id, "state": str(STATE)}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(directory / OWNER_FILE, flags, 0o644), "w", encoding="utf-8") as out:
        json.dump(record, out)


def read_owner(directory: Path) -> dict[str, str] | None:
    """The owner record, only if it is a regular file of the user running Local CI."""
    try:
        descriptor = os.open(directory / OWNER_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        found = os.fstat(handle.fileno())
        if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid():
            return None
        try:
            record = json.loads(handle.read(4096))
        except ValueError:
            return None
    if not isinstance(record, dict) or not all(
        isinstance(record.get(key), str) for key in ("run", "state")
    ):
        return None
    return record


def claim_workspace(root: Path, run_id: str) -> None:
    """The run's directory below a workspace root, new and marked as this run's."""
    root.mkdir(parents=True, exist_ok=True)
    problem = unsafe_directory(root, forbidden=0o022)
    if problem:
        raise RuntimeError(f"{root} {problem}")
    (root / run_id).mkdir()
    write_owner(root / run_id, run_id)


def unsafe_directory(path: Path, forbidden: int) -> str | None:
    """Why ``path`` is no directory of ours, reached without any symbolic link and closed to
    others by the permission bits in ``forbidden``; ``None`` when it is."""
    if os.path.realpath(path) != str(path):
        return "is reached through a symbolic link or is not a normalised absolute path"
    try:
        found = os.lstat(path)
    except OSError as error:
        return f"cannot be inspected: {error.strerror}"
    if not stat.S_ISDIR(found.st_mode):
        return "is not a directory"
    if found.st_uid != os.getuid():
        return "belongs to another user"
    if found.st_mode & forbidden:
        return f"is open to other users (mode {stat.S_IMODE(found.st_mode):o})"
    return None


def foreign_workspace(directory: Path) -> str | None:
    """Why cleanup must keep this entry of a workspace root; ``None`` only for a workspace that
    a run of this state directory created."""
    if not RUN_ID.fullmatch(directory.name):
        return "its name is not a run id"
    # The runner's umask leaves the directory itself writable by its owner only.
    problem = unsafe_directory(directory, forbidden=0o022)
    if problem:
        return f"it {problem}"
    owner = read_owner(directory)
    if owner is None or owner["run"] != directory.name:
        return "it has no owner record of its run"
    if owner["state"] != str(STATE):
        return f"it belongs to state directory {owner['state']}"
    return None


# --- images --------------------------------------------------------------------------------


def runner_image(flow: workflows.Workflow, log: Path) -> str:
    lock = json.loads((CI_DIR / "images.lock.json").read_text(encoding="utf-8"))
    tags = {
        "UBUNTU_IMAGE": "ubuntu:24.04",
        "NODE_IMAGE": f"node:{flow.node_version}-bookworm-slim",
        "UV_IMAGE": f"ghcr.io/astral-sh/uv:{flow.uv_version}",
    }
    arguments = {"PYTHON_VERSION": flow.python_version}
    for key, tag in tags.items():
        if tag not in lock:
            raise RuntimeError(f"no digest for {tag} in scripts/ci/images.lock.json")
        arguments[key] = f"{tag}@{lock[tag]}"
    dockerfile = (CI_DIR / "Dockerfile").read_text(encoding="utf-8")
    identity = hashlib.sha256(
        (dockerfile + json.dumps(arguments, sort_keys=True)).encode()
    ).hexdigest()[:12]
    tag = f"atci-runner:{identity}"
    with open(STATE / "build.lock", "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if docker("image", "inspect", tag, check=False).returncode == 0:
            return tag
        say(f"Building the runner image {tag} ...")
        # A separate label key: containers inherit image labels, and a container someone starts
        # from this image by hand must not look like a resource of a run.
        command = ["docker", "build", "--progress=plain", "--label", f"{LABEL}.image=1", "-t", tag]
        for key, value in arguments.items():
            command += ["--build-arg", f"{key}={value}"]
        with tempfile.TemporaryDirectory() as context, open(log, "w", encoding="utf-8") as out:
            command += ["-f", str(CI_DIR / "Dockerfile"), context]
            if subprocess.run(command, stdout=out, stderr=subprocess.STDOUT).returncode:  # noqa: S603
                raise RuntimeError(f"building the runner image failed, see {log}")
    return tag


def pull(images: set[str]) -> None:
    for image in sorted(images):
        if docker("image", "inspect", image, check=False).returncode:
            say(f"Pulling {image}")
            docker("pull", "--quiet", image)


def ensure_volumes() -> None:
    for name in CACHE_VOLUMES:
        docker("volume", "create", "--label", f"{LABEL}=1", "--label", f"{LABEL}.cache=1", name)


# --- resources -----------------------------------------------------------------------------


class Monitor(threading.Thread):
    """Samples the CPU and memory of this run's containers."""

    UNITS: ClassVar = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}

    def __init__(self, run_id: str) -> None:
        super().__init__(daemon=True)
        self.run_id = run_id
        self.done = threading.Event()
        self.samples = 0
        self.peak_memory = 0.0
        self.peak_cpu = 0.0
        self.peak_containers = 0

    def run(self) -> None:
        while not self.done.wait(2):
            ids = owned(self.run_id)
            if not ids:
                continue
            stats = docker(
                "stats", "--no-stream", "--format", "{{.CPUPerc}}\t{{.MemUsage}}", *ids, check=False
            )
            memory = cpu = 0.0
            count = 0
            for line in stats.stdout.splitlines():
                found = re.match(r"([\d.]+)%\t([\d.]+)([KMG]?i?B)", line)
                if found:
                    cpu += float(found[1])
                    memory += float(found[2]) * self.UNITS.get(found[3], 1)
                    count += 1
            if count:
                self.samples += 1
                self.peak_cpu = max(self.peak_cpu, cpu)
                self.peak_memory = max(self.peak_memory, memory)
                self.peak_containers = max(self.peak_containers, count)

    def result(self) -> dict[str, Any]:
        return {
            "peak_memory_mib": round(self.peak_memory / 1024**2),
            "peak_cpu_percent_of_core": round(self.peak_cpu),
            "peak_running_containers": self.peak_containers,
            "samples": self.samples,
        }


def locked_versions(uv_lock: str) -> dict[str, str]:
    return dict(re.findall(r'^name = "([^"]+)"\nversion = "([^"]+)"', uv_lock, re.M))


def tree_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            with suppress(OSError):
                total += os.lstat(os.path.join(root, name)).st_size
    return total


def volume_mib(name: str) -> int:
    found = docker("volume", "inspect", name, "--format", "{{.Mountpoint}}", check=False)
    return round(tree_bytes(Path(found.stdout.strip())) / 1024**2) if not found.returncode else 0


# Memory a test worker needs with its PostgreSQL server, with a wide margin (benchmark report).
WORKER_MEMORY = 1024**3


def available_memory() -> int:
    with suppress(OSError):
        found = re.search(r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)
        if found:
            return int(found[1]) * 1024
    return 0


def worker_budget(
    other_runs: int, cpus: int, memory: int, load: float = 0.0, targeted: bool = False
) -> int:
    """Workers of a run whose workflow says ``auto``: the workflow's own number, shared with the
    runs already active; fewer (but not below four) while other work keeps the CPUs busy; and no
    more than half of the free memory allows. A targeted run takes ``TARGETED_WORKERS`` at
    most."""
    share = pytest_phases.resolve_workers("auto", cpus) // (other_runs + 1)
    idle = cpus - RESERVED_CPUS - round(load)
    share = min(share, max(4, idle))
    if memory:
        share = min(share, memory // (2 * WORKER_MEMORY))
    share = max(2, share)
    return min(share, TARGETED_WORKERS) if targeted else share


def work_roots() -> list[Path]:
    return [STATE / "work", TMPFS_WORK]


def work_root() -> Path:
    """Where this run puts its job workspaces. ``ATCI_STATE_DIR`` keeps everything below it."""
    if "ATCI_STATE_DIR" not in os.environ and TMPFS.is_dir():
        if shutil.disk_usage(TMPFS).free >= MIN_TMPFS_BYTES:
            private_directory(TMPFS_WORK)  # anyone may create entries in /dev/shm: check ours
            return TMPFS_WORK
    return STATE / "work"


def active_runs(but: str) -> int:
    locks = STATE / "locks"
    found = locks.glob("*.lock") if locks.exists() else []
    return sum(1 for lock in found if lock.stem != but and is_active(lock.stem))


# --- one job -------------------------------------------------------------------------------


class JobRun:
    def __init__(self, run: Run, selection: profiles.Selection) -> None:
        self.run = run
        self.selection = selection
        self.job = selection.job
        self.project = f"{PREFIX}-{run.run_id}-{self.job.key}"
        self.workspace = run.work / run.run_id / self.job.key
        self.logs = run.directory / "logs" / self.job.key
        self.deadline = 0.0
        self.netns = ""
        self.egress = ""
        self.broker: Broker | None = None
        self.checks: list[dict[str, Any]] = []
        self.suites: list[dict[str, Any]] = []
        self.compose_env: dict[str, str] = {}
        self.workspace_mib = 0

    # infrastructure
    def prepare(self) -> None:
        ws = self.workspace
        src = ws / "src"
        steps = [*self.selection.steps, *self.selection.local]
        # The workspace root, `steps` and `junit` stay owned by the host user: code running in a
        # step cannot swap them for links that the host would then write or change ownership
        # through.
        for name in ("runner_temp", "tmp", "steps", "broker", "junit"):
            (ws / name).mkdir(parents=True, exist_ok=True)
        junit = [ws / "junit" / f"{number:02d}" for number in range(1, len(steps) + 1)]
        for directory in junit:
            directory.mkdir()
        snapshots.materialise(self.run.content, src)
        if self.selection.local:
            snapshots.export(src, ws / "export")
        (ws / "step_summary.md").touch()
        writable = [ws / "runner_temp", ws / "tmp", ws / "broker", ws / "step_summary.md", *junit]
        for path in writable:
            os.lchown(path, RUNNER_UID, RUNNER_UID)
        for tree in (src, ws / "export"):
            for root, directories, files in os.walk(tree):
                for name in [".", *directories, *files]:
                    os.lchown(os.path.join(root, name), RUNNER_UID, RUNNER_UID)
        self.start_services()
        if any(NEEDS_EGRESS.search(s.run) or SCANNER_DOWNLOAD.search(s.run) for s in steps):
            self.egress = f"{self.project}-egress"
            wait = min(NETWORK_WAIT_SECONDS, self.deadline - time.monotonic())
            create_network(self.egress, self.label_args(), self.job.key, wait)
        if any(NEEDS_DOCKER.search(step.run) for step in steps):
            policy = Policy(
                prefix=self.project,
                labels=self.labels(),
                netns=self.netns,
                workspace=self.workspace.resolve(),
                read_only_roots=(src.resolve(),),
                images=self.run.broker_images,
                egress=self.egress,
            )
            self.broker = Broker(self.workspace / "broker", policy)
            self.broker.start()

    def labels(self) -> dict[str, str]:
        return {
            LABEL: "1",
            f"{LABEL}.run": self.run.run_id,
            f"{LABEL}.job": self.job.key,
            STATE_LABEL: str(STATE),
        }

    def label_args(self) -> list[str]:
        return [word for k, v in self.labels().items() for word in ("--label", f"{k}={v}")]

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return docker(
            "compose",
            "--env-file",
            "/dev/null",  # a developer's .env must never reach the CI infrastructure
            "-f",
            str(COMPOSE_FILE),
            "-p",
            self.project,
            *args,
            check=check,
            env=self.compose_env,
        )

    def start_services(self) -> None:
        env = {k: os.environ[k] for k in ("PATH", "HOME", "DOCKER_HOST") if k in os.environ}
        env |= {
            "ATCI_PROJECT": self.project,
            "ATCI_RUN_ID": self.run.run_id,
            "ATCI_STATE": str(STATE),
            "ATCI_RUNNER_IMAGE": self.run.image,
        }
        names = ["netns"]
        flags: list[str] = []
        if self.selection.services:
            for service in self.job.services:
                key = service.name.upper()
                env[f"ATCI_{key}_IMAGE"] = service.image
                for part, value in service.health.items():
                    env[f"ATCI_{key}_HEALTH_{part}"] = value
                for variable, value in service.env.items():
                    env[f"ATCI_{variable}"] = value
                names.append(service.name)
                flags += ["--profile", service.name]
        self.compose_env = env
        began = time.monotonic()
        up = self.compose(
            *flags, "up", "--detach", "--wait", "--wait-timeout", "180", *names, check=False
        )
        (self.logs / "00-services.log").write_text(
            self.run.redact(up.stdout + up.stderr), encoding="utf-8"
        )
        if up.returncode:
            raise RuntimeError(f"services did not become healthy: {up.stderr.strip()[-800:]}")
        self.netns = self.compose("ps", "-q", "netns").stdout.strip()
        if not self.netns:
            raise RuntimeError("the network namespace container is not running")
        say(f"[{self.job.key}] services ready in {time.monotonic() - began:.1f} s: {names}")

    # steps
    def environment(self, step: workflows.Step, number: int) -> dict[str, str]:
        ws = self.workspace
        junit = ws / "junit" / f"{number:02d}"
        env = {
            "HOME": "/home/runner",
            "LANG": "C.UTF-8",
            "RUNNER_TEMP": str(ws / "runner_temp"),
            "GITHUB_STEP_SUMMARY": str(ws / "step_summary.md"),
            "UV_CACHE_DIR": "/cache/uv",
            "UV_PYTHON": self.run.flow.python_version,
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_LINK_MODE": "copy",
            "npm_config_cache": "/cache/npm",
            "PYTHONPATH": "/atci",
            "PYTEST_PLUGINS": "atci_pytest",
            "ATCI_JUNIT_DIR": str(junit),
            "ATCI_EXPORT": str(ws / "export"),
            **self.job.env,
            **step.env,
        }
        if "PYTEST_WORKERS" in env:
            if self.run.workers is not None:
                env["PYTEST_WORKERS"] = str(self.run.workers)
            elif env["PYTEST_WORKERS"] == "auto":
                env["PYTEST_WORKERS"] = str(self.run.budget["workers"])
        if not NEEDS_EGRESS.search(step.run):
            env["UV_OFFLINE"] = "1"
        if NEEDS_DOCKER.search(step.run):
            env["ATCI_BROKER_DIR"] = str(ws / "broker")
            env["TMPDIR"] = str(ws / "tmp")  # mounts made by the step stay inside the workspace
            env["PATH"] = "/atci/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        if step.name.startswith(profiles.TESTS):
            if self.selection.infra:
                env["ATCI_INFRA"] = self.selection.infra
            if self.run.tests:
                env["PYTEST_ADDOPTS"] = shlex.join(self.run.tests)
        return env

    def execute(self, step: workflows.Step, number: int) -> dict[str, Any]:
        slug = re.sub(r"[^a-z0-9]+", "-", step.name.lower()).strip("-")[:50]
        log = self.logs / f"{number:02d}-{slug}.log"
        script = self.workspace / "steps" / f"{number:02d}.sh"
        script.write_text(step.run, encoding="utf-8")
        name = f"{self.project}-s{number:02d}"
        network = self.egress if NEEDS_EGRESS.search(step.run) else f"container:{self.netns}"
        command = ["docker", "run", "--rm", "--init", "--name", name, *self.label_args()]
        command += ["--network", network, "--user", RUNNER_USER, "--cap-drop", "ALL"]
        command += ["--security-opt", "no-new-privileges:true"]
        command += [
            "-v",
            f"{self.workspace}:{self.workspace}",
            "-v",
            f"{LIB / 'container'}:/atci:ro",
        ]
        for volume, target in CACHE_VOLUMES.items():
            command += ["-v", f"{volume}:{target}"]
        for key, value in self.environment(step, number).items():
            command += ["-e", f"{key}={value}"]
        # `bash -e {0}` is what GitHub uses for a run step without an explicit shell.
        command += ["-w", str(self.workspace / "src"), self.run.image, "bash", "-e", str(script)]
        began = time.monotonic()
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            remove_containers(owned_by_job(self.run.run_id, self.job.key))

        timer = threading.Timer(max(1.0, self.deadline - began), expire)
        timer.start()
        try:
            with open(log, "w", encoding="utf-8") as out:
                process = subprocess.Popen(  # noqa: S603
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                )
                for line in process.stdout or ():
                    out.write(self.run.redact(line))
                    out.flush()
                code = process.wait()
                if timed_out.is_set():
                    out.write(f"Local CI: job timeout of {self.job.timeout_minutes} min reached\n")
                    code = code or 124
        finally:
            timer.cancel()
        seconds = round(time.monotonic() - began, 2)
        self.collect_junit(step, number)
        status = report.PASS if code == 0 else report.FAIL
        say(f"[{self.job.key}] {status} {seconds:7.1f} s  {step.name}")
        if code:
            tail = log.read_text(encoding="utf-8").splitlines()[-40:]
            say(f"----- last lines of {log} -----\n" + "\n".join(tail) + "\n-----")
        return {"status": status, "exit_code": code, "seconds": seconds, "log": str(log)}

    def collect_junit(self, step: workflows.Step, number: int) -> None:
        manifest = self.workspace / "junit" / f"{number:02d}" / "manifest.jsonl"
        if manifest.is_symlink() or not manifest.exists():
            return
        lines = manifest.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines, 1):
            record = json.loads(line)
            xml = self.safe_file(Path(record["xml"]))
            if xml is None:
                raise RuntimeError(f"JUnit file of '{step.name}' is missing")
            target = self.run.directory / "junit" / f"{self.job.key}-{number:02d}-{index}.xml"
            target.write_text(self.run.redact(xml.read_text(encoding="utf-8")), encoding="utf-8")
            self.suites.append(
                {
                    "step": step.name,
                    "file": target.name,
                    "source_name": xml.name,
                    **report.read_junit(target),
                    "deselected": record["deselected"],
                }
            )

    def safe_file(self, path: Path) -> Path | None:
        """A file written by test code is read only if it really lies inside the workspace."""
        resolved = Path(os.path.realpath(path))
        inside = self.workspace.resolve() in resolved.parents
        return resolved if inside and resolved.is_file() else None

    def keep_artifacts(self) -> None:
        for source in (
            self.workspace / "step_summary.md",
            self.workspace / "runner_temp" / "spike-results.json",
        ):
            found = self.safe_file(source)
            if found and found.stat().st_size:
                target = self.run.directory / "artifacts" / f"{self.job.key}-{found.name}"
                target.write_text(self.run.redact(found.read_text("utf-8")), encoding="utf-8")

    def go(self) -> dict[str, Any]:
        began = time.monotonic()
        self.deadline = began + self.job.timeout_minutes * 60
        self.logs.mkdir(parents=True, exist_ok=True)
        planned = [(step, False) for step in self.selection.steps]
        planned += [(step, True) for step in self.selection.local]
        self.checks = [
            {
                "name": step.name,
                "local_only": local,
                "status": report.NOT_RUN,
                "exit_code": None,
                "seconds": 0.0,
                "log": None,
            }
            for step, local in planned
        ]
        error = None
        prepared = 0.0
        try:
            if cancelled.is_set():
                raise RuntimeError("cancelled")
            self.prepare()
            prepared = round(time.monotonic() - began, 2)
            failed = False
            for number, ((step, local), check) in enumerate(
                zip(planned, self.checks, strict=True), 1
            ):
                if cancelled.is_set():
                    break
                # As on GitHub: after a failure only always()/failure() steps run. Local-only
                # checks are independent of the workflow's own steps and always run.
                if not local:
                    if step.condition == "failure()" and not failed:
                        check["status"] = report.NOT_APPLICABLE
                        continue
                    if failed and step.condition is None:
                        continue
                check.update(self.execute(step, number))
                failed = failed or (check["status"] == report.FAIL and not local)
            self.keep_artifacts()
        except Exception as problem:  # reported as a failed job, never swallowed
            error = self.run.redact(f"{type(problem).__name__}: {problem}")
            say(f"[{self.job.key}] ERROR {error}")
        finally:
            self.teardown()
        refusals = self.broker.refusals if self.broker else []
        bad = error or any(c["status"] in (report.FAIL, report.NOT_RUN) for c in self.checks)
        return {
            "key": self.job.key,
            "name": self.job.name,
            "status": report.FAIL if bad else report.PASS,
            "error": error,
            "seconds": round(time.monotonic() - began, 2),
            "prepare_seconds": prepared,
            "workspace_mib": self.workspace_mib,
            "docker_refusals": refusals,
            "checks": self.checks,
            "suites": self.suites,
        }

    def teardown(self) -> None:
        if self.broker:
            self.broker.stop()
            for image in self.broker.policy.built.values():
                docker("image", "rm", "-f", image, check=False)
        # Containers started by the steps join the netns, so they go before compose. Only they
        # carry the job label.
        remove_containers(owned_by_job(self.run.run_id, self.job.key))
        if self.compose_env:
            flags = [w for s in self.job.services for w in ("--profile", s.name)]
            self.compose(*flags, "down", "--volumes", "--remove-orphans", check=False)
        if self.egress:
            docker("network", "rm", self.egress, check=False)
        self.workspace_mib = round(tree_bytes(self.workspace) / 1024**2)
        if not self.run.keep:
            shutil.rmtree(self.workspace, ignore_errors=True)


def owned_by_job(run_id: str, job: str) -> list[str]:
    return docker(
        "ps",
        "-aq",
        "--filter",
        f"label={LABEL}.run={run_id}",
        "--filter",
        f"label={LABEL}.job={job}",
    ).stdout.split()


# --- a run ---------------------------------------------------------------------------------


class Run:
    def __init__(self, options: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        self.profile: str = options.profile
        self.ref: str | None = options.ref
        self.source = Path(options.source).resolve() if options.source else REPO
        self.serial: bool = options.serial
        self.keep: bool = options.keep_workspace
        self.tests: list[str] = options.tests
        self.workers: int | None = options.workers
        self.directory = RESULTS / self.run_id
        self.work = STATE / "work"
        self.claimed = False  # whether this run created its directory below ``work``
        self.redact = report.Redactor([])

    def execute(self) -> int:
        for name in ("logs", "junit", "artifacts"):
            (self.directory / name).mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "profile": self.profile,
            "targeted": bool(self.tests),
            "workers_override": self.workers,
            "started": now(),
            "runner_hash": runner_hash(),
            "content": {
                "commit": "?",
                "branch": "?",
                "tree": "?",
                "dirty": True,
                "changes": [],
                "excluded": [],
            },
            "versions": {},
            "jobs": [],
        }
        began = time.monotonic()
        monitor = Monitor(self.run_id)
        say(f"Local CI run {self.run_id}, profile '{self.profile}' -> {self.directory}")
        try:
            with host_activity(), run_lock(self.run_id):
                write_owner(self.directory, self.run_id)
                try:
                    self.body(summary, monitor)
                finally:
                    monitor.done.set()
                    remove_containers(owned(self.run_id))
                    if self.claimed and not self.keep:
                        shutil.rmtree(self.work / self.run_id, ignore_errors=True)
        except Exception as problem:
            summary["error"] = self.redact(f"{type(problem).__name__}: {problem}")
            say(f"ERROR {summary['error']}")
        summary["finished"] = now()
        summary["seconds"] = round(time.monotonic() - began, 1)
        summary["interrupted"] = cancelled.is_set()
        suites = [suite for job in summary["jobs"] for suite in job["suites"]]
        summary["totals"] = {key: sum(s[key] for s in suites) for key in report.COUNTS}
        summary["primary_suites"] = report.primary_suites(suites)
        summary["status"], summary["reasons"] = report.verdict(summary)
        report.write(summary, self.directory)
        point_latest(self.directory, self.profile)
        say("\n" + report.text_report(summary))
        say(f"Report: {self.directory / 'report.txt'}")
        say(f"Short summary: {self.directory / 'brief.txt'}")
        if cancelled.is_set():
            return 130
        if summary.get("error"):
            return 2
        return 0 if summary["status"] == report.PASS else 1

    def body(self, summary: dict[str, Any], monitor: Monitor) -> None:
        if docker("info", "--format", "{{.ServerVersion}}", check=False).returncode:
            raise RuntimeError("Docker is not reachable")
        free = shutil.disk_usage(STATE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"less than {MIN_FREE_BYTES // 1024**3} GiB free in {STATE}")
        self.work = work_root()
        claim_workspace(self.work, self.run_id)
        self.claimed = True
        self.content = snapshots.take(self.source, self.ref)
        summary["content"] = {
            key: getattr(self.content, key)
            for key in ("commit", "branch", "tree", "dirty", "changes", "excluded")
        }
        with tempfile.TemporaryDirectory() as temporary:
            definition = Path(temporary) / "ci.yml"
            definition.write_text(self.show(".github/workflows/ci.yml"), encoding="utf-8")
            self.flow = workflows.load(definition)
        selections = profiles.select(self.profile, self.flow)
        if self.tests and not any(
            s.name.startswith(profiles.TESTS) for sel in selections for s in sel.steps
        ):
            raise RuntimeError("--tests applies only to profiles that run the test suite")
        self.redact = report.Redactor(
            [
                env
                for job in self.flow.jobs.values()
                for env in (job.env, *(s.env for s in job.services))
            ]
        )
        steps = [s for sel in selections for s in (*sel.steps, *sel.local)]
        images = {ref for step in steps for ref in IMAGE_REF.findall(step.run)}
        contracts = self.show("openapi/check-clients.sh")
        if any("check-clients.sh" in step.run for step in steps):
            images |= set(IMAGE_REF.findall(contracts))
        self.broker_images = frozenset(images)
        services = {s.image for sel in selections if sel.services for s in sel.job.services}
        began = time.monotonic()
        self.image = runner_image(self.flow, self.directory / "logs" / "runner-image-build.log")
        pull(images | services)
        ensure_volumes()
        summary["image_preparation_seconds"] = round(time.monotonic() - began, 1)
        summary["versions"] = self.versions(images | services)
        load_before = os.getloadavg()[0]
        others, memory = active_runs(self.run_id), available_memory()
        self.budget = {
            "workers": worker_budget(
                others, os.cpu_count() or 1, memory, load_before, targeted=bool(self.tests)
            ),
            "other_active_runs": others,
            "host_load_1m": round(load_before, 2),
            "memory_available_mib": round(memory / 1024**2),
        }
        if self.workers is None:
            summary["worker_budget"] = self.budget
        monitor.start()
        workers = 1 if self.serial else len(selections)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(JobRun(self, sel).go) for sel in selections]
            # A timed wait keeps the main thread able to receive signals.
            while not all(f.done() for f in futures):
                time.sleep(0.2)
            summary["jobs"] = [f.result() for f in futures]
        monitor.done.set()
        monitor.join(timeout=15)
        if self.profile in profiles.SELFTEST_PROFILES:
            summary["jobs"].append(self.selftest())
        summary["resources"] = {
            **monitor.result(),
            "workspaces_mib": sum(j["workspace_mib"] for j in summary["jobs"]),
            **{f"{name}_mib": volume_mib(name) for name in CACHE_VOLUMES},
            "workspace_root": str(self.work),
            "host_cpus": os.cpu_count(),
            "host_load_1m_before": round(load_before, 2),
            "host_load_1m_after": round(os.getloadavg()[0], 2),
            "jobs_in_parallel": workers,
        }

    def selftest(self) -> dict[str, Any]:
        """The runner's own guard rails (host process, standard library only)."""
        name = "[local] Local CI runner self-test"
        log = self.directory / "logs" / "runner-selftest.log"
        began = time.monotonic()
        done = subprocess.run(  # noqa: S603
            [sys.executable, str(CI_DIR / "selftest.py")], capture_output=True, text=True
        )
        log.write_text(self.redact(done.stdout + done.stderr), encoding="utf-8")
        seconds = round(time.monotonic() - began, 2)
        status = report.PASS if done.returncode == 0 else report.FAIL
        say(f"[runner] {status} {seconds:7.1f} s  {name}")
        check = {
            "name": name,
            "local_only": True,
            "status": status,
            "exit_code": done.returncode,
            "seconds": seconds,
            "log": str(log),
        }
        return {
            "key": "runner",
            "name": "Local CI runner",
            "status": status,
            "error": None,
            "seconds": seconds,
            "prepare_seconds": 0.0,
            "workspace_mib": 0,
            "docker_refusals": [],
            "checks": [check],
            "suites": [],
        }

    def show(self, path: str) -> str:
        return snapshots.git(self.source, "show", f"{self.content.tree}:{path}") + "\n"

    def versions(self, images: set[str]) -> dict[str, str]:
        probe = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--label",
            f"{LABEL}=1",
            "--label",
            f"{LABEL}.run={self.run_id}",
            "--label",
            f"{STATE_LABEL}={STATE}",
            self.image,
            "bash",
            "-c",
            f'py="$(UV_PYTHON_DOWNLOADS=never uv python find {self.flow.python_version})"; '
            'echo "python=$("$py" --version)"; echo "uv=$(uv --version)"; '
            'echo "node=$(node --version)"; '
            'echo "npm=$(npm --version)"; echo "os=$(. /etc/os-release; echo $PRETTY_NAME)"',
        )
        found = dict(line.split("=", 1) for line in probe.stdout.splitlines() if "=" in line)
        locked = locked_versions(self.show("uv.lock"))
        for tool in ("ruff", "mypy", "pytest", "alembic", "openapi-spec-validator"):
            found[tool] = f"{locked.get(tool, '?')} (uv.lock)"
        engine = docker("version", "--format", "{{.Server.Version}}").stdout.strip()
        found["docker"] = (
            f"{engine}, compose {docker('compose', 'version', '--short').stdout.strip()}"
        )
        found["runner-image"] = self.image
        if "python" not in found or not found["python"]:
            raise RuntimeError(f"cannot read the runner toolchain versions: {probe.stderr[-500:]}")
        for number, image in enumerate(sorted(images), 1):
            found[f"image-{number}"] = image
        return found


def runner_hash() -> str:
    digest = hashlib.sha256()
    files = [COMPOSE_FILE, *sorted(p for p in CI_DIR.rglob("*") if p.is_file())]
    for path in files:
        if "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(REPO)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def point_latest(directory: Path, profile: str) -> None:
    for name in ("latest", f"latest-{profile}"):
        temporary = RESULTS / f".{name}.{directory.name}"
        temporary.symlink_to(directory.name)
        os.replace(temporary, RESULTS / name)


# --- status and cleanup --------------------------------------------------------------------


def result_directories() -> list[Path]:
    if not RESULTS.exists():
        return []
    return sorted(p for p in RESULTS.iterdir() if p.is_dir() and not p.is_symlink())


def status(options: argparse.Namespace) -> int:
    locks = STATE / "locks"
    active = [p.stem for p in locks.glob("*.lock") if is_active(p.stem)] if locks.exists() else []
    say(f"Active runs: {', '.join(sorted(active)) or 'none'}")
    containers = docker(
        "ps",
        "-a",
        "--filter",
        f"label={LABEL}=1",
        "--format",
        "{{.Names}}  {{.Status}}",
    ).stdout.strip()
    say(f"CI containers:\n{containers or '  none'}")
    say(f"Last {options.limit} results:")
    for directory in result_directories()[-options.limit :]:
        path = directory / "summary.json"
        if not path.exists():
            state = "running" if directory.name in active else "INCOMPLETE (no summary: not a PASS)"
            say(f"  {directory.name}  {state}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        say(
            f"  {data['run_id']}  {data['status']:<4}  {data['profile']:<11} "
            f"{data['seconds']:>7} s  {data['content']['commit'][:7]}"
            f"{' dirty' if data['content']['dirty'] else ''}"
            f"{' targeted' if data['targeted'] else ''}  "
            f"tests={data['totals']['tests']} failed={data['totals']['failed']}"
        )
    return 0


def cleanup(options: argparse.Namespace) -> int:
    """Removes only what a finished run of THIS state directory created: containers, networks and
    images with the run label, the state label and the name prefix, and workspaces with a
    matching owner record. Everything else is kept and named."""
    dry = options.dry_run
    verb = "would remove" if dry else "removing"
    labelled = f"label={LABEL}=1"
    of_a_run = f"label={LABEL}.run"

    def stale(kind: str, listing: list[str]) -> list[str]:
        chosen = []
        for line in listing:
            identifier, name, run, state = [*line.split("\t"), "", "", ""][:4]
            if not run or not name.lstrip("/").startswith(f"{PREFIX}-"):
                continue
            if state != str(STATE):
                owner = f"of state directory {state}" if state else "without an owner label"
                say(f"keeping {kind} {name}: {owner}")
                continue
            if is_active(run):
                say(f"keeping {kind} {name}: run {run} is active")
                continue
            say(f"{verb} {kind} {name}")
            chosen.append(identifier)
        return chosen

    columns = f'{{{{.Label "{LABEL}.run"}}}}\t{{{{.Label "{STATE_LABEL}"}}}}'
    containers = stale(
        "container",
        docker(
            "ps", "-a", "--filter", of_a_run, "--format", "{{.ID}}\t{{.Names}}\t" + columns
        ).stdout.splitlines(),
    )
    if not dry:
        remove_containers(containers)
    networks = stale(
        "network",
        docker(
            "network",
            "ls",
            "--filter",
            of_a_run,
            "--format",
            "{{.ID}}\t{{.Name}}\t" + columns,
        ).stdout.splitlines(),
    )
    for identifier in [] if dry else networks:
        docker("network", "rm", identifier, check=False)
    # `docker image ls` has no label column in its format: ask for each image.
    listed = docker(
        "image", "ls", "--filter", of_a_run, "--format", "{{.ID}}\t{{.Repository}}"
    ).stdout.splitlines()
    built = stale("image", [f"{line}\t{image_owner(line.split()[0])}" for line in listed])
    for identifier in [] if dry else built:
        docker("image", "rm", "-f", identifier, check=False)
    cleanup_workspaces(dry)
    locks = STATE / "locks"
    for lock in locks.glob("*.lock") if locks.exists() else []:
        if not dry:
            remove_stale_lock(lock)
    if options.caches:
        with host_activity(exclusive=True) as idle:
            busy = any(is_active(p.stem) for p in locks.glob("*.lock")) if locks.exists() else False
            if busy or not idle:
                say("keeping caches and runner images: a run is active")
            else:
                remove_caches(dry, labelled)
    if options.results_older_than is not None:
        cleanup_results(dry, options.results_older_than)
    say("Cleanup finished." if not dry else "Dry run: nothing was removed.")
    return 0


def image_owner(identifier: str) -> str:
    """``run<TAB>state`` labels of an image."""
    template = (
        f'{{{{index .Config.Labels "{LABEL}.run"}}}}\t'
        f'{{{{index .Config.Labels "{STATE_LABEL}"}}}}'
    )
    found = docker("image", "inspect", identifier, "--format", template, check=False)
    return found.stdout.rstrip("\n") if not found.returncode else "\t"


def cleanup_workspaces(dry: bool) -> None:
    verb = "would remove" if dry else "removing"
    for root in work_roots():
        if not os.path.lexists(root):
            continue
        # /dev/shm accepts entries from anyone: look at the root before looking into it.
        problem = unsafe_directory(root, forbidden=0o022)
        if problem:
            say(f"keeping everything below {root}: it {problem}")
            continue
        for directory in sorted(root.iterdir()):
            reason = foreign_workspace(directory)
            if reason:
                say(f"keeping workspace {directory}: {reason}")
            elif is_active(directory.name):
                say(f"keeping workspace {directory}: run {directory.name} is active")
            else:
                say(f"{verb} workspace {directory}")
                if not dry:
                    shutil.rmtree(directory, ignore_errors=True)


def remove_caches(dry: bool, labelled: str) -> None:
    verb = "would remove" if dry else "removing"
    volumes = docker("volume", "ls", "--filter", labelled, "--format", "{{.Name}}").stdout.split()
    for name in (v for v in volumes if v.startswith(f"{PREFIX}-")):
        say(f"{verb} cache volume {name}")
        if not dry:
            docker("volume", "rm", name, check=False)
    images = docker(
        "image",
        "ls",
        "--filter",
        f"label={LABEL}.image=1",
        "--format",
        "{{.Repository}}:{{.Tag}}",
    ).stdout.split()
    for name in (i for i in images if i.startswith("atci-runner:")):
        say(f"{verb} image {name}")
        if not dry:
            docker("image", "rm", name, check=False)


def cleanup_results(dry: bool, days: int) -> None:
    """Old result directories of this checkout. One without a summary is removed only if a run
    of this state directory made it and has ended: another state directory's run may be writing
    it."""
    verb = "would remove" if dry else "removing"
    limit = time.time() - days * 86400
    for directory in result_directories():
        if directory.stat().st_mtime >= limit or is_active(directory.name):
            continue
        owner = read_owner(directory)
        ours = owner is not None and owner["state"] == str(STATE)
        if not ours and not (directory / "summary.json").is_file():
            say(f"keeping results {directory}: unfinished, and not of this state directory")
            continue
        say(f"{verb} results {directory}")
        if not dry:
            shutil.rmtree(directory)
    for link in RESULTS.glob("latest*") if RESULTS.exists() and not dry else []:
        if not link.exists():
            link.unlink()


# --- command line --------------------------------------------------------------------------


def private_directory(path: Path) -> None:
    """Only the user running CI may enter; the containers are given their own job directory as a
    mount, so they do not need to pass through it. An existing directory is only checked, never
    changed: a mistaken ``ATCI_STATE_DIR`` such as ``/tmp`` must not lose its permissions."""
    if not path.is_absolute() or str(path) != os.path.normpath(path) or len(path.parts) < 3:
        sys.exit(f"{path} must be an absolute, normalised path below a top-level directory")
    try:
        path.mkdir(mode=0o700, parents=True)
        path.chmod(0o700)
    except FileExistsError:
        pass
    problem = unsafe_directory(path, forbidden=0o077)
    if problem:
        sys.exit(f"{path} {problem}; Local CI needs a private directory of its user")


def private_state_directory() -> None:
    """Locks, and the workspaces when memory is short, live here."""
    if os.getuid() not in (0, RUNNER_UID):
        sys.exit(f"Local CI must run as root or uid {RUNNER_UID} (workspace ownership)")
    private_directory(STATE)


def stop(signum: int, _frame: Any) -> None:
    if not cancelled.is_set():
        cancelled.set()
        say(f"Signal {signum}: stopping this run and removing its resources ...")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scripts/ci", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("profile", choices=profiles.PROFILES)
    run.add_argument("--ref", help="test the content of this commit instead of the working tree")
    run.add_argument("--source", help="test another checkout (used to prove failures fail)")
    run.add_argument("--serial", action="store_true", help="one job at a time")
    run.add_argument("--keep-workspace", action="store_true")
    run.add_argument(
        "--workers",
        type=int,
        help="override PYTEST_WORKERS of the workflow (benchmarks; not acceptance evidence)",
    )
    run.add_argument("tests", nargs="*", help="after --: pytest arguments for a targeted run")
    state = commands.add_parser("status")
    state.add_argument("--limit", type=int, default=10)
    clean = commands.add_parser("cleanup")
    clean.add_argument("--dry-run", action="store_true")
    clean.add_argument("--caches", action="store_true", help="also caches and runner images")
    clean.add_argument("--results-older-than", type=int, metavar="DAYS")
    extra: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, extra = argv[:cut], argv[cut + 1 :]
    options = parser.parse_args(argv)
    private_state_directory()
    if options.command == "status":
        return status(options)
    if options.command == "cleanup":
        return cleanup(options)
    options.tests = [*options.tests, *extra]
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, stop)

    def abort() -> None:
        cancelled.wait()
        # Repeated, because a job may be between two containers when the signal arrives.
        while True:
            remove_containers(owned(runner.run_id))
            time.sleep(1)

    os.umask(0o022)
    runner = Run(options)
    threading.Thread(target=abort, daemon=True).start()
    return runner.execute()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
