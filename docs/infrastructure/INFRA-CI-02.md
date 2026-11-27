# INFRA-CI-02 — CI performance optimization

Date: 2026-11-27
Status: PROPOSED / DOCUMENTED ONLY. INFRA-CI-02 was deferred in INFRA-CI-01 acceptance; this document does not lift that deferral or authorize implementation, workflow changes, deployment or other packages.

## 1. Scope and evidence

Repository: AutoTramita-es/autotramita; branch: dev.
Review baseline: 2d5afc48b412f0d0fe50dcfa9825e99a0db60b2c.
Reuse [LOCAL-CI.md](LOCAL-CI.md) and [INFRA-CI-01 acceptance](INFRA-CI-01-ACCEPTANCE.md). The workflow remains the single source of mandatory commands.

GitHub's latest 20 runs at review: 7 success, 6 failure, 6 cancelled, 1 unfinished. Seven successful runs averaged 569.7 seconds. Four consecutive cancelled runs consumed 803 seconds of elapsed run time in aggregate (not necessarily developer waiting time). See [run history](https://github.com/AutoTramita-es/autotramita/actions) and [sample run](https://github.com/AutoTramita-es/autotramita/actions/runs/45963493616).
Sample: main pytest 346 s; mypy 7 s; dependency installation 1 s; identity OIDC step cancelled after 290 s; identity job cancelled after 410 s; Trivy job 67 s; dependency audit 11 s; secret scan 9 s. Existing concurrency cancellation is enabled. Full CI triggers on pushes and PRs to dev/main. Five jobs currently exist.

Historical local measurements from INFRA-CI-01 (not a fresh benchmark): FAST 77.2 s, unit 68.6 s, integration 174 s, full 303–316 s. Host Ryzen 9 5950X, 32 threads, 125 GiB RAM; shared with other services. The updated local guide estimates Keycloak ~370 s and security ~60 s. Rebaseline current SHA before comparing. No new host measurements were performed.

## 2. Development workflow

| Level | Existing command | Usage |
|---|---|---|
| FAST | scripts/ci/run-fast.sh | lint, format, mypy, unit suite, counts, runner self-test; during development |
| TARGETED | scripts/ci/run-unit.sh -- <pytest args> or scripts/ci/run-integration.sh -- <pytest args> | changed component and dependants; development feedback only |
| Specialized | scripts/ci/run-keycloak.sh, run-migrations.sh, run-security.sh, run-contracts.sh (same directory) | affected security, database, dependency and API boundaries |
| FULL LOCAL | scripts/ci/run-all.sh | all mandatory workflow steps plus local guards at defined checkpoints |
| GITHUB | existing CI workflow | independent final evidence at T package, CP, phase, release and main merge gates |

Use focused tests during corrections; do not push each experimental change. Run FAST and relevant specialized/targeted checks before checkpoint full CI. Commit and push only within existing authorization. Test the exact committed tree with --ref where necessary; reuse valid full results only for identical content and compatible environment, with current security evidence. Dirty or targeted runs are never acceptance evidence. Record SHA, tree hash, run ID, profile, counts, duration, verdict and GitHub run URL. No skipped, failed, errored or missing mandatory checks; no zero-test success. A failed or cancelled run is not acceptance evidence. Retry only failed jobs when valid for the same SHA and evidence requirements.

## 3. Proposed optimization order

1. Benchmark current local and GitHub jobs; collect pytest --durations and JUnit timing, CPU, memory and disk; distinguish cold/warm cache and host contention. Use at least three comparable runs per configuration.
2. Evaluate pytest-xdist (not currently declared) with 2/4/8 workers. Isolate PostgreSQL databases/roles, Redis state, files and ports per worker; keep shared-state, concurrency and timing-sensitive tests serial unless equivalence is proven. Preserve all three rate-limit regression repetitions and assertions. Verify test IDs/counts and outcomes against serial baseline.
3. Profile Keycloak fixtures and OIDC tests. Split independent groups only with isolated realms, users, databases and containers. Preserve multi-node locking, MFA, DEV/PROD import and missing-provider fail-closed tests. Do not reuse mutable state across tests to save time.
4. Add conservative automatic targeted selection to existing runner if beneficial. Map changed paths and transitive dependencies to profiles; include untracked changes and renames; unknown/shared/config/lockfile changes fall back to full CI. Never use selection to bypass acceptance checks. Existing explicit targeted commands remain available.
5. Evaluate cache improvements only after measurement. uv caching and local npm/uv volumes already exist. Preserve pinned images, lockfiles, scanner freshness and broker restrictions; local Docker build currently deliberately uses --no-cache. Any change to broker or network boundary requires separate security review and authorization. Do not introduce a privileged or production-connected self-hosted GitHub runner.
6. Propose root CLAUDE.md and AGENTS.md pointers to the accepted CI rules; avoid duplicate policy. Add concise agent-facing summaries using existing summary.json and report.txt; retain redacted detailed logs for failures.
7. Consider GitHub trigger changes only with separate owner approval, after parity evidence: retain main push and PR checks for dev/main; optional manual dispatch on dev checkpoints instead of every dev push. Ensure exact-SHA run evidence, update compare-github event handling, and preserve all five mandatory jobs. No paths-ignore for documentation. Existing triggers and concurrency stay unchanged until approved.

## 4. Targets (not guarantees)

FAST 10–60 s; TARGETED 1–3 min; main pytest 1–2 min; identity job 3–5 min; GitHub full 4–6 min; local full target to be set after baseline. Report median and range, resource costs and any regressions. Prioritize reduced development waiting over artificial benchmark targets.

## 5. Security and acceptance criteria

- All current mandatory tests, warning policies, RLS/tenant isolation, migrations, authentication/MFA, API contracts, secret history scan, dependency audit and image scan remain intact.
- Preserve INFRA-CI-01 conditional acceptance and LCI-04/05 limitations. Network-enabled steps can reach host-published services; no expansion of access, production credentials, data or shared mutable test state. No host firewall or broker changes without authorization.
- Preserve scanner database age limits, pinned tools and owner-only vulnerability acceptances.
- Demonstrate equivalent serial/parallel test inventories and results, repeatability, fail-closed behavior, isolated workers and safe cleanup. No Docker prune.
- Demonstrate full local/GitHub parity on the same clean SHA with compare-github.sh and independent GitHub success. Validate runner compatibility with all workflow changes and retain runner self-tests.
- Report benchmark evidence, limitations, deferred findings and rollback procedure. Independent read-only review precedes owner acceptance.
- No changes to F2 decisions, application features, production infrastructure or deployment are authorized by this document.

## 6. Open items

Fresh host benchmarks, fixture-level profiling, safe worker count, automatic selection design, branch protection/current ruleset verification and any trigger change remain open. Existing local CI documentation remains authoritative for current commands. This is a proposal, not an execution order.
