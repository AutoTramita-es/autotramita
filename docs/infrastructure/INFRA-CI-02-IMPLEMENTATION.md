# INFRA-CI-02 — Implementation

Date: 2026-11-27. Specification and owner authorizations: [INFRA-CI-02.md](INFRA-CI-02.md) (sections 1–9). Measurements: [INFRA-CI-02-BENCHMARK.md](INFRA-CI-02-BENCHMARK.md). Verdict and evidence: [INFRA-CI-02-ACCEPTANCE.md](INFRA-CI-02-ACCEPTANCE.md). How to use Local CI: [LOCAL-CI.md](LOCAL-CI.md).

The existing Local CI runner was extended. `ci.yml` remains the single definition of what runs, locally and on GitHub. Triggers, concurrency, permissions, job names, the Docker broker policy, host firewall and production infrastructure are unchanged.

## 1. What changed

### 1.1 Main test suite in parallel

- `scripts/ci/pytest_phases.py` (new) takes the workflow's pytest command and runs it as two complementary selections: `-m "not keycloak and not serial"` in pytest-xdist workers (`--dist loadfile`), then `-m "serial and not keycloak"` alone. Both always run; the first failure is the exit code; the two JUnit files are joined into the one the unchanged "Test counts" step reads. A part that selects nothing fails the run (except in a targeted run). One worker runs the original single command.
- `PYTEST_WORKERS: "auto"`: one worker per usable CPU, at most `AUTO_LIMIT` (16, from the benchmark matrix).
- `tests/serial_tests.py` (new) lists the tests that run alone: the whole rate-limit file and every test that races threads, sleeps, uses leases or expiry, a fixed port or measured time. `tests/conftest.py` gives them the `serial` marker. A guard test derives the same set statically and fails when a test is missing from the list or a listed name no longer exists.
- Slow files whose tests each build their own state are handed to workers test by test (`SPLIT_FILES`; a small subclass of xdist's file scheduler in `tests/conftest.py`).
- `pytest-xdist` 3.8.0 (and `execnet` 2.1.2) added to the development dependencies and `uv.lock`. No other locked version changed.

### 1.2 Isolation per worker

| Resource | Isolation |
|---|---|
| PostgreSQL | one server per worker: `gw0` the job's service, `gwN` a server on port 5440+N from the service's pinned image, loopback only, uid 1001, data in the job's temporary directory |
| Redis | `gw0` the service; `gwN` logical database N of one extra server (64 databases, port 6440, loopback, no persistence) |
| Databases and roles | per test, unchanged |
| Files | pytest temporary directories per worker |
| Ports | tests that bind fixed ports are serial |

**Why a server per worker.** The first parallel run with one shared server failed one test: `migrations/env.py` reads every role of the server during each migration, and met a role another worker was dropping. Unique database and role names are therefore not enough. Application code was not changed. A shared server is refused: a worker without its own URL raises an error.

A guard checks that the worker servers use the digest of the service image.

### 1.3 Keycloak tests in shards

- `scripts/ci/keycloak_shards.py` (new) runs the identity tests as `KEYCLOAK_SHARDS` simultaneous pytest processes (`auto`: 3 with 16 or more CPUs, otherwise 2). Each additional shard has its own Keycloak container (own in-memory database), a realm generated from `realm-test.json` with other SMTP and back-channel ports (the step verifies the substitution), and its own Redis logical database. The first shard keeps the two cluster nodes and takes every file no other shard names, so a new test file is never lost.
- Before the shards start, the suite is collected as a whole; afterwards the number of distinct executed tests must equal it. The JUnit files are joined into `junit-identity.xml`; spike observations are merged.
- `tests/identity/kc.py`: the two sink ports can be set by environment variables (defaults unchanged).

### 1.4 Verification instances

After the tests, the shard and node containers are removed and the DEV, PROD and providerless instances start together instead of one after another; each is then verified by the same assertions as before. The only change in the Python checks is that the base URL's port comes from the step (DEV 18082, PROD 18087). The upstream (providerless) instance has its own start step, named so that the existing guard test "after the build every node runs the built image" keeps covering every start of the built image.

### 1.5 Local CI runner

| Change | File |
|---|---|
| Job workspaces (and with them worker databases) on `/dev/shm` when 16 GiB are free, otherwise on disk; the directory must be owned by the runner's user; `cleanup.sh` looks in both places | `lib/runner.py` |
| Worker budget: `auto` shared between simultaneous runs, reduced under CPU load (not below 4 for that reason) and by free memory (not below 2); written into the report | `lib/runner.py`, `lib/report.py` |
| At most 4 workers for a targeted run (16 made small selections slower than the former serial run) | `lib/runner.py` |
| A job waits up to 10 minutes for a free Docker subnet instead of failing at once | `lib/runner.py` |
| `--workers N` for benchmarks, marked as not acceptance evidence; `compare-github.sh` refuses such a run | `lib/runner.py`, `lib/compare.py` |
| xdist support in the pytest plugin: workers apply the unit/integration split and report the deselected count; only the controller records the run | `lib/container/atci_pytest.py` |
| Suites that ran in parts are counted as one in "Primary suite" | `lib/report.py` |
| `brief.txt`: short summary with failed tests and log paths | `lib/report.py` |
| The integration profile includes the step that starts the worker servers | `lib/profiles.py` |
| `compare-github.sh` compares the pytest summaries of a sharded job as their sum (GitHub runs 2 shards, Local CI 3) | `lib/compare.py` |
| Self-test: 22 → 34 tests | `selftest.py` |

### 1.6 Agent instructions

`AGENTS.md` and `CLAUDE.md` (new, repository root) point to the rules in LOCAL-CI.md instead of repeating the policy.

### 1.7 A pre-existing CI failure fixed first

Commit `81fa391` raised the Keycloak security provider to 1.2.0 and updated its Python test and README, but the realm import step of `ci.yml` still expected 1.1.1, so the identity job failed on `dev` from 2026-11-26. The expected version in that one assertion was changed to `1.2.0` in a separate commit. Without it two identity steps do not run and no complete baseline exists.

## 2. Affected files

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | test job: worker settings, worker server step, test command through `pytest_phases.py`; identity job: shard settings, shard start step, step order, verification instances started together, shard runner, failure logs |
| `scripts/ci/pytest_phases.py`, `keycloak_shards.py`, `junit_merge.py` | new |
| `scripts/ci/lib/{runner,report,profiles,compare}.py`, `lib/container/atci_pytest.py`, `selftest.py` | section 1.5 |
| `tests/conftest.py`, `tests/serial_tests.py`, `tests/test_ci_parallel.py`, `tests/identity/kc.py` | markers, isolation, scheduler, guards |
| `pyproject.toml`, `uv.lock` | pytest-xdist, `serial` marker |
| `AGENTS.md`, `CLAUDE.md`, `docs/infrastructure/*` | documentation |

No application code, migration, realm file, existing test assertion, `compose.ci.yml`, image digest list or broker file changed. The existing tests of the workflow (`tests/test_ci_workflow.py`, `tests/identity/test_identity_environment.py`) pass unmodified.

## 3. Decisions

Taken without explicit owner guidance; each can be reversed.

| # | Decision | Reason |
|---|---|---|
| D1 | Fix the stale provider version in `ci.yml` (separate commit) | section 1.7 |
| D2 | A PostgreSQL server per worker instead of one shared server | section 1.2 |
| D3 | Serial list in one file with a static guard, not decorators in the test files | one place to review; no edits in test files other sessions work on |
| D4 | Wrapper scripts called by the workflow, not logic in the runner | GitHub and Local CI run exactly the same thing |
| D5 | Workspaces on `/dev/shm` instead of a new broker flag (`--tmpfs`) | tmpfs without widening the Docker broker |
| D6 | Automatic selection of tests by changed paths **not implemented** (optimization 4, "if beneficial") | with FAST at about 40 s and targeted runs available, a path-to-test mapping saves little and can silently miss a dependency |
| D7 | **No new caches** (optimization 5) | measured candidates are not on the critical path (Trivy database download, client generation, image build) or would add shared state writable by test code (a mypy cache, about 15 s) |
| D8 | Verification instances start after the tests, not before | measured: an early start with a heap limit saved 8 s alone and nothing under load, and changed the JVM settings of the instances under test |
| D9 | Benchmark matrix also with 2 workers; serial reference measured beside load once | specification section 3 names 2; see BENCHMARK for repetitions |
| D10 | Wait for a Docker subnet (no host setting changed, no network of another stack removed) | two simultaneous full runs exhausted the default address pools and one failed |
| D11 | Targeted runs: at most 4 workers | measured on four selections; small selections remain a few seconds slower than the former serial run (`--workers 1` avoids it), larger ones are faster |
| D12 | The load-sensitive failure (limitation 9) was **not** worked around: no test moved, retried or changed | moving one test would hide one case of a general dependency; the decision belongs to review and the owner |
| D13 | The comparison tool sums the summaries of a sharded job | the first comparison reported DIFFERENT only because the shard counts differ; totals of every outcome must still be equal |

## 4. Limitations

1. Parallel tests change which tests run next to each other. The serial list is the safeguard; its static guard recognises threads, sleeps, timers and monotonic or performance clocks, not every possible timing dependency (for example one hidden behind database time).
2. The guard for split files rejects module, class, package and session fixtures; it cannot see state shared through module variables.
3. One scheduler hook uses a private method of pytest-xdist; the version is locked and a test covers the grouping.
4. The shard layout is a fixed list balanced by today's durations. It stays correct when files are added (they go to the first shard) but can become unbalanced.
5. The longest Keycloak file (`test_second_factor_keycloak.py`) runs on one instance and bounds the shard step.
6. Local CI uses more memory and CPU than before and shares the host with other services. The budget counts active CI runs, load and free memory; it does not reserve resources, and cannot see a run that starts later.
7. Worker data on `/dev/shm` uses RAM until the run ends; after a `SIGKILL` or reboot-free crash `cleanup.sh` removes it.
8. GitHub runs 4 workers and 2 shards, Local CI more: the same tests and assertions, a different interleaving.
9. **Load sensitivity.** The application gives a Redis operation 500 ms, and some paths (password recovery, change detection) only log a failure. On a heavily loaded host a test of such a path can fail although the code is correct: one failure of `test_a_sign_in_that_saw_the_change_first_leaves_the_check_nothing_to_do` was seen beside a second full run; an injected stall reproduces its exact assertion. The run fails (never a false pass). More parallel work makes such load more likely.
10. The worker budget counts only runs already active when a run starts.
11. The limitations of INFRA-CI-01 remain (LCI-04/05: network-enabled steps reach host services published on all interfaces).

## 5. Rollback

| Goal | Action |
|---|---|
| Serial main suite, everything else kept | in `ci.yml` set `PYTEST_WORKERS: "1"` (the guard test in `tests/test_ci_parallel.py` expects `auto` and must change with it) |
| One Keycloak process | `KEYCLOAK_SHARDS: "1"` (the additional instances are then not started) |
| Complete rollback | `git revert` the INFRA-CI-02 implementation commit(s); keep the provider version commit, otherwise the identity job fails again. Then `./scripts/ci/cleanup.sh --caches` is optional |

No data, schema, service or host setting needs to be restored.
