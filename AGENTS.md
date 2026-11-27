# Instructions for coding agents

AutoTramita.es backend. This file only points to the accepted CI rules; the rules and commands
are maintained in [docs/infrastructure/LOCAL-CI.md](docs/infrastructure/LOCAL-CI.md). If this
file and that document differ, that document is right and this file must be corrected.

## Continuous integration

`.github/workflows/ci.yml` is the single definition of what CI runs. Local CI executes its steps
on the development server.

| When | Command |
|---|---|
| While working | `./scripts/ci/run-fast.sh` |
| The component you changed | `./scripts/ci/run-unit.sh -- <paths>` or `./scripts/ci/run-integration.sh -- <paths>` |
| Identity, migrations, dependencies, API contract | `run-keycloak.sh`, `run-migrations.sh`, `run-security.sh`, `run-contracts.sh` |
| Defined checkpoint (end of a T package) | `./scripts/ci/run-all.sh` |
| Result of the last run | `cat .ci-results/latest/brief.txt` (details: `report.txt`, `summary.json`) |

Rules ([full list](docs/infrastructure/LOCAL-CI.md#rules-for-claude-code-codex-and-other-agents)):

- Never weaken, skip, deselect or remove a test or a security control to make a run pass.
- A targeted, partial or dirty-tree run is never acceptance evidence; neither is an exit code
  other than 0. Report the run id, tested SHA and tree.
- Do not push every intermediate correction. GitHub CI on the exact SHA is the independent
  evidence at the checkpoints and cannot be replaced by a local PASS.
- Workflow triggers, branch protection, the Docker broker policy, host firewall rules and
  production infrastructure change only with the owner's separate approval.
- Stage commits by explicit path: other sessions may have uncommitted work in the same tree.

## Writing tests

Most tests run in parallel workers. A test that races threads, sleeps, uses a lease, expiry or a
fixed port, or measures time belongs in `tests/serial_tests.py`; `tests/test_ci_parallel.py`
fails if it is missing there. Every test creates its own database and roles; do not depend on
state left by another test.
