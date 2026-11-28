# INFRA-CI-02 — Acceptance report

Date: 2026-11-27. **Status: ACCEPTED by the owner on 2026-11-27, together with [INFRA-CI-02-REC-01](INFRA-CI-02-REC-01.md), after its independent verification ([section 7](#7-independent-verification-and-owner-acceptance)).** Reviewed at `1357d89` (PASS WITH CONDITIONS); corrections verified at `285e638`. Closure confirmed the same day. Still open: findings F1 (cause unproven) and F4 and the deferred findings. The F2 obligations IR-05 and IR-06 were transferred to [PROD-SEC-01](PROD-SEC-01.md) ([section 7.4](#74-open-obligation-from-f2-ir-05-and-ir-06)). The acceptance concerns the CI infrastructure only: nothing here accepts a checkpoint, certifies the application as ready for production, or authorizes a merge into `main` or a deployment.

[Specification](INFRA-CI-02.md) · [Implementation](INFRA-CI-02-IMPLEMENTATION.md) · [Benchmark](INFRA-CI-02-BENCHMARK.md) · [Local CI guide](LOCAL-CI.md)

## 1. Revisions

| Item | SHA |
|---|---|
| Head of `dev` before the implementation commits | `19908d7c43fde892217a086a64638270b6d529f6` |
| Fix of the stale provider version in `ci.yml` (precondition, see IMPLEMENTATION 1.7) | `6d4cb64` |
| Parallel test execution and runner changes | `2781c10540f31ae66cee5beb31b476ead3cded70` |
| Runner: wait for a free Docker subnet | `6d6307d46449e1cae3e218fe1596bfe56fb3db80` |
| Runner: targeted runs take at most four workers | `3103631a94dc245cf40b63e5ebeb05ab0fbfe1b9` |
| Benchmark, implementation and first version of this report (first push) | `2f387c63807004a9f220d8a0b2af3ac70ddb8ce9` |
| Comparison tool: sharded summaries compared as their sum (**last code change**, pushed) | `f1a6e56a01411f332e5587a9f2690b2feaa4bebf` |
| Final commit: GitHub evidence recorded (documentation only; **the reviewed baseline**) | `1357d89a699aaf67c83acade180e7a55a8cfc08c` |
| Baseline used for comparisons | `852d28a` (the first commit as measured before a rebase; same change as `6d4cb64`) |

Between `19908d7` and `f1a6e56` nothing changed under `app/`, `migrations/`, `identity/`, `openapi/`, `scripts/identity/`, in the Docker broker, the workflow parser, `compose.ci.yml`, `images.lock.json`, the compose files, `tests/test_ci_workflow.py` or `tests/identity/test_identity_environment.py` (`git diff --stat` empty). Workflow triggers, permissions, concurrency and job names are unchanged.

## 2. Acceptance matrix

State is the implementer's assessment for the reviewer to confirm.

| # | Criterion (specification section 5 and 3) | State | Evidence |
|---|---|---|---|
| A1 | Mandatory tests, warning policy, RLS and tenant isolation, migrations, authentication and MFA, API contracts, secret history scan, dependency audit and image scan remain | met | same workflow steps; `-W error` and the rate-limit repetitions unchanged; case-by-case inventory (BENCHMARK 9); protected paths unchanged (section 1) |
| A2 | INFRA-CI-01 limitations preserved; no new access, credentials, shared mutable state, firewall or broker change | met | broker unchanged; new servers are loopback-only inside the job's namespace, throwaway data, one PostgreSQL per worker and one Redis database per worker or shard |
| A3 | Scanner database age limits, pinned tools, owner-only vulnerability acceptances | met | files unchanged; additional servers use the pinned service digests (guard test) |
| A4a | Equivalent serial and parallel inventories and results | met | BENCHMARK 9: no case missing, 55 guard tests added, all passed. The automatic check compared a count only (review P3-1; REC-01) |
| A4b | Repeatability | **partly** | six of six single full runs passed (`2781c10`, `6d6307d`); under two simultaneous full runs one test failed once, cause unproven (finding F1) |
| A4c | Fail-closed behaviour | met, **gap found by review** | guard tests for failing, empty and interrupted parts and for a missing Keycloak test; both observed failures were reported FAIL. A duplicated or substituted test with an unchanged count was accepted (review P3-1; REC-01) |
| A4d | Isolated workers, safe cleanup, no prune | **not met at the reviewed SHA** | xdist workers were isolated; the Keycloak shards shared one PostgreSQL server (review P1-1), and cleanup with another `ATCI_STATE_DIR` could remove an active run (review P3-2, REC-01 also found containers affected). No `docker … prune`. Corrections: REC-01, verified at `285e638` (section 7) |
| A5 | Local and GitHub parity on the same clean SHA, independent GitHub success | met after a fix of the comparison tool | section 4 |
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

Per full run: main suite 1614, Keycloak 265, migration step 6, rate-limit regression 3 × 59. Other profiles passed three times each on `2781c10` (run IDs: BENCHMARK 8.1). The runner self-test has 34 tests.

Failed runs, all reported FAIL:

| Run | Commit | What failed | Disposition |
|---|---|---|---|
| `20261127-090118-5268da` | working tree | one test with a PostgreSQL server shared by workers | design changed (a server per worker) |
| `20261127-124945-daaa1a` | `2781c10` | no free Docker subnet beside a second full run | fixed in `6d6307d` (F2) |
| `20261127-132311-7e4359` | `6d6307d` | one test beside a second full run | open (F1) |
| `20261127-141107-be863d` | scratch copy with an injected Redis pause | the same test, on purpose | reproduction of F1 |

## 4. Evidence on the pushed commits

| Commit / tree | Local full run | GitHub run | GitHub jobs | `compare-github.sh` |
|---|---|---|---|---|
| `2f387c63807004a9f220d8a0b2af3ac70ddb8ce9` / `0f354b48acc07a8424468f7d8f83971f55515af6` | `20261127-142739-e5b9a6` PASS, 249.7 s | [46016787516](https://github.com/AutoTramita-es/autotramita/actions/runs/46016787516) success, 356 s | 5 of 5 success | first **DIFFERENT**, with the fixed tool EQUIVALENT |
| `f1a6e56a01411f332e5587a9f2690b2feaa4bebf` / `df8e3487a1072bdea70bae96e952f04c250b3437` | `20261127-143904-1b7060` PASS, 247.9 s | [46018469751](https://github.com/AutoTramita-es/autotramita/actions/runs/46018469751) success, 387 s | 5 of 5 success | **EQUIVALENT** |

| Job on `f1a6e56` | GitHub | Local |
|---|---|---|
| Lint, types, tests | success, 365 s | PASS, 204 s |
| Keycloak 26.8.2 integration | success, 383 s | PASS, 245 s |
| Keycloak image vulnerability scan | success, 70 s | PASS, 75 s |
| Dependency audit | success, 10 s | PASS, 5 s |
| Secret scan | success, 12 s | PASS, 6 s |

Both sides: main suite 1513 + 101 passed, migration step 6, rate-limit regression 3 × 59, Keycloak 265 passed (99 deselected); no failed, errored or skipped test. GitHub used 4 workers and 2 shards, Local CI up to 16 and 3.

**The first comparison reported `DIFFERENT`** for one line: the pytest summaries of the Keycloak job, `112 + 153` on GitHub (two shards) against `58 + 139 + 68` locally (three). Totals were equal. The tool did not know about shards, an omission of this implementation. Commit `f1a6e56` makes it compare the sum of the summaries of a sharded job; a missing, failed, deselected or skipped test remains a difference (three self-tests). The reviewer should confirm that this does not weaken the comparison.

The commit that recorded this section (`1357d89`, documentation only) has its own evidence, added by REC-01:

| Commit / tree | Local full run | GitHub run | GitHub jobs | `compare-github.sh` |
|---|---|---|---|---|
| `1357d89a699aaf67c83acade180e7a55a8cfc08c` / `2418f7e82f0fad0c688829f2ffc8829870826c8e` | `20261127-145105-141d26` PASS, 247.6 s | [46020259401](https://github.com/AutoTramita-es/autotramita/actions/runs/46020259401) success, 479 s | 5 of 5 success | **EQUIVALENT** |

The three GitHub durations of INFRA-CI-02 are 356, 387 and 479 s ([BENCHMARK 11](INFRA-CI-02-BENCHMARK.md#11-github)). The comparison compares counts and step outcomes, not test identities.

## 5. Findings

| ID | Finding | Severity (implementer) | State and proposal |
|---|---|---|---|
| F1 | A test of password change detection failed once beside a second full run. **Cause unproven.** Reproduced (review, again in REC-01): a Redis namespace shared by two rigs fails the same assertion without a warning, like the original log. Hypothesis only: a Redis operation over 500 ms; its injected form leaves a warning the original log lacks. An earlier version of this table named the delay as the probable cause and claimed "never a false pass"; neither was established | medium | namespaces made unique in REC-01. **Cause of the historical failure remains open**; no timeout, assertion or retry changed |
| F2 | The development server has few free Docker subnets; two full runs exhausted them | low after the fix | the runner waits up to 10 minutes. Unused networks of other stacks exist; removing them or widening the address pools is a host change for the owner |
| F3 | Targeted runs of few tests are a few seconds slower than before (parallel overhead) | low | documented; `--workers 1` avoids it. Starting worker servers concurrently could reduce it |
| F4 | Full local run about 4.3 minutes, target 2–3 | goal not met | options and their price in BENCHMARK 10; a separate job for the rate-limit regression needs an owner decision |
| F5 | **Host, outside this task:** two containers of another project restart in a loop and write about 400 MiB/s to each SSD while CI is idle | **high for the hardware** | not changed; reported to the owner with the details, for the owner's action |
| F6 | Identity job failing on `dev` since 2026-11-26 (stale expected provider version) | pre-existing | fixed in `6d4cb64` |
| F7 | GitHub runs 4 workers and 2 shards, Local CI 16 and 3 | by design | both passed on both pushed commits |
| F8 | GitHub durations vary widely between runs of the same test code (run 356–479 s; main tests step 154–242 s) | information | three runs; see BENCHMARK 11 |

## 6. Recommendation

The implementer's recommendation (READY FOR INDEPENDENT REVIEW) was followed by the independent review of `1357d89`: **PASS WITH CONDITIONS** (P1-1, P1-2, P2-1, P2-2, P3-1 to P3-7). [INFRA-CI-02-REC-01](INFRA-CI-02-REC-01.md) answers the conditions and records the deferred findings. Next: independent verification of REC-01, then the owner's decision, including F1, F4, F5 and the missed duration goals. No self-acceptance, merge or deployment. Both steps followed on 2026-11-27 (section 7).

## 7. Independent verification and owner acceptance

### 7.1 Verification of INFRA-CI-02-REC-01

A separate session, which took no part in the implementation, verified the corrections read-only on 2026-11-27. Its report was returned to the owner and is not a repository file; this section summarises it. Verdict: **PASS — RECOMMENDED FOR OWNER ACCEPTANCE**. REC-01 to REC-06 confirmed; no production-blocking finding within the reviewed scope.

| Evidence | Implementation `3bbdf82` | Verified head `285e638` |
|---|---|---|
| Tree | `389b063f12f9f68a3b96608180c09e93f2726dd1` | `8fe97580a5e6192683c68317e6ff9aa46ecd9436` |
| Local full run, clean content, not targeted | `20261127-190000-b13df1` PASS, 235.5 s | `20261127-191044-97ce4f` PASS, 232.6 s |
| GitHub run, attempt 1 | [46054031586](https://github.com/AutoTramita-es/autotramita/actions/runs/46054031586) success, 5 of 5 jobs, 344 s | [46054830681](https://github.com/AutoTramita-es/autotramita/actions/runs/46054830681) success, 5 of 5 jobs, 439 s |
| Comparison, recomputed by the verifier | **EQUIVALENT** | **EQUIVALENT** |
| Commits scanned without a leak | 575 | 576 |

Both SHAs: main suite 1733 (1632 parallel, 101 serial), Keycloak 265, migration step 6, rate-limit regression 3 × 59; 2181 executions, none failed, errored or skipped. Inventory digests as in [REC-01 4.2](INFRA-CI-02-REC-01.md#42-final-checkpoint-the-tested-implementation), recomputed from the local result files (for the main suite after restoring four redacted test parameters from the source). Against `1357d89` no test case is missing and 119 are added.

Limits of the verification: it did not repeat the full runs, the GitHub runs, the PostgreSQL race experiment or the cleanup runs with the real Docker daemon; for these it relied on saved logs, partly those of the implementing session.

### 7.2 Findings added by the verification (not blocking, not corrected)

| ID | Finding |
|---|---|
| N1 | Checkouts with the older runner (the feature worktrees on the development server, and this branch after a rollback) can remove containers, networks and images of an active run that uses another state directory, also when started with the default one. [REC-01 section 9](INFRA-CI-02-REC-01.md#9-rollback) warns of one direction only, and not of the returning permission change of an existing state directory. Until those checkouts have REC-01, and after a rollback: run `cleanup.sh` only while no CI run is active. Concluded from the code, not executed |
| N2 | LOCAL-CI says cleanup removes only what a run of the same state directory created; `--results-older-than` also removes old finished results of other state directories, as its table row says |
| N3 | `compare-github.sh` skips the inventory digest if neither side printed it. The current scripts cannot succeed without printing it, and a test keeps the workflow on those scripts |

### 7.3 Owner acceptance

The owner, 2026-11-27, verbatim: „Prihvaćam INFRA-CI-02 i REC-01, upiši prihvaćanje u dokumente."

- INFRA-CI-02 and INFRA-CI-02-REC-01 are **accepted and closed**, on the verification of `285e638` (the order itself names no SHA).
- Acceptance changes no measured result: A4b stays partly met, the duration goals that were missed stay missed (F4), and the cause of F1 stays unproven.
- P3-3 to P3-7, the other entries of [REC-01 section 5](INFRA-CI-02-REC-01.md#5-deferred-findings), the limitations in REC-01 section 7 and N1 to N3 remain recorded and not corrected.
- It authorizes no merge into `main`, deployment, trigger or host change, or further package.

Final confirmation by the owner, 2026-11-27, verbatim: „Potvrđujem konačno prihvaćanje i zatvaranje INFRA-CI-02 i INFRA-CI-02-REC-01.“

### 7.4 Open obligation from F2: IR-05 and IR-06

The F2 decisions D46 and D47 ([decision register](../design/F2-DECISION-REGISTER.md), 2026-11-25) deferred IR-05 (scan-gate hardening) and IR-06 (Local CI broker build network) **to INFRA-CI-02**, and D47 made severity binding of vulnerability acceptances a **mandatory INFRA-CI-02 requirement**. The INFRA-CI-02 specification, implementation and review reports do not address them, and the verification in 7.1 did not cover them; this was noticed while the acceptance was being recorded. `scripts/identity/scan_gate.py`, the acceptances and `scripts/ci/lib/broker.py` are unchanged since `b24da2a`: the gate still matches an acceptance by finding and package, not by severity.

The acceptance order does not mention these items. It therefore **neither fulfilled, waived nor reassigned** them.

**Decided afterwards (2026-11-27, D48):** the owner transferred the obligations to the production security package [PROD-SEC-01](PROD-SEC-01.md). IR-05 must be resolved and independently verified before any production deployment; for IR-06 applicability and scope are determined first. Nothing is fulfilled yet. Until PROD-SEC-01 is formally closed, D46 and D47 and their interim controls stay in force: the severity is reassessed whenever an acceptance is renewed or extended, zero CRITICAL findings are confirmed manually before any production deployment, and existing network access is not extended.
