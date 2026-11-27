# INFRA-CI-02 — Acceptance report

Date: 2026-11-27. **Status: evidence collection in progress; not accepted.** The implementing session does not accept its own work: an independent read-only review in a separate session and the owner's acceptance are required. Nothing here accepts a checkpoint, authorizes a merge into `main` or a deployment.

[Specification](INFRA-CI-02.md) · [Implementation](INFRA-CI-02-IMPLEMENTATION.md) · [Benchmark](INFRA-CI-02-BENCHMARK.md) · [Local CI guide](LOCAL-CI.md)

## 1. Revisions

| Item | SHA |
|---|---|
| Head of `dev` before the implementation commits | `19908d7c43fde892217a086a64638270b6d529f6` |
| Fix of the stale provider version in `ci.yml` (precondition, see IMPLEMENTATION 1.7) | `6d4cb64` |
| Parallel test execution and runner changes | `2781c10540f31ae66cee5beb31b476ead3cded70` |
| Runner: wait for a free Docker subnet | `6d6307d46449e1cae3e218fe1596bfe56fb3db80` |
| Runner: targeted runs take at most four workers (**last code change**) | `3103631a94dc245cf40b63e5ebeb05ab0fbfe1b9` |
| Baseline used for comparisons | `852d28a` (the first commit as measured before a rebase; same change as `6d4cb64`) |

Between `19908d7` and `3103631` nothing changed under `app/`, `migrations/`, `identity/`, `openapi/`, `scripts/identity/`, in the Docker broker, the workflow parser, `compose.ci.yml`, `images.lock.json`, the compose files, `tests/test_ci_workflow.py` or `tests/identity/test_identity_environment.py` (`git diff --stat` empty). Workflow triggers, permissions, concurrency and job names are unchanged.

## 2. Acceptance matrix

State is the implementer's assessment for the reviewer to confirm.

| # | Criterion (specification section 5 and 3) | State | Evidence |
|---|---|---|---|
| A1 | Mandatory tests, warning policy, RLS and tenant isolation, migrations, authentication and MFA, API contracts, secret history scan, dependency audit and image scan remain | met | same workflow steps; `-W error` and the rate-limit repetitions unchanged; case-by-case inventory (BENCHMARK 9); protected paths unchanged (section 1) |
| A2 | INFRA-CI-01 limitations preserved; no new access, credentials, shared mutable state, firewall or broker change | met | broker unchanged; new servers are loopback-only inside the job's namespace, throwaway data, one PostgreSQL per worker and one Redis database per worker or shard |
| A3 | Scanner database age limits, pinned tools, owner-only vulnerability acceptances | met | files unchanged; additional servers use the pinned service digests (guard test) |
| A4a | Equivalent serial and parallel inventories and results | met | BENCHMARK 9: no case missing, 55 guard tests added, all passed |
| A4b | Repeatability | **partly** | six of six single full runs passed (`2781c10`, `6d6307d`); under two simultaneous full runs one test failed once (finding F1) |
| A4c | Fail-closed behaviour | met | guard tests for failing, empty and interrupted parts and for a missing Keycloak test; both observed failures were reported FAIL |
| A4d | Isolated workers, safe cleanup, no prune | met | guard tests refuse shared servers; after the measurements no CI container, network or workspace remained; no `docker … prune` |
| A5 | Local and GitHub parity on the same clean SHA, independent GitHub success | see section 4 | |
| A6 | Benchmark, limitations, deferred findings, rollback | met | BENCHMARK, IMPLEMENTATION 4 and 5, section 5 |
| A7 | No application feature, F2 decision, production or deployment change | met | section 1 |
| O1 | Benchmark of 1/2/4/8/12/16/24/32 workers, isolated and beside full CI, with resources | met | BENCHMARK 6; cold caches not measured; per-test timing from JUnit instead of `--durations` |
| O2, O3 | Parallel main suite and Keycloak groups with isolation | met | IMPLEMENTATION 1.1–1.4 |
| O4 | Automatic targeted selection "if beneficial" | not implemented | decision D6 |
| O5 | Cache improvements only after measurement | none made | decision D7 |
| O6 | `CLAUDE.md`, `AGENTS.md`, short summaries | met | repository root; `brief.txt` |
| O7 | Trigger changes only with owner approval | not changed | |
| T | Duration targets (goals, not thresholds) | **partly; full local 2–3 min not reached** | BENCHMARK 10 |

## 3. Local CI evidence

All runs: clean committed content (`--ref`), not targeted, no worker override.

| Commit | Tree | Full runs | Result | Test executions | Duration |
|---|---|---|---|---|---|
| `2781c10` | `a3e8c2d266021a64b61560a6fcbd0a06c35af674` | `20261127-122038-875a1f`, `20261127-123249-36d37e`, `20261127-124517-8cb786` | PASS × 3 | 2062, no failed, errored or skipped | 247–265 s |
| `6d6307d` | `0324a4b3384dbeea080cb20bf5652697e3e62055` | `20261127-133509-80f335`, `20261127-133925-a46e09`, `20261127-134341-a9e21f` | PASS × 3 | 2062, same | 256–263 s |

Per full run: main suite 1614, Keycloak 265, migration step 6, rate-limit regression 3 × 59. Other profiles passed three times each on `2781c10` (run IDs: BENCHMARK 8.1). The runner self-test has 31 tests.

Failed runs, all reported FAIL:

| Run | Commit | What failed | Disposition |
|---|---|---|---|
| `20261127-090118-5268da` | working tree | one test with a PostgreSQL server shared by workers | design changed (a server per worker) |
| `20261127-124945-daaa1a` | `2781c10` | no free Docker subnet beside a second full run | fixed in `6d6307d` (F2) |
| `20261127-132311-7e4359` | `6d6307d` | one test beside a second full run | open (F1) |
| `20261127-141107-be863d` | scratch copy with an injected Redis pause | the same test, on purpose | reproduction of F1 |

## 4. Evidence on the pushed commit

To be recorded after the push: full local run on the pushed SHA, GitHub run ID, URL and job results, and the comparison.

## 5. Findings

| ID | Finding | Severity (implementer) | State and proposal |
|---|---|---|---|
| F1 | A test of password change detection failed once beside a second full run. Probable cause: a Redis operation over the application's 500 ms on a loaded host, on a path that only logs the error; an injected pause reproduces the exact assertion. More parallel work makes such load likelier | medium: false failure, never false pass | **open.** Options for the owner: accept and rerun; let test rigs use a longer Redis timeout where the timeout is not under test; limit simultaneous full runs |
| F2 | The development server has few free Docker subnets; two full runs exhausted them | low after the fix | the runner waits up to 10 minutes. Unused networks of other stacks exist; removing them or widening the address pools is a host change for the owner |
| F3 | Targeted runs of few tests are a few seconds slower than before (parallel overhead) | low | documented; `--workers 1` avoids it. Starting worker servers concurrently could reduce it |
| F4 | Full local run about 4.3 minutes, target 2–3 | goal not met | options and their price in BENCHMARK 10; a separate job for the rate-limit regression needs an owner decision |
| F5 | **Host, outside this task:** two containers of another project restart in a loop and write about 400 MiB/s to each SSD while CI is idle | **high for the hardware** | not changed; reported to the owner with the details, for the owner's action |
| F6 | Identity job failing on `dev` since 2026-11-26 (stale expected provider version) | pre-existing | fixed in `6d4cb64` |
| F7 | GitHub runs 4 workers and 2 shards, Local CI 16 and 3 | by design | both must pass; see section 4 |

## 6. Recommendation

To be completed with section 4.
