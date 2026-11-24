# REC-07.5 — F1 final validation evidence
2026-11-24 | STOP V5 | validation only: no code change, no merge, no deployment | **owner F1 acceptance pending**
[Validation plan](F1-FINAL-VALIDATION-PLAN.md) | [Reconciliation plan](F1-RECONCILIATION-PLAN.md) | [Scope review](F1-REC-07-4-SCOPE-REVIEW.md)

## 1. Candidate and evidence
- **Candidate SHA: `0fa6cab58feb4c74ea773548b2b162d43545a4ec`** on `dev` (main unchanged at 1e8be38a40aac63f5c58d6dbb01daaa051326e6b). Later commits on dev contain only this document and plan records (verify with `git diff 0fa6cab..HEAD --stat`: documentation paths only).
- **CI run [45442918072](https://github.com/AutoTramita-es/autotramita/actions/runs/45442918072)** on exactly that SHA: three jobs passed.
  - Fresh GitHub runner checkout; PostgreSQL 16 and Redis 7 service containers pinned by digest; `uv sync --locked` (54 packages resolved).
  - Ruff lint clean, format check (109 files) clean, mypy 47 files clean.
  - pytest with `-W error` (single exact ignore for the known Starlette/httpx deprecation): **419 passed, 0 failed, 0 errors, 0 skipped** (junit gate).
  - Rate-limit file repeated three more times: 59 passed each.
  - Owner-migration step (upgrade head, downgrade base, upgrade again; role SQL applied twice; non-owner refusal): 6 passed.
  - OpenAPI: independent validator OK, drift check OK, TypeScript (locked npm toolchain) and Dart generation passed; "Client generation check passed".
  - Secret scan over full history: 451 commits scanned, no leaks. Dependency audit (pip-audit 2.10.1, locked set): no known vulnerabilities.
- **Independent local clean clone** of the pre-final candidate 98b73fa (scratch directory, `--no-hardlinks`): `uv lock --check` consistent, `uv sync --locked`, Ruff, format, mypy clean, OpenAPI drift OK and validator OK, 257 passed with the 162 PostgreSQL/Redis tests skipped because no database was available locally (not acceptance evidence; the CI run above is). The only change since is one documentation line.
- No test was run against shared infrastructure; no database, host, Docker, DNS or Traefik state was read or changed.

## 2. Exact-diff review (`main..dev`, 81 files)
- No business tables or policies: the only migration (0001) creates the three RLS context functions; probe tables exist only in test fixtures created per disposable database.
- No generated client committed (no `.dart`, `pubspec`, `schema.d.ts`); `openapi/` holds the contract, script and the locked npm manifest.
- No business modules: `app/auth|tenants|customers|cases|documents|billing|credit` contain only pre-existing `.gitkeep` files.
- No real secrets: no credential-like literals in `app/`; `.env.*.example` files are unchanged from main; `.gitleaksignore` holds five exact commit-and-line fingerprints (three original, two approved in CP14), no wildcards.
- Outside F1 by origin (owner release selection pending, see scope review §2 and §7): `maintenance/`, `docker-compose.maintenance.yml`, `docs/DNS-NEXTCLOUD-MAIL.md` edits, `docs/specifications/AT-05-BOE-vehicle-catalog-plan.md`.
- No deployment job, no secret use, read-only workflow permissions (guarded by `tests/test_ci_workflow.py`).

## 3. Rollback review
`docs/DEVELOPMENT.md` "Rollback" reviewed: code by `git revert` on dev (no history rewrite), database by `alembic downgrade base` plus idempotent `harden.sql` on disposable or explicitly provisioned databases only, OpenAPI regenerated after a revert. Verified by evidence: downgrade to base and re-upgrade, and role SQL twice, run in CI on every push. Not exercised: an actual revert of a code commit (procedure is standard git; no deployment exists to roll back). Stale "known limit" about unlocked npm packages corrected in 0fa6cab.

## 4. AC01–15 disposition
| AC | Disposition | Basis and bound |
|---|---|---|
| 01 | PASS | locked sync on clean runner and clean clone, exact pins; Dart output not analyzed (R10, owner-deferred) |
| 02 | PASS | settings masking/error tests, secret scan, fingerprints reviewed |
| 03 | PASS (local/CI) | migration cycle and R02/R03 tests; persistent DEV/PROD migration state unverified (R05 live gate) |
| 04 | PASS | role attribute and escalation tests, impostor rejection (R02) |
| 05 | PASS | FORCE RLS and missing-context tests on real non-owner roles |
| 06 | PASS | forged write, cross-tenant read and join tests with positive controls |
| 07 | PASS | composite FK cross-tenant rejection |
| 08 | PASS | pool reuse, early commit/rollback/close and error scopes on one physical connection (R01/R04) |
| 09 | BOUNDED SCOPE | worker role and synthetic independent context only; real Celery and authorization are later phases; owner must accept this scope |
| 10 | PASS (F1 scope) | problem+json, cursor, idempotency, optimistic concurrency on fixtures; no business persistence |
| 11 | PASS | real Redis tests, atomic limits, fail-closed 503, spoof, global per-user scope (R06/R07/R15); live proxy networks pending |
| 12 | PASS | liveness only, request ID, log redaction, registered-template spans (R08); readiness O20 pending |
| 13 | PASS (bounded) | contract equals real responses, independent validation, TS and Dart generation; Dart not compiled |
| 14 | PASS | all three CI jobs on the candidate, zero skips, `-W error`, pins, audit, full-history scan |
| 15 | PASS with condition | guide, test report, risks, rollback present, no business tables; "no change outside scope" depends on the owner's release selection for the maintenance/DNS/AT-05 group |

## 5. Findings register — final disposition
| ID | Priority | Disposition |
|---|---|---|
| R01–R04 | P0 | CLOSED (REC-07.1, accepted CP11) |
| R05 | P2 live gate | OPEN by design: read-only inventory of persistent migration state needed before any live migration, or record F1 as local-only |
| R06–R08 | P0 | CLOSED (REC-07.2, accepted CP12) |
| R09, R15 | P1 | CLOSED (REC-07.3, accepted CP13) |
| R10 | P1 | CLOSED except Dart analysis: owner-deferred bounded residual risk |
| R11 | P2 live gate | OPEN: provisioning script lacks `schema_migrations` hand-over and PUBLIC revocations that the migration guard and `harden.sql` require (scope review finding B) |
| R12 | P2 live gate | OPEN: readiness semantics (O20) before live |
| R13 | P0 scope | DOCUMENTED (REC-07.4, accepted CP14); closes fully only when the owner records the release selection |
| R14 | P0 | CLOSED: status pointers, matrix, register, release boundary recorded; this document is the final matrix |
| Finding A | owner decision | OPEN: archive and `f1/foundation` refs absent on GitHub; e22ae3b intact in dev history |

## 6. Exceptions and notes for the owner
- Individual acceptances for CP02–CP09 were never recorded; T01–T10 completion was accepted collectively at CP10. Not back-filled.
- Three commits are authored "Copilot" (T01 toolchain reconciliation, the dev merge, the maintenance page); all are in the reviewed diff.
- One upstream warning remains (Starlette/httpx2) and is explicitly allow-listed; migration to httpx2 is a future dependency change.
- Deferred decisions O04–O17 and O20 remain PROPOSED; O01, O02, O03, O18, O19 remain ACCEPTED. 15 proposed decisions are not changed by F1 acceptance.
- Test count progression: 93, 336, 368, 397, 419, always with zero skipped.

## 7. Decisions requested at STOP V5 (nothing is merged or deployed)
1. Accept F1 (AC01–AC15 as dispositioned above, including AC09 bounded scope and R10 Dart residual) — or list what to rework.
2. Record the **release selection** (everything on dev / F1 plus governance only / F1 stays on dev) and so close R13.
3. Decide **finding A** (recreate the archive ref at e22ae3b, or accept dev history).
4. Acknowledge the **P2 live gates** R05, R11, R12 (and the live proxy networks) as prerequisites for any live step, and decide when finding B is fixed.
5. Merge to `main`, release, deployment and F2 each need a separate authorization.
