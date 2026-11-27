# Local CI (INFRA-CI-01, performance: INFRA-CI-02, corrections: INFRA-CI-02-REC-01)

Runs every check of the GitHub Actions workflow on the development server, on uncommitted work, with no commit or push. **A local PASS is development feedback. It does not replace the GitHub CI evidence** required at the control points listed in [Agent rules](#rules-for-claude-code-codex-and-other-agents).

## Quick start

```sh
./scripts/ci/run-fast.sh                 # while working, about 40 s
./scripts/ci/run-all.sh                  # at the defined checkpoint, about 4.5 minutes
./scripts/ci/status.sh                   # what ran, what is running
cat .ci-results/latest/brief.txt         # last result in a few lines
cat .ci-results/latest/report.txt        # last report
```

Run from any directory; the scripts locate the repository themselves. No `uv sync`, environment variable or running service is needed on the host.

## Installation and requirements

| Requirement | Verified on this server | Note |
|---|---|---|
| Docker Engine with Compose v2 | 29.2.1, Compose 5.0.2 | used for every container |
| `python3` 3.10 or newer with PyYAML | 3.10.12, PyYAML 5.4.1 | the runner itself; standard library otherwise |
| `git` | 2.34.1 | |
| User `root` or uid 1001 | root | workspaces are handed to uid 1001, the user inside the containers |
| `gh`, logged in | 2.4.0 | only for `compare-github.sh` |
| Disk | see below | the run stops if less than 10 GiB is free |
| `/dev/shm` with 16 GiB free | 63 GiB | job workspaces and worker databases; with less room they go to disk |
| Internet | | dependency install, `npm ci`, `pip-audit`, first image pulls |

Nothing else is installed on the host and no GitHub self-hosted runner is involved. The first run builds the runner image (`atci-runner:<hash>`) and pulls the pinned service images.

Locks live in `/var/tmp/autotramita-ci`, job workspaces in `/dev/shm/autotramita-ci-work` (both mode 0700). Optional: `ATCI_STATE_DIR` moves both below one directory, on disk; `activity.lock` stays in `/var/tmp/autotramita-ci` and is shared by all state directories.

A state or workspace directory must be an absolute path below a top-level directory, reached without any symbolic link, owned by the user running Local CI and closed to everyone else. The runner creates a missing one that way and **refuses** an existing one that is not; it never changes the permissions of an existing directory (so `ATCI_STATE_DIR=/tmp` stops instead of locking the host out of `/tmp`).

### Resources (measured)

| Run | Peak memory | Peak CPU (threads of 32) | Workspaces |
|---|---|---|---|
| fast, unit | 2.4 GiB | 16 | |
| integration | 3.8 GiB | 17 | |
| keycloak | 8.6 GiB | 25 | |
| full | about 11 GiB | about 25 | about 5 GB, in memory |

Measured on 2026-11-27; conditions and all figures: [INFRA-CI-02 benchmark](INFRA-CI-02-BENCHMARK.md). Result directories stay small; caches keep about 250 MB in two Docker volumes.

Local CI shares the host with other services and agent sessions. A run whose workflow says `auto` takes fewer test workers when other runs are active, when the CPUs are already busy or when memory is short, and four at most when it is targeted (see [Parallel tests](#parallel-tests)). A run sees only the runs that were already active when it started. Use `--serial` (one job at a time) on a busy machine; `--workers 1` runs the main suite in a single process.

## Architecture

```text
.github/workflows/ci.yml      the only definition of jobs, steps, commands, images, versions
        │ read from the tested content
scripts/ci/run-*.sh ─► lib/runner.py ─┬─ lib/workflow.py   parses ci.yml, refuses what it cannot reproduce
                                      ├─ lib/profiles.py   which steps each profile runs
                                      ├─ lib/snapshot.py   the content under test (git tree)
                                      ├─ lib/broker.py     restricted stand-in for `docker`
                                      └─ lib/report.py     redaction, JUnit, verdict, reports

one job = one GitHub job
  netns (no network, loopback only) ── PostgreSQL ── Redis ── Keycloak instances ── step containers
                                       one more PostgreSQL per extra test worker (test job) or
                                       per extra Keycloak shard (identity job), one more Redis
  egress network (only for steps that run `uv sync`, `npm ci` or `uvx`)
```

**Single source of commands.** The runner executes the `run:` blocks of `ci.yml` verbatim with `bash -e`, as GitHub does. No test command is copied into the local scripts, so a change to the workflow takes effect locally at once. Versions of Python, uv and Node are read from the workflow; their base image digests are in [images.lock.json](../../scripts/ci/images.lock.json). Service and tool images are taken from `ci.yml` and `openapi/check-clients.sh`.

**Fail closed.** A job key, action, condition, expression, service or Docker flag that the runner does not know stops the run with exit code 2. If a step that a profile selects by name is renamed, the run stops too.

**Content under test.** By default the working tree: tracked changes plus untracked, not ignored files. `--ref <commit>` tests a commit instead. Each job gets its own new repository containing only that tree and the history GitHub would check out (the tested branch up to the commit, the other branches of `origin` as last fetched, tags). Files edited during a run do not affect it, and CI cannot write into the real tree. The real index, refs and files are not changed; only git objects are added.

Untracked files named like secrets (`.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, SSH keys, `*secret*.json`, `credentials*.json`) are never copied and are listed in the report. Ignored paths such as `.secrets/` are never part of the tree.

## Commands and profiles

| Command | Runs | Services | Measured |
|---|---|---|---|
| `run-fast.sh` | Ruff lint and format, mypy, tests that need no PostgreSQL or Redis, test counts, runner self-test | none | 40 s |
| `run-unit.sh` | the same tests and counts only | none | 30 s |
| `run-integration.sh` | tests that depend on the PostgreSQL or Redis fixtures (RLS, privileges, sessions, authentication, recovery, notifications, rate limiting), test counts, isolation check | PG, Redis, per worker | 95 s |
| `run-keycloak.sh` | the whole `identity` job: builds the AutoTramita Keycloak image, Keycloak tests in parallel shards (one Keycloak instance and one PostgreSQL server each) and on two nodes sharing one PostgreSQL database, DEV and PROD realm import, a realm without the provider | PG per shard, Redis, Keycloak ×5 | 3 min 40 s |
| `run-migrations.sh` | the workflow's upgrade/downgrade/upgrade step, exactly one migration head, the complete role and migration test files | PG, Redis | 27 s |
| `run-security.sh` | the `secrets`, `dependencies` and `image-scan` jobs (gitleaks, pip-audit, Trivy scan of the AutoTramita Keycloak image with its gate), gitleaks on uncommitted files | none | 55 s |
| `run-contracts.sh` | OpenAPI 3.1 validation, contract is current, TypeScript and Dart generation | none | 14 s |
| `run-all.sh` | **every job and every run step of `ci.yml`**, plus the local checks | all | 4 min 20 s |
| `compare-github.sh [dir] [--run id]` | compares a clean full run with the GitHub run of the same commit: jobs, step outcomes, counts and two [inventory digests](#test-inventory) | | seconds |
| `status.sh [--limit n]` | active runs, CI containers, recent results | | |
| `cleanup.sh [--dry-run] [--caches] [--results-older-than DAYS]` | removes leftovers | | |

Options of every `run-*.sh`:

| Option | Meaning |
|---|---|
| `--ref <commit>` | test the content of that commit, ignoring uncommitted changes |
| `--serial` | one job at a time |
| `--keep-workspace` | keep the job directories for debugging (remove with `cleanup.sh`) |
| `--source <dir>` | test another checkout |
| `--workers <n>` | override `PYTEST_WORKERS` (benchmarks); the run is not acceptance evidence |
| `-- <pytest args>` | targeted run: passed to the main test step |

Targeted tests of the component you changed:

```sh
./scripts/ci/run-integration.sh -- tests/auth/sessions
./scripts/ci/run-unit.sh -- tests/test_config.py -k url
```

A targeted run uses four test workers at most. For a handful of tests `--workers 1` (one process, no extra servers) is several seconds faster. The report of such a run is marked `TARGETED: not acceptance evidence`. If the selected paths contain no test of the profile's kind, the run fails.

**Unit and integration split.** A test counts as integration when it depends, directly or through another fixture, on `pg_admin_url` or `redis_url`. The split is made by a pytest plugin at collection time; no test is modified or marked. Deselected tests are reported as deselected, never as skipped. Unit plus integration equals the main suite of GitHub.

## Parallel tests

Introduced by INFRA-CI-02. The workflow says what runs in parallel, the same way on GitHub and locally.

| Part | How | Isolation |
|---|---|---|
| Main suite | [pytest_phases.py](../../scripts/ci/pytest_phases.py) runs the workflow's pytest command twice: all tests not marked `serial` in `PYTEST_WORKERS` pytest-xdist workers, then the `serial` tests alone. One JUnit file holds both; the [inventory](#test-inventory) is checked | per worker: a PostgreSQL server (roles are global to a server, and migrations inspect all of them) and a Redis logical database; per test, as before: its own databases and roles |
| Keycloak suite | [keycloak_shards.py](../../scripts/ci/keycloak_shards.py) runs `KEYCLOAK_SHARDS` pytest processes at once; the [inventory](#test-inventory) is checked | per shard: a Keycloak container with its own in-memory database and realm, its own SMTP and back-channel ports, Redis database and PostgreSQL server (the first shard keeps the job's service, which also holds the nodes' database). The script refuses shards that would share one of these, and asks the servers for their identity before any shard starts |
| Rate-limit regression, migrations, contracts, scans | unchanged | |

| Setting (`ci.yml`) | Value | Meaning |
|---|---|---|
| `PYTEST_WORKERS` | `auto` | one worker per CPU, at most 16 (GitHub's 4-CPU runner: 4). Local CI shares this number between simultaneous runs and lowers it on a busy host, never below 2; a targeted run takes 4 at most. `1`: one process, serial |
| `KEYCLOAK_SHARDS` | `auto` | 3 on a host with 16 or more CPUs, otherwise 2. `1`: one process |

### Writing tests

A test that races threads, sleeps, uses a lease, expiry or fixed port, or measures time belongs in [tests/serial_tests.py](../../tests/serial_tests.py). **The author lists it.** A worker takes a whole test file, except for the slow files listed in `SPLIT_FILES`, whose tests are handed out one by one and therefore must not share a module fixture. Redis keeps its keys between tests: use `uuid4` in namespaces, never the `id()` of an object (a guard in [tests/test_redis_namespaces.py](../../tests/test_redis_namespaces.py) rejects the direct forms).

What the guard in [tests/test_ci_parallel.py](../../tests/test_ci_parallel.py) actually checks:

| | |
|---|---|
| Always checked | every entry of the serial list names an existing test file or function |
| Recognised by text | `Thread(`, `ThreadPoolExecutor(`, `ProcessPoolExecutor(`, `Barrier(`, `Timer(`, `Process(`, `time.sleep(`, `asyncio.sleep(`, `time.monotonic`, `perf_counter`, `asyncio.gather`, `ThreadingTCPServer`, `serve_forever` |
| Where it looks | top-level `test_*` functions of the main suite, and the functions, classes and fixtures they name that are defined in the same module or imported with `from tests… import name` |
| **Not seen** | leases and expiry (database or Redis time), `time.time()` or `datetime` measurements, `Event.wait` and other waits not listed, `from time import sleep` or `import time as t`, fixtures taken from a `conftest.py` by argument name, helpers reached as `module.attribute`, tests inside classes, anything application code does, Keycloak test modules (never run in workers) |

A passing guard is therefore no proof that a test is safe in parallel. The examples of both rows are tests (`test_the_guard_sees_these_dependencies`, `test_the_guard_does_not_see_these_dependencies`); whoever changes the guard changes this table.

### Test inventory

A suite that runs in parts is checked by the **identities** of its tests ([inventory.py](../../scripts/ci/inventory.py)): the JUnit class name and test name, parameters included.

| Check | Guarantee |
|---|---|
| Within a run, main suite | the parallel and serial selections are disjoint and together equal the unsplit selection; each part reports exactly what it selected: nothing missing, twice or unexpected |
| Within a run, Keycloak suite | the shard results report exactly the unsplit selection |
| Fail closed | an unreadable listing or result file, counts that do not match the test cases, a nameless case, an empty selection or two tests that would be reported alike fail the run. The only repeat read as one test is pytest's own pair for a failed test whose teardown also fails (the run fails anyway) |
| `compare-github.sh` | compares **counts** (pytest summaries, count lines, commits scanned) and, for these two suites only, the printed number and SHA-256 **digest of the identities**, so equal digests mean both machines selected and reported the same set |
| Not covered by identities | the migration step, the three rate-limit repetitions (separate pytest runs on purpose; each runs every rate-limit test again) and the `[local]` checks: counts only |
| Reference | the collection of the same commit by the same pytest. A test that pytest no longer collects at all is not noticed by this check; case lists of two commits have to be compared for that |

A targeted run with several workers selects `not keycloak` whatever `-m` it was given, because the two parts replace it.

**Without Local CI**, plain `uv run pytest` is unchanged: one process, one server. `-n` additionally needs `TEST_PG_WORKER_PORT_BASE` and `TEST_REDIS_WORKERS_URL`; without them the run fails instead of sharing a server.

**Local-only checks** are marked `[local]` in reports. They can turn a run into FAIL although GitHub would pass: migration head count, network isolation, gitleaks on uncommitted files, runner self-test.

**R10** (Dart analysis) stays deferred, exactly as in the workflow. Local CI generates the Dart client and does not analyse it.

## Docker isolation

| Property | How |
|---|---|
| Separate project, network, volumes | one Compose project `atci-<run>-<job>` per job; PostgreSQL and Redis data in tmpfs |
| No published ports | nothing is published; services share a network namespace and use `127.0.0.1` as on GitHub |
| No route anywhere from tests | the namespace is created with `network_mode: none`; every full, integration, migration and Keycloak run verifies it |
| No production data or secrets | only the throwaway values written in `ci.yml`; no host environment, `.env` or `.secrets` reaches a container; `docker compose` runs with `--env-file /dev/null` |
| No real mail | tests run their own SMTP sink on `127.0.0.1:18025`; there is no Mailpit |
| Worker databases in memory | the extra PostgreSQL servers run as uid 1001 with their data in the job workspace on `/dev/shm`; they disappear with the job |
| No Docker socket | steps that call `docker` talk to a broker on the host that allows only `run`, `logs` and `rm -f` of the job's own containers, only the images named in the repository, only mounts inside the job workspace, and only the job's namespace or no network; in addition exactly the operations below (Keycloak image and its scan) |
| Unprivileged steps | uid 1001, all capabilities dropped, `no-new-privileges` |
| Parallel runs | every run has its own names, namespace and workspace; several runs may execute at once. Caches are shared and safe for concurrent use |
| Ownership | containers, networks and images carry the run and its state directory as labels; each workspace and result directory holds an owner record written outside every directory a job can write to |

### Keycloak image build and scan (F2-T09-REC, owner authorization of 2026-11-25)

The broker (`scripts/ci/lib/broker.py`, guarded by `selftest.py`) allows three more operations, nothing wider:

| Operation | Allowed only as | Refused (negative self-tests) |
|---|---|---|
| `docker build` | tag `autotramita-keycloak:ci`, context exactly `<job source>/identity/keycloak` reached without any symbolic link, build arguments `KEYCLOAK_IMAGE`/`JDK_IMAGE` naming pinned images of the workflow, run with `--network none` and `--no-cache`; the Dockerfile may only use those arguments in `FROM`, stages in `COPY --from`, pinned ARG defaults, and no parser directive (`# syntax=` pulls a frontend image), `ADD`, `--network`, `--security`, ssh, secret or cache mounts | any other tag, context, link, build flag, argument or Dockerfile construct |
| `docker save` | `--output <file>` inside the job workspace (new file, no link) of the image this job built; the file is handed to uid 1001, read only | any other image, path, existing file or link |
| scanner downloads | the pinned `aquasec/trivy` image with exactly `--cache-dir /cache image --download-db-only|--download-java-db-only --no-progress`, one cache mount; this is the **only** container placed on the job's egress network (the step container itself stays without network) | another image, argument, network flag or mount; a scan always runs with `--network none` |

The built image is removed when the job ends; `cleanup.sh` removes images of finished runs by their run label. The vulnerability databases live in the job workspace and are deleted with it. The gate `scripts/identity/scan_gate.py` fails on a missing or old database (vulnerabilities 48 h, Java 7 days), on a report of another image, another scanner version or without operating-system and Java coverage, and on every CRITICAL or HIGH finding not accepted by the owner (`identity/keycloak/vulnerability-acceptances.json`, time-limited, empty). The known boundary below applies to the scanner download as to `uv sync`.

Keycloak is not declared in [compose.ci.yml](../../compose.ci.yml): the workflow step that starts it (`docker run`, pinned by digest) is executed through the broker, so it has one definition.

**Known boundary.** Steps that need the network (`uv sync`, `npm ci`, `pip-audit`) and the scanner's database download run on a per-job bridge network. Measured from such a network: the host's PostgreSQL and Redis containers are **not** reachable, and neither is a service bound to the host's loopback. Services the host publishes on all interfaces **are** reachable through the gateway (on this server ports 22, 25, 80, 443, 587, 993, 8001, 8010, 9000). Those steps run dependency tooling, not tests, and hold no credentials. Blocking this needs host firewall rules, which Local CI does not change.

Local CI shares the Docker daemon, CPU, memory and disk with the other services of the host.

## Reading results

`.ci-results/` is ignored by git.

```text
.ci-results/
  latest  latest-all  latest-fast ...       links to the newest run (per profile)
  <run id>/
    brief.txt             verdict, identity, durations, counts, failed tests and log paths
    report.txt            readable report, ends with RESULT: PASS or FAIL
    summary.json          the same data for tools
    junit/<job>-<step>-<n>.xml    one file per pytest invocation
    junit/checks.xml      one test case per CI check, including lint, scans and audit
    logs/<job>/<step>.log
    artifacts/            step summary, Keycloak spike observations
    github-comparison.txt         after compare-github.sh
```

The report holds the run id, start and end, git SHA and branch, whether the tree was dirty, the identity (git tree hash) of the tested content with the list of uncommitted changes, a hash of the runner code, tool versions and image digests, every check with status and duration, test counts per suite and in total, and resource use. For a clean tree the tested tree hash equals `git rev-parse <sha>^{tree}`.

| Check status | Meaning |
|---|---|
| `PASS` / `FAIL` | the step ran |
| `NOT_RUN` | required but not executed (an earlier step failed, or the run was stopped); the run is FAIL |
| `NOT_APPLICABLE` | an `if: failure()` step in a run without failure |

A run is `PASS` only if every required check ran and passed and no suite has a failed, errored or skipped test or zero tests. A directory without `summary.json` is an incomplete run and never a PASS.

| Exit code | Meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| 2 | the run could not be carried out (unsupported workflow, Docker, disk, …) |
| 130 | interrupted |

Logs and JUnit files are redacted: values of password, secret and token variables, passwords in URLs, bearer tokens, JWTs and private key headers. Redaction is pattern based; do not publish results without looking at them.

## Cleanup

Every run removes its own containers (the extra PostgreSQL servers included), networks and workspaces (in `/dev/shm` and, if used, on disk), also after failure, `Ctrl-C` or `SIGTERM`. After a kill that gives no chance to react (`SIGKILL`, reboot):

```sh
./scripts/ci/cleanup.sh --dry-run     # shows what would be removed
./scripts/ci/cleanup.sh               # stale containers, networks, workspaces
./scripts/ci/cleanup.sh --caches      # also caches and the runner image
./scripts/ci/cleanup.sh --results-older-than 14
```

`cleanup.sh` removes only what a **finished run of the same state directory** created. Everything else is kept and named in its output.

| Resource | Removed only if |
|---|---|
| container, network, image | label `com.autotramita.ci.run`, name starting with `atci-`, label `com.autotramita.ci.state` equal to this state directory, and the run holds no lock |
| workspace | its root is a real directory of this user that others cannot write to; the entry has a run id as its name, is a real directory of this user, holds an owner record (a regular file of this user) naming this run and this state directory; and the run holds no lock |
| cache volumes, runner image (`--caches`) | no run of any state directory is alive (host-wide `activity.lock`) |
| results (`--results-older-than`) | old enough, not active, and either finished (has `summary.json`) or made by a run of this state directory |

Leftovers of a run with `ATCI_STATE_DIR` are removed with the same variable set: `ATCI_STATE_DIR=<dir> ./scripts/ci/cleanup.sh`. Resources created before INFRA-CI-02-REC-01 carry no owner and are kept; inspect and remove them by hand. It never runs a `prune` command. Pulled service images are left in place.

## Troubleshooting

| Symptom | Cause and action |
|---|---|
| `Unsupported: job '…'` (exit 2) | `ci.yml` uses something new. Extend `lib/workflow.py` (and `compose.ci.yml` for a service); never bypass it |
| `expected exactly one step named '…'` | a step was renamed: update `lib/profiles.py` |
| `no digest for node:… in images.lock.json` | a tool version changed: `docker pull <tag>`, add the digest |
| `Local CI refused: …` in a step log | a step asked Docker for something outside the broker policy |
| A test fails locally only, with `Network is unreachable` or a name resolution error | the test needs external network, which test steps do not have. GitHub would allow it; fix the dependency rather than the isolation |
| `uv … offline` error in a test step | the step needs a download; steps get network only if their command contains `uv sync`, `uvx` or `check-clients.sh` |
| `services did not become healthy` | see `logs/<job>/00-services.log` |
| `Local CI needs a private directory of its user` | the state or workspace directory is a link, belongs to someone else or is open to others. Choose another `ATCI_STATE_DIR`, or inspect the directory; the runner does not repair it |
| `no free Docker subnet, waiting` | the host has few free Docker networks; the job continues when another run releases one and fails after 10 minutes. `status.sh` shows the active runs; do not remove networks of other stacks |
| `pip-audit` fails without a code change | a new advisory was published, or PyPI is unreachable |
| Rate-limit timing tests fail on a loaded host | check `uptime`; rerun with `--serial`. Do not loosen the assertions |
| A test of sign-in, recovery or sessions fails once and passes again | do not assume host load. Report the run, and read the failed test's `Captured log` section: a Redis operation over the application's 500 ms often leaves a warning there (not always: `RecoveryMarkers.get` treats the error as "no marker" without logging). Without a warning, do not assume a timeout; look for shared state first (an inherited Redis namespace reproduces such a failure silently, [INFRA-CI-02-REC-01](INFRA-CI-02-REC-01.md)). A rerun that passes explains nothing |
| `inventory:` message from `pytest_phases` or `keycloak_shards` | the tests that ran are not the tests that were selected; the message names them. Usual causes: a test id that changes between two collections (random or time-based parameters), a test process that died |
| `keeping container/workspace …` from `cleanup.sh` | the resource is not provably a finished one of this state directory; the message says why ([Cleanup](#cleanup)) |
| A test fails only in parallel | rerun it with `--workers 1`; if it then passes, it depends on timing (add it to `tests/serial_tests.py`) or on shared state (fix the test) |
| `parallel workers need … of their own` | `-n` without the worker settings; use Local CI or run without `-n` |
| `pytest_phases:` or `keycloak_shards:` message, exit 2 | the script refused the command, or a file named in `LAYOUTS`/`SPLIT_FILES` was renamed |
| gitleaks scans an unexpected number of commits | refresh branches with `git fetch origin`; this clone fetches only `main` by default |
| `[local] gitleaks on the files under test` fails | a secret-like string is in a file you have not committed yet: remove it before committing |
| Disk filling up | `cleanup.sh --results-older-than 14`, `cleanup.sh --caches` |
| Debugging a job | `--keep-workspace`, inspect `/dev/shm/autotramita-ci-work/<run>/<job>/` (or `<state directory>/work/<run>/<job>/` when workspaces are on disk) |

## Rules for Claude Code, Codex and other agents

Proposed workflow (to be confirmed by the owner):

1. Implement the change.
2. `run-fast.sh`.
3. Targeted tests of the changed components (`run-unit.sh -- <paths>`, `run-integration.sh -- <paths>`, `run-keycloak.sh` for identity changes, `run-migrations.sh` for migrations).
4. Fix and repeat. Do not push each intermediate correction.
5. `run-all.sh` before finishing a T package (the defined checkpoint).
6. Commit and push to `dev`.
7. GitHub Actions final check; optionally `compare-github.sh`.
8. Acceptance report.
9. Owner acceptance.

GitHub CI stays mandatory for: completion of a T package, CP control points, completion of a phase, release and merge into `main`.

Agents must:

- report the run id, tested SHA and tree, and whether the tree was dirty;
- never describe a targeted, partial or dirty-tree run as acceptance evidence;
- never report PASS for exit code other than 0;
- add a concurrent or timing-dependent test to `tests/serial_tests.py`, and never move a test out of that list to gain time without proof that it still tests the same thing in parallel;
- change workflow triggers, branch protection, the broker policy, host firewall rules or production infrastructure only with the owner's separate approval;
- not weaken, skip or deselect tests, edit `images.lock.json` digests or widen the broker policy to make a run pass;
- not run test containers by hand on fixed ports when a profile covers the need;
- clean up only with `cleanup.sh`, never with `docker … prune`;
- in a shared working tree, remember that the default run includes other sessions' uncommitted files. Use `--ref` to test a commit alone, and stage commits by explicit path.

## Local CI compared with GitHub CI

Same: workflow steps and order, commands, shell, job separation, timeouts, `if: always()` / `if: failure()`, service and tool images by digest, service health checks, Python 3.12.16 (uv managed), uv 0.13.9, Node 20.20.0, `uv.lock`, npm lockfile, unprivileged uid 1001.

| Difference | GitHub | Local | Effect |
|---|---|---|---|
| Parallelism | 4 test workers, 2 Keycloak shards (4 CPUs) | up to 16 workers, 3 shards | same tests and assertions; other interleaving |
| Worker and shard databases | runner disk, `fsync=off` | `/dev/shm`, `fsync=off` | the primary services are configured as before |
| Machine | `ubuntu-24.04` VM image, updated by GitHub | `ubuntu:24.04` container; apt packages (curl, git, jq, python3) not version pinned; host kernel 5.15 | tools outside the lockfiles may differ |
| CPU and load | small dedicated VM | 32 threads shared with other services | timing-sensitive tests can differ in either direction |
| Network in test steps | open | loopback only | stricter locally |
| Services | service containers, disk | same images, tmpfs, shared namespace | no persistence either way |
| Host | dedicated VM per job | shared development server | see the resource budget above |
| Docker in steps | direct | broker, namespace instead of host network | new Docker usage must be added to the broker |
| Node in `identity` | whatever the VM provides | 20.20.0 | not used by those tests |
| Platform variables | `GITHUB_*` set | only `RUNNER_TEMP`, `GITHUB_STEP_SUMMARY`, and the workflow's `env` | a step relying on others fails locally |
| `sudo` | available | not available | none today |
| Content | pushed commit | working tree or `--ref` | local can test unpushed work |
| History scanned | all remote branches at checkout | tested branch plus `origin` branches as last fetched | fetch first for equality |
| Advisory database | at run time | at run time | results can differ between times |
| Triggers, concurrency cancel, permissions | enforced | not applicable | |
| Extra checks | none | four `[local]` checks | local is stricter |
| Trust | independent, logged by GitHub | produced on a machine the agent controls | the reason GitHub stays mandatory |

The runner's own code under `scripts/ci/` is outside the project's Ruff and mypy scope (`scripts` is excluded) and its self-test runs only locally (in `run-fast.sh` and `run-all.sh`).

## Proposed future GitHub Actions triggers (not applied)

Observed on 2026-11-24: 100 listed workflow runs in one day (62 success, 18 failure, 20 cancelled), about 5.3 minutes each. The repository is public, so GitHub-hosted minutes are not billed; the gain is less waiting and less noise. `main` and `dev` have no branch protection and no ruleset.

Proposal, each point for separate owner approval:

1. **Triggers.** Keep `pull_request` and `push` for `main`. Replace `push` on `dev` with `workflow_dispatch`, started at the end of a T package, at CP points and at the end of a phase:
   ```yaml
   on:
     push:
       branches: [main]
     pull_request:
       branches: [main, dev]
     workflow_dispatch:
   ```
   `gh workflow run ci.yml --ref dev`. The risk is a forgotten run: an acceptance report without a GitHub run id for its SHA must be rejected. A cautious first step is to keep `push` on `dev` for two weeks while comparing local and GitHub results.
2. `compare-github.sh` needs `event=push` replaced by the dispatch event, or `--run <id>`, once point 1 is applied.
3. **No `paths-ignore` for documentation.** The secret scan reads documentation too and has flagged a document before (REC-07.4).
4. **Branch protection for `main`:** pull request required, the four job names as required status checks, no force push. For `dev`: no force push; no required checks, so the direct push flow keeps working.
5. **Optional:** add `python3 scripts/ci/selftest.py` as a workflow step so that a change which breaks Local CI is noticed on GitHub.
