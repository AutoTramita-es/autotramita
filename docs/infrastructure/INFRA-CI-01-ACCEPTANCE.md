# INFRA-CI-01 — Local CI Runner: acceptance report

Date: 2026-11-25. **Status: CONDITIONALLY ACCEPTED for development use** (owner order, 2026-11-25: accepted with the documented limitations LCI-04 and LCI-05; the repository stays public until a separate owner decision; INFRA-CI-02 is deferred). Reported as READY FOR OWNER ACCEPTANCE. Nothing here accepts CP09 or authorizes T10–T13; F2 decisions are unchanged.

How to use the runner: [LOCAL-CI.md](LOCAL-CI.md).

## 1. Revisions

| Item | SHA |
|---|---|
| Start of the task (HEAD of `dev`) | `99e0d8a83d53cdc619552b577220e2b83af9798e` |
| F2 commits made by a parallel session during the task (not part of INFRA-CI-01) | `c647f9c`, `822a4e7`, `8cd5820` |
| Local CI runner | `bb4538c73a6782677d7e1f5b174ae3c48be85a3f` |
| **Final runner code** (redaction fix) | `43542b69143739759f6144e994b0c5286339572a` |
| This report and the guide | the documentation commit on top of the final runner code |

Changed by INFRA-CI-01: `.gitignore` (one line), `compose.ci.yml`, `scripts/ci/`, `docs/infrastructure/`. **Not changed:** `.github/workflows/ci.yml`, triggers, branch settings, application code, tests, migrations. The F2 work in progress was left to its own session; commits were staged by path.

## 2. Delivered scripts

| Script | Purpose |
|---|---|
| `run-fast.sh`, `run-unit.sh`, `run-integration.sh`, `run-keycloak.sh`, `run-migrations.sh`, `run-security.sh`, `run-contracts.sh`, `run-all.sh` | profiles |
| `status.sh`, `cleanup.sh` | operation |
| `compare-github.sh` | local versus GitHub on one commit |
| `selftest.py` | 15 tests of the runner's guard rails |
| `lib/runner.py`, `workflow.py`, `profiles.py`, `snapshot.py`, `broker.py`, `report.py`, `compare.py`, `container/` | implementation |
| `Dockerfile`, `images.lock.json`, `../../compose.ci.yml` | environment |

## 3. Local full CI

| Run | Content | Result | Main | Keycloak | Duration |
|---|---|---|---|---|---|
| `20261124-232810-424bec` | working tree before the commit | PASS | 1183 | 58 | 303.0 s |
| `20261124-233928-a8d6f9` | `99e0d8a` | PASS | 1163 | 54 | 315.3 s |
| `20261124-235228-0e0ae8` | `bb4538c`, caches and runner image removed first | PASS | 1183 | 58 | 315.7 s |
| `20261124-235759-37e74c` | `bb4538c`, again | PASS | 1183 | 58 | 309.9 s |
| `20261125-001446-45b1eb` | `43542b6` | PASS | 1183 | 58 | 312.6 s |

On the final runner code: 1241 distinct tests passed, 0 failed, 0 errors, 0 skipped. All pytest invocations together: 1424 passed (migration step 6, rate-limit regression 59 three times). Ruff, format, mypy, OpenAPI validation and currency, TypeScript and Dart generation, gitleaks (history and files), pip-audit and DEV/PROD realm import passed.

"Caches removed" means the uv and npm volumes and the runner image; the Docker build cache and pulled service images stayed. The very first image build took 19.2 s.

## 4. GitHub CI on the same commits

| Commit | GitHub run | GitHub | Local | Comparison |
|---|---|---|---|---|
| `99e0d8a` | [45507595621](https://github.com/AutoTramita-es/autotramita/actions/runs/45507595621) | success, 318 s | PASS, 315 s | one difference: 517 commits scanned locally, 514 on GitHub. Cause fixed before `bb4538c`; the security profile then scanned 514 |
| `bb4538c` | [45513560183](https://github.com/AutoTramita-es/autotramita/actions/runs/45513560183) | success, 319 s | PASS, 316 s | **EQUIVALENT** |
| `43542b6` | [45517272943](https://github.com/AutoTramita-es/autotramita/actions/runs/45517272943) | success, 329 s | PASS, 313 s | **EQUIVALENT** |

Compared: job set, run-step names and order, outcome of every step, pytest summaries, test count lines, commits scanned, secret-scan and audit verdicts, imported realms, client generation. On `bb4538c` and `43542b6` both sides had 1183 passed (58 deselected), 6, 59, 59, 59, and 58 passed (39 deselected); commits scanned were 518 and 519 on both sides.

## 5. Durations and resources

Per-profile durations were measured on `bb4538c` with a clean tree and warm caches.

| Profile | Duration | Tests |
|---|---|---|
| FAST | 77.2 s | 616 |
| unit | 68.6 s | 616 |
| integration | 174.0 s | 567 |
| keycloak | 139.3 s | 58 |
| migrations | 24.7 s | 63 (6 + 57) |
| security | 5.9 s | — |
| contracts | 14.1 s | — |
| **FULL** | **303–316 s** (GitHub: 318–329 s) | 1241 |

FULL is bounded by the main job (about 215 s tests and 57 s rate-limit repetitions); running the four jobs in parallel gains nothing beyond that.

Full run: peak 3.3–3.8 GiB memory, peak CPU 8–13 cores, 10 containers, workspaces about 0.4 GiB (removed afterwards), caches about 210 MiB, runner image 643 MB, results under 1 MiB per run. Host: Ryzen 9 5950X (32 threads), 125 GiB, load 4–10 from other services during the measurements.

## 6. Acceptance matrix

| ID | Criterion | Verdict | Evidence |
|---|---|---|---|
| LCI-01 | FAST works | MET | `20261125-000309-5fe536`, PASS, 77.2 s |
| LCI-02 | FULL works | MET | section 3 |
| LCI-03 | All mandatory GitHub checks covered | MET | the runner executes every run step of `ci.yml`; self-test asserts it; step lists identical in section 4. R10 unchanged (deferred) |
| LCI-04 | Test infrastructure isolated | MET, with the boundary in 7.1 | per-job namespace without network, tmpfs, no published ports, isolation check in the run; two simultaneous runs passed (`20261125-001147-1462f1`, `-737e10`) |
| LCI-05 | No access to production data | MET, with the boundary in 7.1 | test steps have loopback only; only `ci.yml` throwaway credentials; probe: shared `postgres` and `infra-redis` unreachable from the network-enabled network |
| LCI-06 | Reproducible results | MET | two runs of `bb4538c`: identical check statuses and counts; content identified by tree hash; images and lockfiles pinned (limits 7.2, 7.3) |
| LCI-07 | Complete evidence in reports | MET | `report.txt`, `summary.json`, JUnit per pytest invocation and per check, logs |
| LCI-08 | Failures give non-zero exit | MET | injected: failing unit test (`20261124-233619-f74883`, exit 1), skipped test (`20261124-233424-c1d0b9`, 1), Ruff error (`-c78669`, 1), mypy error (`-5d7a3d`, 1), failing Keycloak test (`20261125-001251-a3ed30`, 1), unsupported workflow (exit 2), interrupt (`20261125-002031-715c73`, 130) |
| LCI-09 | Cleanup leaves other services alone | MET after a fix | first test removed a hand-started container of the runner image (it inherited the image label). Fixed before the first commit; retest removed only the planted stale container and network plus CI caches, while four bystanders survived; an active run was kept |
| LCI-10 | Differences documented | MET | LOCAL-CI.md, "Local CI compared with GitHub CI" |
| LCI-11 | Durations measured | MET | section 5 |
| LCI-12 | Functional equivalence on one commit | MET | section 4 |

No test was weakened, removed or skipped.

## 7. Remaining limitations

1. **Network-enabled steps reach host services published on all interfaces** (measured: 22, 25, 80, 443, 587, 993, 8001, 8010, 9000). Only dependency install, client generation and audit run there, without credentials. The shared PostgreSQL and Redis tested are not reachable. Closing it needs host firewall rules (separate approval). The Docker daemon and hardware are shared with other services.
2. The runner is an Ubuntu 24.04 container, not GitHub's VM image; its apt packages are not version pinned.
3. `pip-audit` depends on the advisory database at run time.
4. The runner supports only the workflow features in use; new ones stop the run until it is extended.
5. `scripts/ci/` is outside the project's Ruff and mypy scope and its self-test does not run on GitHub.
6. A local PASS is produced on a machine the agent controls; it is not independent evidence.
7. It needs root (or uid 1001).
8. There is no `AGENTS.md` or `CLAUDE.md` in the repository, so agents do not pick up the new rules automatically.

## 8. Deviations from the requested design

| Requested | Done | Reason |
|---|---|---|
| Shared scripts used by local CI and GitHub | the workflow's own `run:` blocks are executed locally; `ci.yml` unchanged | one implementation, no change to the guarded workflow while F2 work touched it |
| Keycloak in `compose.ci.yml` | started by the workflow step through the broker | otherwise defined twice |
| Mailpit or test SMTP | the tests' own SMTP sink | it already exists; nothing else needed |

## 9. Observations for the owner (outside this task)

- The repository is **public** (GitHub API, 2026-11-24). Confirm that this is intended.
- `main` and `dev` have no branch protection and no ruleset.
- The parallel F2 session reported that `99e0d8a` reached `dev` at 23:10:05 UTC without a push from it. This session did not push it either. GitHub shows account `avrcanio`; the local process is unknown.
- Containers `autotramita-d37-pg-ephemeral` and `autotramita-d37-redis-ephemeral`, not created by Local CI, were still running; they were not touched.
- The clone fetches only `main` by default (`remote.origin.fetch`), so `origin/dev` is stale locally.
- `docs/DEVELOPMENT.md` still describes manual test containers; a pointer to Local CI could be added.

## 10. Proposed optimization of GitHub Actions (not applied)

Details in LOCAL-CI.md. Summary: keep `pull_request` and `push` for `main`; for `dev` replace the push trigger by `workflow_dispatch` at T package ends, CP points and phase ends (optionally after a two-week comparison period); no `paths-ignore`; protect `main` with the four jobs as required checks; block force push on `dev`; optionally run the runner self-test on GitHub. On 2026-11-24 the listed history held 100 runs in one day of about 5.3 minutes each; minutes are not billed for a public repository.
