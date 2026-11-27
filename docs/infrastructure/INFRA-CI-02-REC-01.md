# INFRA-CI-02-REC-01 — Independent review remediation

Date: 2026-11-27. **Status: READY FOR INDEPENDENT VERIFICATION — not accepted.** The implementing session does not accept its own corrections. Nothing here authorizes a merge into `main`, a deployment, or a change of triggers, branch protection, job structure, Docker address pools, host firewall or broker permissions; none was made.

[Specification](INFRA-CI-02.md) · [Implementation](INFRA-CI-02-IMPLEMENTATION.md) · [Benchmark](INFRA-CI-02-BENCHMARK.md) · [Acceptance](INFRA-CI-02-ACCEPTANCE.md) · [Local CI guide](LOCAL-CI.md)

## 1. Review baseline

| Item | Value |
|---|---|
| Repository, branch | `AutoTramita-es/autotramita`, `dev` |
| Reviewed commit / tree | `1357d89a699aaf67c83acade180e7a55a8cfc08c` / `2418f7e82f0fad0c688829f2ffc8829870826c8e` |
| Reviewer | a separate read-only session on 2026-11-27; its report was returned to the owner and is not a repository file. Findings below are summarised from it |
| Verdict | **PASS WITH CONDITIONS**; no P0 |
| Evidence the reviewer confirmed on the baseline | local `20261127-145105-141d26` PASS 247.6 s; GitHub [46020259401](https://github.com/AutoTramita-es/autotramita/actions/runs/46020259401) 5/5, 479 s; comparison EQUIVALENT |

## 2. Findings and corrections

| Finding | Severity | Original finding | Correction | Implementer's state |
|---|---|---|---|---|
| REC-01 | P1-1 | The Keycloak shards shared one PostgreSQL server; roles are server-wide and `migrations/env.py` reads all of them (reviewer: 210 `undefined_object` errors in 4000 stressed executions of that query) | a PostgreSQL server per additional shard, isolation guards | RESOLVED |
| REC-02 | P1-2 | Redis namespaces built from `id()` are reused; reusing one reproduces the F1 assertion without a warning; documents named a Redis delay as the cause | `uuid4` namespaces, regression tests, documents corrected | RESOLVED (the correction); the cause of the historical failure stays unproven |
| REC-03 | P2-1 | Third GitHub run (479 s) and the final evidence missing; GitHub savings shown from two favourable runs | evidence and all three durations added, claims narrowed | RESOLVED |
| REC-04 | P2-2 | `AGENTS.md` and `LOCAL-CI.md` claimed the serial guard fails for leases and expiry | documents state what the text search sees and does not see; tests pin both | RESOLVED (documentation; the guard itself is unchanged) |
| REC-05 | P3-1 | The Keycloak inventory check compared a count: a duplicated or substituted test passed; the main suite had no check | identity-based checks for both suites, digest in the comparison | RESOLVED |
| REC-06 | P3-2 | Cleanup removed `/dev/shm` workspaces without checking ownership; another `ATCI_STATE_DIR` does not see the locks of active runs | ownership records and labels, path checks, lock corrections | RESOLVED |

### 2.1 REC-01 — PostgreSQL per Keycloak shard

- `ci.yml`, job `identity`: new variable `TEST_PG_SHARD_URLS` (ports 5451, 5452) and step "Start the PostgreSQL servers of the additional test shards": the digest of the job's service image, `--user 1001:1001`, data below `$RUNNER_TEMP` (memory-backed in Local CI), loopback only, `fsync=off`. Server logs are printed after a failure.
- The first shard keeps the service, which also holds the database of the two cluster nodes.
- `keycloak_shards.py`: `shard_environment` sets each additional shard's own `TEST_PG_ADMIN_URL`. `require_isolation` refuses shards that share a Keycloak instance, PostgreSQL server, Redis database, sink port or result file; loopback spellings count as one host, and URLs with a query or several hosts are refused. Before any shard starts, each server is asked for `pg_control_system().system_identifier`; equal or unreadable identifiers stop the run.
- `migrations/env.py` and all application code are unchanged.
- Cleanup: the servers carry the job's labels and are removed by the runner's job teardown like every step container.

### 2.2 REC-02 — Redis namespaces

- `tests/auth/security/test_security_policies.py` and `tests/audit/test_t03_isolation_rec.py` use `private_markers()` (new, `tests/auth/web_harness.py`: prefix plus `uuid4`); `tests/identity/rig.py` uses one `uuid4` namespace per rig. The security `rig` fixture was split into a generator and the fixture, with the same body, so that a test can build two rigs in a row.
- `tests/test_redis_namespaces.py` (new): two successive security rigs and two successive Keycloak rigs share no recovery marker, pending entry, sign-in state or token id **while `id()` is forced to return a constant**; a guard rejects names built from `id()` or `hash()` in tests.
- No Redis timeout, assertion or retry was changed.

What is known about the historical failure (run `20261127-132311-7e4359`):

| Observation | Fails the F1 assertion | Warning in the test's log |
|---|---|---|
| original failure | yes | none |
| injected 800 ms Redis pause (`20261127-141107-be863d`) | yes | `password recovery processing failed` |
| shared namespace (review; repeated in section 4) | yes | none |

The namespace collision is **reproduced and consistent** with the original log. The timeout is a **separate hypothesis** that the original log does not support. Neither observation records what happened in the original run: **its exact cause is unproven.**

### 2.3 REC-03 — Benchmark accuracy

BENCHMARK 8.6 (new), 9, 10 and 11 and ACCEPTANCE 4 and F8: final local and GitHub evidence of `1357d89`; the three GitHub durations 356, 387 and 479 s (median 387 s; goal of 4–6 minutes met by one of three; against the historical green-run median 36 %, 30 % and 13 % shorter); the historical inventory (2007 executions) kept apart from the INFRA-CI-02 inventory (2062); no performance is guaranteed.

### 2.4 REC-04 — Serial-test guard

The guard is a regular expression over the source of top-level test functions and what they name in the same module or import with `from tests… import`. Its limits are listed in [LOCAL-CI.md, "Writing tests"](LOCAL-CI.md#writing-tests) and pinned by tests that assert both what it sees and what it does not. `AGENTS.md` now says that listing a test is the author's task. Corrected also: the docstrings of `tests/serial_tests.py` and `tests/test_ci_parallel.py`, IMPLEMENTATION limitation 1 and decision D3. The serial list and the expression are unchanged. The reviewer's wider scan (845 test functions, `conftest.py` included) found no unlisted test with a construct the expression recognises; some lease tests run in parallel and use given time or wide margins.

### 2.5 REC-05 — Test inventory by identity

- `scripts/ci/inventory.py` (new): collects node ids (`--collect-only`), converts them to the identity pytest writes into JUnit files (parameters kept), reads results, reports missing, duplicated and unexpected identities.
- `pytest_phases.py`: unsplit, parallel and serial selections are collected before the run; they must be complementary; each part must report exactly its selection. One worker is checked too. The collection replaces the former probe for empty targeted parts.
- `keycloak_shards.py`: the count comparison is replaced; one shard is checked too.
- Fail closed: [LOCAL-CI.md, "Test inventory"](LOCAL-CI.md#test-inventory).
- The three rate-limit repetitions remain three separate pytest runs of the workflow and are not part of any inventory check.
- `compare-github.sh` now compares, besides counts, the number and digest of identities that each side printed for the main and Keycloak suites. Everything else is still compared by counts and step outcomes.

### 2.6 REC-06 — Cleanup of workspaces and other resources

While correcting P3-2 the implementer found the defect to be wider than reported: with another `ATCI_STATE_DIR` the reviewed cleanup also removed the **containers, networks and images** of active runs.

| Protection | How |
|---|---|
| Active workspaces and containers | removed only when a run of the **same** state directory made them and holds no lock |
| Cross-state conflicts | label `com.autotramita.ci.state` on containers, networks and images; owner record `.atci-owner.json` in every workspace and result directory, outside what a job can write to; a host-wide `activity.lock` keeps caches while any run lives |
| Ownership | root, workspace and record must belong to the user running Local CI |
| Unsafe paths and links | workspace roots are inspected before they are read; links, foreign names, writable-by-others directories and linked records are kept. State directories must be absolute, normalised, below a top-level directory, free of links and private; an existing directory is **never** chmod'ed (before, `ATCI_STATE_DIR=/tmp` would have set `/tmp` to 0700) |
| Lock races | a run waits for and verifies its lock file; cleanup removes a lock file only while holding it |

Resources made by an earlier runner version have no owner and are kept (none existed on the server when this was written). All regression tests use temporary directories and a stand-in for Docker.

## 3. Changed files

| File | REC |
|---|---|
| `.github/workflows/ci.yml` | 01 (one step, one variable, failure log lines in `identity`; no job, trigger, permission or existing assertion changed) |
| `scripts/ci/keycloak_shards.py` | 01, 05 |
| `scripts/ci/inventory.py` (new), `scripts/ci/pytest_phases.py`, `scripts/ci/lib/compare.py` | 05 |
| `scripts/ci/lib/runner.py`, `compose.ci.yml` | 06 |
| `scripts/ci/selftest.py` | 05, 06 |
| `tests/auth/web_harness.py`, `tests/auth/security/test_security_policies.py`, `tests/audit/test_t03_isolation_rec.py`, `tests/identity/rig.py`, `tests/test_redis_namespaces.py` (new) | 02 |
| `tests/test_ci_parallel.py` | 01, 04, 05 |
| `tests/test_ci_inventory.py` (new) | 05 |
| `tests/serial_tests.py` (docstring only) | 04 |
| `AGENTS.md`, `docs/infrastructure/*` | 02–06 |

No application code, migration, realm file, dependency, lockfile, image digest, broker file or scanner setting changed.

Changed existing tests (`tests/test_ci_parallel.py`): the calls were adapted to the new interfaces with their outcome assertions kept; the two count-based inventory tests now state the same expectations on identities; two assertions about the workflow were raised from 3 to 4 PostgreSQL image references and from "contains" to "exactly 2" loopback servers.

## 4. Evidence

### 4.1 Corrections, positive and negative

Development evidence of 2026-11-27 on the uncommitted working tree (base `1357d89`) and on scratch copies; **not acceptance evidence**. Run IDs refer to `.ci-results/` on the development server.

| REC | Positive | Negative: the defect put back, or the old code |
|---|---|---|
| 01 | Keycloak profile `20261127-184512-ffad3e` PASS, 265 tests; the three servers reported different system identifiers and each held at most 4 test roles (one test's role set) in the samples of about 3 s. Guard tests in `tests/test_ci_parallel.py` | the reviewed query of `migrations/env.py` under role churn: shared server **235** `undefined_object` errors in 4000 executions, dedicated servers **0** (throwaway containers without network, removed). With the assignment and its guard removed, 11 guard cases fail (`20261127-185037-7c2162`) |
| 02 | `tests/test_redis_namespaces.py`, 11 cases | one shared namespace: the F1 test fails with `assert (True and 0 == 1)` and **no captured log** (`20261127-184941-0d0f5c`, two tests, one worker). With a constant namespace and `id()` put back, the three rig tests and the name guard fail (`185007-8b76de`, `185037-7c2162`) |
| 03 | figures checked against the GitHub API and the local result directories | not applicable |
| 04 | the guard sees 10 synthetic cases | 9 synthetic cases it does not see, and test classes, are asserted as unseen |
| 05 | main suite and Keycloak suite pass with the inventory line; 69 cases in `tests/test_ci_inventory.py`, against real pytest output with one process and two workers | old `inventory_problem` accepted a duplicate and a substituted id; the new check rejects both. With a count comparison put back, 20 cases fail (`185037-7c2162`) |
| 06 | 15 new self-tests (49 in total) | old runner, stand-in Docker: another state directory **deleted** the active workspace and **removed** the active container; corrected code keeps both. With the state, root and state-directory checks removed, 10 self-tests fail and 1 errors |

Cleanup with the real Docker daemon (Keycloak profile; containers, networks, images of runs, workspaces and locks listed before and after):

| Run | Exit | Left afterwards |
|---|---|---|
| successful (`20261127-184512-ffad3e`) | 0 | nothing |
| failing: injected test in shard 2, scratch copy (inventory of 266 still complete) | 1 | nothing |
| interrupted with `SIGTERM` during the shard tests (`20261127-184924-6e6a0c`) | 130 | nothing |
| killed with `SIGKILL` during the shard tests (`20261127-185105-fe73a1`) | 137 | 11 containers, 1 network, 1 image, 1 workspace, 1 lock. `cleanup.sh` with another `ATCI_STATE_DIR` kept all containers, the network, image and workspace; with the own state directory it removed them and the lock; then nothing |
| during an active run, `cleanup.sh --dry-run --caches`, own and another state directory | – | every resource and the caches reported as kept |

The number of dangling anonymous Docker volumes of the host was the same before and after.

Inventory against the reviewed baseline, case by case (main suite of `20261127-145105-141d26` against the fast and integration runs `20261127-185743-7c4501` and `185610-8abe76`): 1614 → 1733, **no baseline case missing**, 119 added (`test_ci_inventory` 69, `test_ci_parallel` 39, `test_redis_namespaces` 11), none twice. The serial list is unchanged.

### 4.2 Final checkpoint

The full local run with `--ref`, the GitHub run and their comparison on the committed implementation are recorded by the documentation commit that follows it.

## 5. Deferred findings

Recorded, not accepted and not closed. Nothing was optimised.

| ID | Finding | State |
|---|---|---|
| P3-3 | Stale text: the comment in `ci.yml` (job `test`) says at most 12 workers, the limit is 16; `LOCAL-CI.md` named an old workspace path | the path was corrected because REC-06 rewrites that text; **the workflow comment is deferred** |
| P3-4 | In a targeted run with several workers a user's `-m` is silently replaced | deferred. REC-05 keeps the behaviour, takes `not keycloak` as the reference there and now documents it |
| P3-5 | The number of Keycloak shards does not adapt to load (always 3 locally) | deferred |
| P3-6 | `scripts/ci` runs mandatory GitHub steps but is outside Ruff and mypy; the runner self-test runs only locally | deferred. The REC-06 tests are part of that self-test; the REC-01 and REC-05 tests are in the main suite and run on GitHub |
| P3-7 | Baseline results of the specialised profiles exist only in another session's temporary directory; commit `852d28a` is not reachable from the branch; the worker matrix was measured on an uncommitted runner | deferred; the evidence may be lost with a cleanup of `/tmp` |
| review, section 3 | The pytest summary expression of `compare-github.sh` does not match a summary that starts with "skipped" or "error" (step outcomes are still compared) | deferred |
| F4 and opportunities | duration goals; splitting the longest Keycloak file, concurrent server starts, earlier instance starts, a separate rate-limit job | deferred; no optimisation in this package |
| host | restarting containers and heavy NVMe writes (F5), few free Docker subnets | outside this package |

## 6. Historical GitHub evidence gap (stale provider version)

Commit `81fa391` (2026-11-26) raised the security provider to 1.2.0 while the realm import step still expected 1.1.1; `6d4cb64` corrected the assertion. For the pushed commits from `81fa391` to `19908d7` (12 commits, 11 of them documentation only) **no GitHub run succeeded**:

| GitHub run | Commit | Result |
|---|---|---|
| 45897963908 | `81fa391` | failure |
| 45961202252 | `64e8355` | cancelled |
| 45961211185 | `e4fce03` | failure |
| 45962797732, 45962808186, 45963226146, 45963493616, 45964365574 | `2e811c3`, `4512e94`, `66437d9`, `825dad6`, `2d5afc4` | cancelled |
| 45965134344 | `d555212` | failure |
| 45966748646 | `9105f3f` | cancelled |
| 45967314380, 45971351879 | `4d06c67`, `19908d7` | failure |

In the five failed runs the other four jobs succeeded and the Keycloak tests step passed; the step "Import DEV and PROD realms into isolated Keycloak instances" failed, so "Without the security provider the realm signs nobody in" and the identity "Test counts" step were **skipped**. Any acceptance that relies on those commits has no green GitHub evidence for these checks. This record accepts nothing retroactively and reopens no package.

## 7. Remaining limitations

1. The serial list depends on test authors; its guard is partial (2.4).
2. The cause of the historical F1 failure is unknown; it could recur from a cause not addressed here. Fixed namespaces remain in a few tests that name them literally.
3. The inventory check compares results with the collection of the same commit; it does not notice a test that is no longer collected. Test ids must be the same in two collections.
4. `compare-github.sh` compares identities only for the main and Keycloak suites.
5. Cleanup keeps what it cannot attribute; leftovers of a deleted or unknown state directory need the same `ATCI_STATE_DIR` or removal by hand. The worker budget still counts only runs of the same state directory. Another user than the owner of `/var/tmp/autotramita-ci` cannot run Local CI at all, also with an own state directory.
6. Local CI results are produced on a machine the agent controls; GitHub remains the independent evidence.
7. The limitations of INFRA-CI-01 and INFRA-CI-02 remain (LCI-04/05; durations).

## 8. Decisions taken without explicit owner guidance

| # | Decision | Reason |
|---|---|---|
| R1 | Besides URL comparison, the servers are asked for their system identifier before any shard starts | two spellings of one address cannot be ruled out by text |
| R2 | The digest of test identities was added to `compare-github.sh` | otherwise equivalence between local and GitHub stays count-based for the two split suites |
| R3 | The serial guard was documented, not extended | the order asks for alignment; extending it would change which tests run serially |
| R4 | Unowned resources of older runner versions are never removed automatically | safety over convenience |
| R5 | An unsafe existing state directory is refused instead of repaired | changing permissions of an arbitrary directory is the greater risk |
| R6 | REC-06 covers containers, networks, images, caches, results and lock files, not only workspaces | the same cause affected them |
| R7 | The review report was read from the review session's log on this server | the order lists P3-3 to P3-7 without their text |

## 9. Rollback

`git revert` the REC-01 commits (implementation and documentation), then `./scripts/ci/cleanup.sh`. Partial: reverting the `ci.yml` step alone is not possible (the shard script requires `TEST_PG_SHARD_URLS`); `KEYCLOAK_SHARDS: "1"` runs one process without additional servers (the guard test expects `auto`). No data, schema, service or host setting needs to be restored. After a rollback the cleanup defect of P3-2 is back: do not run `cleanup.sh` with another `ATCI_STATE_DIR` while a run is active.
