# Local CI (INFRA-CI-01)

Runs every check of the GitHub Actions workflow on the development server, on uncommitted work, with no commit or push. **A local PASS is development feedback. It does not replace the GitHub CI evidence** required at the control points listed in [Agent rules](#rules-for-claude-code-codex-and-other-agents).

## Quick start

```sh
./scripts/ci/run-fast.sh                 # while working, about 75 s
./scripts/ci/run-all.sh                  # before finishing a T package, about 5 min
./scripts/ci/status.sh                   # what ran, what is running
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
| Internet | | dependency install, `npm ci`, `pip-audit`, first image pulls |

Nothing else is installed on the host and no GitHub self-hosted runner is involved. The first run builds the runner image (`atci-runner:<hash>`) and pulls the pinned service images.

Optional: `ATCI_STATE_DIR` moves the workspaces and locks (default `/var/tmp/autotramita-ci`, mode 0700).

### Resources (measured)

| Quantity | Full run, four jobs in parallel |
|---|---|
| Peak memory of CI containers | 3.3–3.8 GiB |
| Peak CPU | 8–13 cores |
| Containers at the same time | 10 |
| Workspaces during the run (removed afterwards) | about 0.4 GiB |
| Caches kept between runs | about 210 MiB (`atci-uv-cache`, `atci-npm-cache`), runner image 643 MB, service images |
| Results per full run | under 1 MiB |

Recommended: 8 free cores, 8 GiB free memory, 20 GiB free disk. The measuring host has 32 threads and 125 GiB and runs other services. Use `--serial` on a smaller or busy machine.

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
  netns (no network, loopback only) ── PostgreSQL ── Redis ── Keycloak ── step containers
  egress network (only for steps that run `uv sync`, `npm ci` or `uvx`)
```

**Single source of commands.** The runner executes the `run:` blocks of `ci.yml` verbatim with `bash -e`, as GitHub does. No test command is copied into the local scripts, so a change to the workflow takes effect locally at once. Versions of Python, uv and Node are read from the workflow; their base image digests are in [images.lock.json](../../scripts/ci/images.lock.json). Service and tool images are taken from `ci.yml` and `openapi/check-clients.sh`.

**Fail closed.** A job key, action, condition, expression, service or Docker flag that the runner does not know stops the run with exit code 2. If a step that a profile selects by name is renamed, the run stops too.

**Content under test.** By default the working tree: tracked changes plus untracked, not ignored files. `--ref <commit>` tests a commit instead. Each job gets its own new repository containing only that tree and the history GitHub would check out (the tested branch up to the commit, the other branches of `origin` as last fetched, tags). Files edited during a run do not affect it, and CI cannot write into the real tree. The real index, refs and files are not changed; only git objects are added.

Untracked files named like secrets (`.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, SSH keys, `*secret*.json`, `credentials*.json`) are never copied and are listed in the report. Ignored paths such as `.secrets/` are never part of the tree.

## Commands and profiles

| Command | Runs | Services | Measured |
|---|---|---|---|
| `run-fast.sh` | Ruff lint and format, mypy, tests that need no PostgreSQL or Redis, test counts, runner self-test | none | 77 s |
| `run-unit.sh` | the same tests and counts only | none | 69 s |
| `run-integration.sh` | tests that depend on the PostgreSQL or Redis fixtures (RLS, privileges, sessions, authentication, recovery, notifications, rate limiting), test counts, isolation check | PG, Redis | 174 s |
| `run-keycloak.sh` | the whole `identity` job: Keycloak tests, DEV and PROD realm import | PG, Redis, Keycloak | 139 s |
| `run-migrations.sh` | the workflow's upgrade/downgrade/upgrade step, exactly one migration head, the complete role and migration test files | PG, Redis | 25 s |
| `run-security.sh` | the `secrets` and `dependencies` jobs (gitleaks, pip-audit), gitleaks on uncommitted files | none | 6 s |
| `run-contracts.sh` | OpenAPI 3.1 validation, contract is current, TypeScript and Dart generation | none | 14 s |
| `run-all.sh` | **every job and every run step of `ci.yml`**, plus the local checks | all | 303–316 s |
| `compare-github.sh [dir] [--run id]` | compares a clean full run with the GitHub run of the same commit | | seconds |
| `status.sh [--limit n]` | active runs, CI containers, recent results | | |
| `cleanup.sh [--dry-run] [--caches] [--results-older-than DAYS]` | removes leftovers | | |

Options of every `run-*.sh`:

| Option | Meaning |
|---|---|
| `--ref <commit>` | test the content of that commit, ignoring uncommitted changes |
| `--serial` | one job at a time |
| `--keep-workspace` | keep the job directories for debugging (remove with `cleanup.sh`) |
| `--source <dir>` | test another checkout |
| `-- <pytest args>` | targeted run: passed to the main test step |

Targeted tests of the component you changed:

```sh
./scripts/ci/run-integration.sh -- tests/auth/sessions
./scripts/ci/run-unit.sh -- tests/test_config.py -k url
```

The report of such a run is marked `TARGETED: not acceptance evidence`. If the selected paths contain no test of the profile's kind, the run fails.

**Unit and integration split.** A test counts as integration when it depends, directly or through another fixture, on `pg_admin_url` or `redis_url`. The split is made by a pytest plugin at collection time; no test is modified or marked. Deselected tests are reported as deselected, never as skipped. Unit plus integration equals the main suite of GitHub.

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
| No Docker socket | steps that call `docker` talk to a broker on the host that allows only `run`, `logs` and `rm -f` of the job's own containers, only the images named in the repository, only mounts inside the job workspace, and only the job's namespace or no network |
| Unprivileged steps | uid 1001, all capabilities dropped, `no-new-privileges` |
| Parallel runs | every run has its own names, namespace and workspace; several runs may execute at once. Caches are shared and safe for concurrent use |

Keycloak is not declared in [compose.ci.yml](../../compose.ci.yml): the workflow step that starts it (`docker run`, pinned by digest) is executed through the broker, so it has one definition.

**Known boundary.** Steps that need the network (`uv sync`, `npm ci`, `pip-audit`) run on a per-job bridge network. Measured from such a network: the host's PostgreSQL and Redis containers are **not** reachable, and neither is a service bound to the host's loopback. Services the host publishes on all interfaces **are** reachable through the gateway (on this server ports 22, 25, 80, 443, 587, 993, 8001, 8010, 9000). Those steps run dependency tooling, not tests, and hold no credentials. Blocking this needs host firewall rules, which Local CI does not change.

Local CI shares the Docker daemon, CPU, memory and disk with the other services of the host.

## Reading results

`.ci-results/` is ignored by git.

```text
.ci-results/
  latest  latest-all  latest-fast ...       links to the newest run (per profile)
  <run id>/
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

Every run removes its own containers, networks and workspaces, also after failure, `Ctrl-C` or `SIGTERM`. After a kill that gives no chance to react (`SIGKILL`, reboot):

```sh
./scripts/ci/cleanup.sh --dry-run     # shows what would be removed
./scripts/ci/cleanup.sh               # stale containers, networks, workspaces
./scripts/ci/cleanup.sh --caches      # also caches and the runner image
./scripts/ci/cleanup.sh --results-older-than 14
```

It removes a container or network only if it carries the label `com.autotramita.ci.run` **and** its name starts with `atci-`, and only if that run is no longer active (file lock). It never runs a `prune` command. Pulled service images are left in place.

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
| `pip-audit` fails without a code change | a new advisory was published, or PyPI is unreachable |
| Rate-limit timing tests fail on a loaded host | check `uptime`; rerun with `--serial`. Do not loosen the assertions |
| gitleaks scans an unexpected number of commits | refresh branches with `git fetch origin`; this clone fetches only `main` by default |
| `[local] gitleaks on the files under test` fails | a secret-like string is in a file you have not committed yet: remove it before committing |
| Disk filling up | `cleanup.sh --results-older-than 14`, `cleanup.sh --caches` |
| Debugging a job | `--keep-workspace`, inspect `/var/tmp/autotramita-ci/work/<run>/<job>/` |

## Rules for Claude Code, Codex and other agents

Proposed workflow (to be confirmed by the owner):

1. Implement the change.
2. `run-fast.sh`.
3. Targeted tests of the changed components (`run-integration.sh -- <paths>`, `run-keycloak.sh` for identity changes, `run-migrations.sh` for migrations).
4. Fix and repeat.
5. `run-all.sh` before finishing a T package.
6. Commit and push to `dev`.
7. GitHub Actions final check; optionally `compare-github.sh`.
8. Acceptance report.
9. Owner acceptance.

GitHub CI stays mandatory for: completion of a T package, CP control points, completion of a phase, release and merge into `main`.

Agents must:

- report the run id, tested SHA and tree, and whether the tree was dirty;
- never describe a targeted, partial or dirty-tree run as acceptance evidence;
- never report PASS for exit code other than 0;
- not weaken, skip or deselect tests, edit `images.lock.json` digests or widen the broker policy to make a run pass;
- not run test containers by hand on fixed ports when a profile covers the need;
- clean up only with `cleanup.sh`, never with `docker … prune`;
- in a shared working tree, remember that the default run includes other sessions' uncommitted files. Use `--ref` to test a commit alone, and stage commits by explicit path.

## Local CI compared with GitHub CI

Same: workflow steps and order, commands, shell, job separation, timeouts, `if: always()` / `if: failure()`, service and tool images by digest, service health checks, Python 3.12.16 (uv managed), uv 0.13.9, Node 20.20.0, `uv.lock`, npm lockfile, unprivileged uid 1001.

| Difference | GitHub | Local | Effect |
|---|---|---|---|
| Machine | `ubuntu-24.04` VM image, updated by GitHub | `ubuntu:24.04` container; apt packages (curl, git, jq, python3) not version pinned; host kernel 5.15 | tools outside the lockfiles may differ |
| CPU and load | small dedicated VM | 32 threads shared with other services | timing-sensitive tests can differ in either direction |
| Network in test steps | open | loopback only | stricter locally |
| Services | service containers, disk | same images, tmpfs, shared namespace | no persistence either way |
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
