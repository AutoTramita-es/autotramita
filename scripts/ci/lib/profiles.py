"""Which workflow steps each profile runs. Commands are never written here for a check that
GitHub also runs: steps are selected from ci.yml by name. The ``LOCAL_*`` entries are the only
commands that exist locally and not on GitHub; they are labelled as such in every report."""

from __future__ import annotations

from dataclasses import dataclass, field

from workflow import Job, Step, Unsupported, Workflow

INSTALL = "Install locked dependencies"
WAIT = "Wait for PostgreSQL and Redis"
WORKERS = "Start the servers of the additional test workers"
TESTS = "Tests ("
COUNTS = "Test counts"

LOCAL_HEADS = Step(
    "[local] Exactly one migration head",
    'heads="$(uv run --locked alembic heads)"\n'
    'echo "$heads"\n'
    'test "$(grep -c \'(head)\' <<<"$heads")" = 1\n',
)
LOCAL_ROLE_FILES = Step(
    "[local] Database roles, privileges and migration tests (whole files)",
    "uv run --locked pytest -q -ra tests/test_role_sql.py tests/test_roles_and_migrations.py "
    "-W error -W 'ignore:Using `httpx` with `starlette.testclient` is deprecated:Warning'\n",
)


LOCAL_ISOLATION = Step(
    "[local] The test network is isolated (loopback only, no route, no Docker socket)",
    """python3 - <<'PY'
import os, socket, sys
problems = []
routes = open("/proc/net/route").read().splitlines()[1:]
if routes:
    problems.append(f"the namespace has IPv4 routes: {routes}")
for host, port in (("1.1.1.1", 443), ("172.17.0.1", 22), ("10.0.0.1", 5432)):
    try:
        socket.create_connection((host, port), timeout=3).close()
        problems.append(f"reached {host}:{port}")
    except OSError as error:
        print(f"{host}:{port} not reachable: {error}")
try:
    socket.getaddrinfo("github.com", 443)
    problems.append("external names resolve")
except OSError:
    print("no external name resolution")
if os.path.exists("/var/run/docker.sock"):
    problems.append("the Docker socket is mounted")
sys.exit("; ".join(problems) if problems else 0)
PY
""",
)


def local_worktree_scan(gitleaks_image: str) -> Step:
    return Step(
        "[local] gitleaks on the files under test, including uncommitted ones",
        'cd "$ATCI_EXPORT"\n'
        f'docker run --rm -v "$PWD:/repo" {gitleaks_image} '
        "detect --no-git --source /repo --redact --no-banner --exit-code 1 --verbose\n",
    )


@dataclass
class Selection:
    job: Job
    steps: list[Step]
    services: bool = True
    local: list[Step] = field(default_factory=list)
    infra: str | None = None  # "only" / "exclude": split of the test suite


def _job(workflow: Workflow, key: str) -> Job:
    if key not in workflow.jobs:
        raise Unsupported(f"the workflow has no job '{key}'; update scripts/ci/lib/profiles.py")
    return workflow.jobs[key]


def _pick(job: Job, *names: str) -> list[Step]:
    chosen = [job.step(name) for name in names]
    return [step for step in job.steps if step in chosen]  # keep the workflow order


def gitleaks_image(workflow: Workflow) -> str:
    for job in workflow.jobs.values():
        for step in job.steps:
            for word in step.run.split():
                if word.startswith("zricethezav/gitleaks:"):
                    return word
    raise Unsupported("no gitleaks image found in the workflow")


def select(profile: str, workflow: Workflow) -> list[Selection]:
    if profile in ("fast", "unit"):
        job = _job(workflow, "test")
        lint = ("Ruff lint", "Ruff format", "mypy") if profile == "fast" else ()
        steps = _pick(job, INSTALL, *lint, TESTS, COUNTS)
        return [Selection(job, steps, services=False, infra="exclude")]
    if profile == "integration":
        job = _job(workflow, "test")
        steps = _pick(job, INSTALL, WAIT, WORKERS, TESTS, COUNTS)
        return [Selection(job, steps, infra="only", local=[LOCAL_ISOLATION])]
    if profile == "migrations":
        job = _job(workflow, "test")
        steps = _pick(job, INSTALL, WAIT, "Owner migrations")
        local = [LOCAL_HEADS, LOCAL_ROLE_FILES, LOCAL_ISOLATION]
        return [Selection(job, steps, local=local)]
    if profile == "contracts":
        job = _job(workflow, "test")
        steps = _pick(
            job, INSTALL, "OpenAPI specification", "OpenAPI contract", "TypeScript and Dart"
        )
        return [Selection(job, steps, services=False)]
    if profile == "keycloak":
        job = _job(workflow, "identity")
        return [Selection(job, list(job.steps), local=[LOCAL_ISOLATION])]
    scan = local_worktree_scan(gitleaks_image(workflow))
    if profile == "security":
        secrets, dependencies = _job(workflow, "secrets"), _job(workflow, "dependencies")
        scanner = _job(workflow, "image-scan")
        return [
            Selection(secrets, list(secrets.steps), local=[scan]),
            Selection(dependencies, list(dependencies.steps)),
            Selection(scanner, list(scanner.steps), services=False),
        ]
    if profile == "all":
        # Every job and every step of the workflow, including any added later.
        local = {
            "test": [LOCAL_HEADS, LOCAL_ISOLATION],
            "identity": [LOCAL_ISOLATION],
            "secrets": [scan],
        }
        missing = set(local) - set(workflow.jobs)
        if missing:
            raise Unsupported(f"the workflow has no job {sorted(missing)}")
        return [
            Selection(job, list(job.steps), local=local.get(key, []))
            for key, job in workflow.jobs.items()
        ]
    raise Unsupported(f"unknown profile '{profile}'")


# Profiles that also run scripts/ci/selftest.py, the guard rails of the runner itself.
SELFTEST_PROFILES = frozenset({"all", "fast"})
PROFILES = (
    "all",
    "fast",
    "unit",
    "integration",
    "keycloak",
    "migrations",
    "security",
    "contracts",
)
