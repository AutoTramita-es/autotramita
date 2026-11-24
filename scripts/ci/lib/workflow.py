"""Reads .github/workflows/ci.yml, which stays the single definition of what CI runs.

The Local CI runner supports exactly the workflow features listed here. Anything else raises
``Unsupported``: a change to the workflow that the local runner would silently ignore must stop
the run instead of producing a PASS.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RUNS_ON = "ubuntu-24.04"
TOP_KEYS = {"name", "on", True, "permissions", "concurrency", "jobs"}  # YAML 1.1 reads on: as True
JOB_KEYS = {"name", "runs-on", "timeout-minutes", "services", "env", "steps"}
STEP_KEYS = {"name", "uses", "with", "run", "if", "env"}
CONDITIONS = {None, "always()", "failure()"}
ACTIONS = {
    "actions/checkout": {"persist-credentials", "fetch-depth"},
    "astral-sh/setup-uv": {"version", "python-version", "enable-cache"},
    "actions/setup-node": {"node-version"},
}
SERVICE_PORTS = {"postgres": ["5432:5432"], "redis": ["6379:6379"]}
SERVICE_ENV = {"postgres": {"POSTGRES_PASSWORD"}, "redis": set()}
HEALTH_FLAGS = {
    "--health-cmd": "CMD",
    "--health-interval": "INTERVAL",
    "--health-timeout": "TIMEOUT",
    "--health-retries": "RETRIES",
}


class Unsupported(Exception):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    env: dict[str, str]
    health: dict[str, str]


@dataclass(frozen=True)
class Step:
    name: str
    run: str
    condition: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    key: str
    name: str
    timeout_minutes: int
    env: dict[str, str]
    services: tuple[Service, ...]
    steps: tuple[Step, ...]
    actions: tuple[str, ...]

    def step(self, prefix: str) -> Step:
        found = [s for s in self.steps if s.name == prefix] or [
            s for s in self.steps if s.name.startswith(prefix)
        ]
        if len(found) != 1:
            raise Unsupported(
                f"job '{self.key}': expected exactly one step named '{prefix}...', "
                f"found {len(found)}; update scripts/ci/lib/profiles.py"
            )
        return found[0]


@dataclass(frozen=True)
class Workflow:
    jobs: dict[str, Job]
    uv_version: str
    python_version: str
    node_version: str


def _no_expressions(value: str, where: str) -> str:
    if "${{" in value:
        raise Unsupported(f"{where}: GitHub expressions are not supported locally")
    return value


def _strings(mapping: Any, where: str) -> dict[str, str]:
    return {str(k): _no_expressions(str(v), where) for k, v in (mapping or {}).items()}


def _only(keys: Any, allowed: set[Any], where: str) -> None:
    unknown = set(keys) - allowed
    if unknown:
        raise Unsupported(f"{where}: unsupported keys {sorted(map(str, unknown))}")


def _service(name: str, raw: dict[str, Any], where: str) -> Service:
    if name not in SERVICE_PORTS:
        raise Unsupported(f"{where}: unknown service '{name}'; add it to compose.ci.yml")
    _only(raw, {"image", "env", "ports", "options"}, where)
    if raw.get("ports") != SERVICE_PORTS[name]:
        raise Unsupported(f"{where}: ports must be {SERVICE_PORTS[name]}")
    env = _strings(raw.get("env"), where)
    if set(env) != SERVICE_ENV[name]:
        raise Unsupported(f"{where}: service env must be {sorted(SERVICE_ENV[name])}")
    if "@sha256:" not in raw["image"]:
        raise Unsupported(f"{where}: image must be pinned by digest")
    words = shlex.split(raw.get("options", ""))
    if len(words) % 2:
        raise Unsupported(f"{where}: cannot read service options")
    health: dict[str, str] = {}
    for flag, value in zip(words[::2], words[1::2], strict=True):
        if flag not in HEALTH_FLAGS:
            raise Unsupported(f"{where}: unsupported service option {flag}")
        health[HEALTH_FLAGS[flag]] = value
    if set(health) != set(HEALTH_FLAGS.values()):
        raise Unsupported(f"{where}: all four health options are required")
    return Service(name, raw["image"], env, health)


def _action(step: dict[str, Any], versions: dict[str, set[str]], where: str) -> str:
    reference = step["uses"]
    name, _, ref = reference.partition("@")
    if name not in ACTIONS or not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise Unsupported(f"{where}: action '{reference}' has no local equivalent")
    if "run" in step or "if" in step or "env" in step:
        raise Unsupported(f"{where}: unsupported use of an action step")
    options = _strings(step.get("with"), where)
    _only(options, ACTIONS[name], where)
    for option, tool in (("version", "uv"), ("python-version", "python"), ("node-version", "node")):
        if option in options:
            versions[tool].add(options[option])
    return name


def load(path: Path) -> Workflow:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _only(raw, TOP_KEYS, "workflow")
    versions: dict[str, set[str]] = {"uv": set(), "python": set(), "node": set()}
    jobs: dict[str, Job] = {}
    for key, body in raw["jobs"].items():
        where = f"job '{key}'"
        _only(body, JOB_KEYS, where)
        if body.get("runs-on") != RUNS_ON:
            raise Unsupported(f"{where}: only {RUNS_ON} has a local equivalent")
        steps: list[Step] = []
        actions: list[str] = []
        for number, item in enumerate(body["steps"], 1):
            at = f"{where}, step {number}"
            _only(item, STEP_KEYS, at)
            if "uses" in item:
                actions.append(_action(item, versions, at))
                continue
            if "run" not in item or "name" not in item or "with" in item:
                raise Unsupported(f"{at}: a run step needs 'name' and 'run' only")
            if item.get("if") not in CONDITIONS:
                raise Unsupported(f"{at}: unsupported condition {item.get('if')!r}")
            steps.append(
                Step(
                    item["name"],
                    _no_expressions(item["run"], at),
                    item.get("if"),
                    _strings(item.get("env"), at),
                )
            )
        if len({s.name for s in steps}) != len(steps):
            raise Unsupported(f"{where}: step names must be unique")
        jobs[key] = Job(
            key,
            body.get("name", key),
            int(body["timeout-minutes"]),
            _strings(body.get("env"), where),
            tuple(
                _service(name, service, f"{where}, service '{name}'")
                for name, service in (body.get("services") or {}).items()
            ),
            tuple(steps),
            tuple(actions),
        )
    for tool, found in versions.items():
        if len(found) != 1:
            raise Unsupported(f"the workflow must name exactly one {tool} version, found {found}")
    return Workflow(
        jobs,
        next(iter(versions["uv"])),
        next(iter(versions["python"])),
        next(iter(versions["node"])),
    )
