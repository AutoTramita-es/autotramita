# AT-01.05 — Claude Code Execution Brief: F1

> **Current status pointer (REC-07.4, 2026-11-24):** F1 implementation T01–T10 is accepted (CP10) and REC-07.1–07.3 are accepted; REC-07.4 and REC-07.5 are accepted; **F1 is ACCEPTED by the owner (CP16, 2026-11-24)**, with release selection, archive ref and live gates still open. The status blocks below are historical records, not current authorization. Authoritative current state: [F1 reconciliation plan](../design/F1-RECONCILIATION-PLAN.md) and [REC-07.4 scope review](../design/F1-REC-07-4-SCOPE-REVIEW.md). Normative requirements are unchanged; no merge, deployment, F2 or shared-infrastructure access is authorized.
Version 1.0 | 2026-11-24 | APPROVED — RECONCILIATION HOLD / NOT ACCEPTED
Owner explicitly approved this brief v1.0 on 2026-11-24 and authorized F1-T01 only. T02–T10, merge and deployment remain unauthorized. Mandatory STOP at CP01.

## Current execution status — REC-02 (documentation addendum; approved v1.0 requirements unchanged)
REC-02 (2026-11-24): F1 implementation exists on f1/foundation at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a, preserved identically in archive/f1-foundation-2026-11-24; not merged or accepted. Historical broad authorization quoted in c467005 ("Autoriziram F1 prema G6-EXECUTION-ORDER.md") is UNVERIFIED: repository record exists, original owner instruction not established; neither confirmed nor invalidated retroactively. Later explicit T01-only authorization b6462e4 / 0973e24 remains recorded; CP01 blocked in preflight, no new implementation authorized or executable during reconciliation. T02–T10 not currently authorized. Audit reports 93 passing CI tests at e22ae3b (run 45398235580), not independently rerun; T01–05/T08–10 PARTIAL, T06–07 NON-COMPLIANT; AC05–08 compliant per reported CI, 7 partial, 3 non-compliant, AC09 not verified. F1 acceptance pending REC-07. REC-01 and REC-02 documentation approved; REC-03–07 require separate approval. No merge, deployment, F2 or infrastructure changes authorized. O01/O02/O03/O18/O19 remain ACCEPTED; 15 deferred decisions remain PROPOSED. Maintenance page and routing reported on implementation branch; live state and separate authorization unverified. Preserve both histories; no duplicate implementation or automatic cherry-pick.

[Audit](../design/F1-RECONCILIATION-AUDIT.md) | [Plan](../design/F1-RECONCILIATION-PLAN.md)

## 1. Normative sources
- [AT-01 v1.1 APPROVED](AT-01-foundation-infrastructure.md), especially §§5–10a, AC01–AC15 and O01/O02/O03/O18/O19.
- [G6 ACCEPTED](../G6-EXECUTION-ORDER.md), exact sequence and scope.
- [G5 H1–H6](../design/FOUNDATION-G5-REVIEW.md); historical proposals superseded by later accepted decisions.
- [ADR register](../adr/ADR-REGISTER.md); [ADR-001](../adr/ADR-001-technology-stack.md), [ADR-002](../adr/ADR-002-multi-tenancy-rls.md), [ADR-004](../adr/ADR-004-api-contracts.md), [ADR-008](../adr/ADR-008-delivery-governance.md) directly govern F1. ADR-003/005/006/007/009/010/011 constrain future phases; no implementation of their business features here.
- [Master blueprint](../MASTER-BLUEPRINT.md), [Design roadmap](../design/DESIGN-ROADMAP.md).
Source snapshot: AT-01 blob eafeba70cbc52183703ae13dc2040a62888f712a; G6 1ce11000e3c6011b41348464866051c684782252; G5 055168d381c471e977746506d1aab5b15f84b77f. Re-read current versions before execution; stop on conflicting changes.

## 2. Execution contract
Goal: reproducible local/CI FastAPI modular monolith foundation with real PostgreSQL 16 RLS and Redis 7 rate limiting, no business tables. Execute only the explicitly authorized task; even authorization of F1 does not imply automatic progression between tasks. Each task ends with tests, scoped commit on dev and report, then STOP for review. No merge to main or deployment without separate approval. Prefer PR after F1 review; do not auto-merge.
Preflight after authorization: verify repository identity, branch, HEAD, git status and existing files; do not overwrite unrelated changes. Record baseline SHA, source versions and exact task authorization. If worktree dirty or source conflicts, stop. Approved active development branch: dev (REC-03); no per-task feature branch required. No force push, reset of user changes, destructive cleanup or bypass of branch protections.
Allowed write paths only: pyproject.toml, uv.lock, .python-version, alembic.ini, app/core/**, app/api/**, migrations/**, tests/**, scripts/db/** (role SQL), openapi/**, .github/workflows/**, docs/DEVELOPMENT.md. Per-task subsets below. Temporary test outputs untracked/outside repo; no generated client commits. No .gitignore or Dependabot config changes outside whitelist without explicit approval.
Forbidden: app/auth, app/tenants, app/customers, app/cases, app/documents, app/billing, app/credit and all business modules; frontend/Flutter app; Keycloak, Nextcloud, Celery, external integrations, real webhooks, SMTP; Compose, secrets, Traefik, Cloudflare, server config; scripts/provision-postgres.py execution against shared DB; real data or credentials. Redis only rate limiting. Local disposable PostgreSQL/Redis or CI service containers only. No production or shared host connections. Verify disposable target before any DDL or destructive test; if uncertain STOP. Never print DSNs, passwords, tokens, raw PII or secret values. Use synthetic fixtures. Do not weaken tests or skip failing checks to obtain green CI.

## 3. Task sequence
All tasks have existing implementation on the preserved branch; none accepted against this brief. T01 historical authorization blocked at preflight; do not execute during reconciliation. See REC-02 status above. Task IDs and checkpoints are organizational labels, not new ADRs. Paths below are permitted subsets, not mandatory filenames. Commands are future examples, not executed here. Run relevant regression tests from previous tasks; record actual commands, exit codes and counts. Missing prerequisites or security failures block progression.

### F1-T01 — Toolchain (G6.1)
Depends: authorization and preflight. Paths: pyproject.toml, uv.lock, .python-version, tests/**, docs/DEVELOPMENT.md.
Deliver: Python 3.12.x exact patch, pinned uv, FastAPI/Pydantic2/SQLAlchemy2/psycopg3/Alembic/HTTPX and compatible OTel dependencies as needed for F1, Redis client, separate dev/runtime Ruff/mypy/pytest. PostgreSQL16 and Redis7 service versions recorded; no Celery runtime or business dependencies needed. Select compatible secure patches, lock transitive dependencies, document tool versions and install instructions. Dependabot proposals only; config outside whitelist deferred.
Tests: clean environment uv sync --locked; uv lock --check; uv run --locked ruff check .; uv run --locked mypy on existing in-scope sources; uv run --locked pytest with meaningful smoke test. Record dependency security review and unresolved advisories; no silent exceptions.
Acceptance: lock reproducible, Python version verified, no unpinned tool bootstrap, no global host changes. AC01/AC14 partial. CP01: toolchain evidence and commit; stop.

### F1-T02 — Settings (G6.2)
Depends T01 accepted. Paths: app/core/**, tests/**, docs/DEVELOPMENT.md.
Deliver Pydantic v2 settings, environment separation, four distinct owner/app/worker/platform DB URLs, safe secret representations and no real defaults. Validate required values for applicable runtime role; no owner credentials required in app runtime. Reserve limiter and F2 Keycloak config keys without implementing auth. No live connectivity at import.
Tests: valid synthetic config, missing/invalid settings, distinct role config, no leakage via repr/errors/logs, environment separation, no accidental network calls. AC02. CP02: settings tests and commit; stop.

### F1-T03 — DB layer (G6.3)
Depends T02. Paths: app/core/**, tests/**, docs/DEVELOPMENT.md.
Deliver synchronous SQLAlchemy2 + psycopg3, role-specific engine/session factories, explicit transaction boundaries and transaction-local set_config('app.user_id', ..., true), set_config('app.tenant_id', ..., true) on the same connection before protected queries. Parameterized values, validated UUID context; no raw request authority. Commit/rollback/close correctly; no context across pooled transactions. No real membership/session tables; trusted test context only. Worker independent context. No platform bypass.
Tests on disposable PG16: same connection/transaction, commit/rollback cleanup, pool reuse with forced same connection, malformed/missing context, exception handling, role selection, no owner use in runtime. AC08/09 partial. CP03: DB evidence and commit; stop.

### F1-T04 — Alembic and roles (G6.4)
Depends T03. Paths: alembic.ini, migrations/**, scripts/db/**, app/core/** if needed, tests/**, docs/DEVELOPMENT.md.
Deliver empty/non-business baseline, owner-only migrations, idempotent role SQL for disposable database: owner owns schema, app/worker/platform nonowner NOBYPASSRLS NOSUPERUSER, least privilege, no role escalation, revoke PUBLIC schema privileges, owner default privileges scoped to needed objects. No shared provisioning script edits or execution. No blanket cross-tenant platform grant.
Tests: apply role SQL twice; inspect pg_roles, ownership, grants and memberships; runtime cannot SET ROLE owner or DDL; migration upgrade head/downgrade base/re-upgrade on disposable DB only; schema diff contains no business tables. AC03/04. CP04: SQL/migration evidence and commit; stop.

### F1-T05 — RLS harness (G6.5)
Depends T04. Paths: tests/**, app/core/** only for required corrections, docs/DEVELOPMENT.md.
Deliver test-only parent/child tenant fixtures with nonnull UUID tenant_id, composite tenant foreign keys, ENABLE and FORCE RLS, USING/WITH CHECK. Create fixtures with owner then exercise real nonowner app/worker/platform connections. Synthetic tenants A/B, explicit user contexts. Do not migrate fixtures into production schema.
Required negative tests: absent context returns zero rows; invalid context fails closed; A cannot read B, update/delete B or insert/update forged B tenant; joins cannot reveal B; cross-tenant composite FK rejected even where FK checks bypass row visibility; runtime cannot SET ROLE owner, disable RLS or bypass it; pool reuse after commit and rollback does not leak user/tenant; worker establishes independent verified test context; platform has no arbitrary access. Positive controls prove A can access authorized A rows, B can access B and valid same-tenant FK works. Assert role and FORCE RLS from catalogs; no SQLite or mock substitute. G5 H2 self-membership bootstrap and H4 grants/audit actual tables deferred F2/F3a.
Acceptance AC04–09 all evidenced. CP05 security gate: any negative failure blocks all subsequent tasks; commit only passing scoped changes; stop.

### F1-T06 — API contracts (G6.6)
Depends T05. Paths: app/core/**, app/api/**, tests/**, docs/DEVELOPMENT.md.
Deliver shared FastAPI/Pydantic conventions /api/v1/, RFC9457 application/problem+json (type/title/status/detail/code/request_id), stable English codes, UUID request ID, redacted logging, snake_case, UUID/ISO8601/UTC/ISO4217/Decimal JSON string. Status mapping exactly AT-01 §10a including 404 invisible, 422 validation, 412 stale and 428 missing If-Match. Cursor default25 min1 max100, opaque tamper-protected, bound to tenant/filter/sort, stable unique tie-breaker, no invented totals. ETag/If-Match optimistic version.
Idempotency-Key max128, recommended UUIDv4, 24h retention, scope actor/tenant/operation/key, SHA256 fingerprint, 400 missing required key, 409 mismatched payload/in-progress, replay completed result after authorization. PostgreSQL is future business transaction source of truth; demonstrate atomicity with disposable test fixtures, no business persistence or Redis idempotency. No real auth endpoints; use synthetic test context, no production test routes.
Tests: response content type/schema/status including validation and redaction; cursor tamper/cross-tenant/filter/sort mismatch, boundaries and deterministic pagination; stale/missing precondition and concurrent update; replay, conflicting payload, concurrent in-flight, rollback, expiration, scope isolation and reauthorization; request ID and no PII/secret leakage. Do not silently choose unresolved architecture for canonicalization, cursor encoding or fixture persistence; stop if decision needed. AC10/12 partial. CP06: contract tests and commit; stop.

### F1-T07 — Rate limiter (G6.6a)
Depends T06. Paths: app/core/**, app/api/**, tests/**, docs/DEVELOPMENT.md.
Deliver Redis7 approximate Sliding Window Counter, atomic Lua and Redis server time, environment/scope/identifier keys with tenant isolation; evaluate all applicable limits together. Configurable defaults per minute: public IP60, authenticated user300, tenant3000, upload user30, export user5. Internal /api/v1/health exempt. F2 reserved config only: 5 failed logins/15min, recovery3/h/account. No Keycloak or actual upload/export endpoints. Trusted proxy handling fail safe; no arbitrary forwarded header trust; live proxy addresses deferred. 429 RATE_LIMIT_EXCEEDED with Retry-After for blocking limits. Redis connect/operation timeout each500ms, no automatic retry/local fallback, failure503 RATE_LIMIT_UNAVAILABLE Retry-After5s, redacted logging. No business jobs/cache.
Tests real disposable Redis7: each limit, reset/expiry, window boundary, simultaneous limits and concurrency, isolation environment/tenant/actor, spoofed headers, configurable override, 429 headers/body, connection and operation failures 503, no retry, health exemption. Test-only route/context for auth/upload/export; no public bypass. Document approximate algorithm and availability tradeoff; no new policy on ambiguous counter semantics without approval. AC11/12 partial. CP07: limiter tests and commit; stop.

### F1-T08 — Health and observability (G6.7)
Depends T07. Paths: app/core/**, app/api/**, tests/**, docs/DEVELOPMENT.md.
Deliver /api/v1/health minimal non-sensitive response, internal exemption, OTel hook only; no exporter credentials, external monitoring, Sentry or live readiness policy. Reuse request ID and redaction.
Tests: health success, no DB/Redis versions/hostnames/secrets, limiter outage does not block exempt health, no external telemetry calls, error logs redacted. AC12. CP08: health evidence and commit; stop.

### F1-T09 — OpenAPI (G6.8)
Depends T08. Paths: openapi/**, app/api/**, app/core/**, tests/**, docs/DEVELOPMENT.md.
Deliver deterministic export from actual FastAPI app, versioned schema, contract checks for actual exposed routes and common response models. Prepare reproducible TS/Dart generation commands with pinned compatible tools; execute generation in CI in T10, outputs temporary only. No frontend/Flutter source or committed generated clients; no fake business endpoints. If tooling requires new paths or architecture decision, stop.
Tests: export twice deterministic, schema parses, actual health/error response contract matches, documented status/headers where applicable, generator smoke on actual schema; no claim of full business client coverage. AC13 partial until CI. CP09: schema evidence and commit; stop.

### F1-T10 — CI and final verification (G6.9)
Depends T09. Paths: .github/workflows/**, tests/**, docs/DEVELOPMENT.md, other allowed paths only for scoped fixes after review.
Deliver GitHub Actions workflow with pinned toolchain/actions, least permissions, PostgreSQL16 and Redis7 service containers with disposable credentials, health waits, uv sync --locked, Ruff, mypy, pytest, owner migration up/down/re-up, secret and dependency scanning, OpenAPI drift and TS/Dart generation checks. No deploy workflow, production secrets, privileged runner or unsafe execution of untrusted PR code with secrets. DEVELOPMENT.md contains clean setup, disposable DB/Redis, role SQL, tests, export, rollback and known limitations. Dependabot config outside whitelist not created.
Tests: clean local full suite and actual CI run; record run URL, commit, job statuses and counts; inspect git diff for scope, secrets, business schema and generated files. If CI cannot be triggered/accessed, report BLOCKED, not PASS. AC01–15 final evidence. CP10: final report, commit and stop; owner review before merge; no F2 or deployment.

## 4. Acceptance traceability
| AT-01 criterion | Evidence task |
|---|---|
| AC01 reproducible local/CI | T01,T10 |
| AC02 settings/secrets | T02,T10 |
| AC03 migration up/down | T04,T10 |
| AC04 role safety | T04,T05 |
| AC05 FORCE RLS/no context | T05 |
| AC06 forged write/read/join | T05 |
| AC07 composite FK | T05 |
| AC08 pool/rollback | T03,T05 |
| AC09 worker context | T03,T05 |
| AC10 API/idempotency/concurrency | T06 |
| AC11 limiter | T07 |
| AC12 health/logs | T06,T07,T08 |
| AC13 OpenAPI/clients | T09,T10 |
| AC14 CI/security | T01,T10 |
| AC15 documentation/scope/rollback | T10 |
Every AC initially NOT RUN; no partial test substitutes for final evidence.

## 5. Stop conditions and rollback
STOP immediately on absent authorization, source conflict, dirty unrelated work, required change outside whitelist, new architecture decision, security test failure, unexpected schema change, external credentials, shared/unknown DB or Redis target, secret exposure, unsafe dependency or unavailable required test environment. Report facts and options; do not auto-fix by weakening policies. Never execute destructive rollback on shared infrastructure. For local disposable resources, document cleanup of only resources created by task; code rollback via reviewed revert of task commit, not force push/reset. Migration downgrade only on verified disposable DB. If secret exposure suspected, stop and report without repeating secret; rotation separately authorized.
O04–O17 and O20 remain PROPOSED, assigned to their AT-01 gates; no implementation or approval here. AT-03 reconciliation before F3a, not F1. F2 requires separate design/authorization.

## 6. Mandatory checkpoint report template
- Task / checkpoint / authorization reference / baseline and final commit SHA / branch.
- Status PASS, FAIL or BLOCKED; AC IDs and evidence per test.
- Files changed and why; scope check; migration/role changes or none.
- Exact commands (redacted), exit codes, test counts, failures/skips, CI URL if applicable.
- Security findings, unresolved decisions, risks and rollback procedure.
- Next dependency; explicit statement STOPPED, awaiting owner instruction.
No PASS if required tests not run or fail. Report partial evidence honestly. Do not claim deployed or implemented beyond tested task.

## 7. Historical handoff prompt (superseded operationally; do not execute during reconciliation)
After separate owner authorization: "Read docs/specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md, approved AT-01 v1.1, G6, G5 and relevant accepted ADRs from the current repository. Verify authorization and preflight. Execute only F1-T01, within its allowed paths and local/CI scope. Run tests, create scoped commit on feature branch, report CP01 and STOP. No next task, merge, shared infrastructure, or deployment."
Authorization granted for T01 only on 2026-11-24; preflight blocked. This prompt is retained for history, not an executable instruction during reconciliation. Resume only after explicit reconciliation gate/task approval.

## 8. Document preparation limitations
Task IDs, checkpoint labels, proposed branch name and example commands are organizational choices. No new architectural decisions approved. No code inspection beyond normative documentation in this preparation, no test execution, no live infrastructure verification. Exact package versions, generator choice and implementation details subject to G6 stop rules. This brief cannot override approved AT-01 or G6.

## REC-03 — Approved DEV/PROD Git policy (2026-11-24)
Owner approved two active branches: dev for all development and integration, main for stable production releases. This supersedes the proposed feature/maintenance branches and the earlier main-only plan. dev maps to Docker project autotramita-dev; main maps to autotramita-prod. Mapping is a policy, not an active deployment connection. No automatic deployment or CI/CD deployment configuration is authorized. Future DEV automation is a separate decision; PROD release and deployment require explicit approval. No production data or secrets in DEV.
REC-03 preparation: create dev from updated main, then integrate f1/foundation into dev with a history-preserving merge after checking conflicts and automation. Preserve newer approved documentation, existing code, maintenance assets and historical records; retain original and archive branches. Review .gitleaksignore and disputed migration 0002 in later authorized work. Do not merge unfinished F1 into main. No new features, live changes or F1 acceptance. REC-04–07 remain unauthorized. Stop if external deployment triggers or loss of content cannot be ruled out. Prior REC-02 status is historical; this section supersedes its branch/merge restrictions only for the approved DEV consolidation preparation. Actual merge remains pending verification.

## REC-04.1 / CP01 acceptance and REC-04.2 authorization (2026-11-24)
Owner explicitly ACCEPTED CP01 / F1-T01. Implementation commit 8e1de017e0dcf2ab1537d432d600b5183a4766b8 on dev; verified CI run 45411248406, all three jobs successful, 93 passed, no skips, one Starlette TestClient/HTTPX deprecation warning, pip-audit no known vulnerabilities. Python 3.12.16, uv 0.13.9, OTel API/SDK 1.45.2; no instrumentation. Warning tracked for later review. Owner authorizes ONLY REC-04.2 / F1-T02 under existing brief and G6 scope, mandatory STOP CP02, owner acceptance required before T03. T03–T10 and deployment not authorized. Work on dev only; main unchanged. This current authorization supersedes earlier historical blocked/not-authorized statements only for T01 acceptance and T02. Full regression may use isolated GitHub Actions services after a scoped dev commit, as previously approved for T01; for T02 use the same CI-only approach only with owner approval if local integration is blocked. No shared infrastructure access or bypass of tool restrictions.

## REC-04.6 / F1-T06 authorization record (2026-11-24)
Owner authorized F1-T06 (API contracts) only, with mandatory STOP CP06. T07–T10, deployment and any change to `main` remain unauthorized; work on `dev` only, no access to shared services. This entry records the T06 authorization and does not formally record acceptance of CP02–CP05, which requires separate owner confirmation.

Approved path exceptions, limited to these two files: removal of `migrations/versions/0002_idempotency_keys.py` and regeneration of `openapi/openapi.json` for the T06 contract change. Removal of 0002 was approved on condition that it was never applied to a persistent DEV or PROD database. Evidence available in the repository (no database was queried): no compose file, script, workflow or Dockerfile runs Alembic; the API image is only the placeholder `autotramita-api:pending`; project documentation states the provisioning script was not executed against the database and the application is not deployed; `.secrets/` holds no `dev.env` or `prod.env`, which the provisioning script needs to create the owner role that migrations require. This is documentary evidence, not a check of the live databases.

Technical decisions approved by the owner for T06: cursors are `base64url(payload).base64url(HMAC-SHA256)` signed with the secret `CURSOR_SIGNING_KEY` (at least 32 bytes, no default, no fallback) and bound to tenant, filter hash, sort and a unique tie-breaker; request fingerprint is SHA-256 over method, operation and canonical JSON (sorted keys, compact, UTF-8, numbers as parsed; non-JSON bodies raw); the idempotency table exists only as a disposable test fixture; error codes are UPPER_SNAKE_CASE with `type` `https://docs.autotramita.es/errors/<kebab-code>`; `CurrencyCode` validates the ISO 4217 format only, not the full registry.

CI-only rule: the owner approved CI-only integration validation (isolated GitHub Actions services after a scoped `dev` commit, no skipped tests) for T06 and for future separately authorized F1 tasks. This is not an authorization to implement those tasks.

## REC-07.0 — CP10 accepted; final validation planning (2026-11-24)
Owner explicitly accepted CP10 and completion of T01–T10 collectively and authorized REC-07 planning only. Baseline dev 5d46c234f75ada37fe7121543fb3236d9d3cdb1f; verified CI run 45430813346 all three jobs passed, 336 passed, zero skipped, one warning, mypy 46 files, no leaks or known vulnerabilities. See [final validation plan](../design/F1-FINAL-VALIDATION-PLAN.md) for R01–R15, AC01–15 and proposed packets. CP01 previously accepted; individual historical CP02–09 approvals not inferred. REC-04–06 implementation complete; F1 final acceptance pending. This entry supersedes stale execution status/authorization text only; normative requirements unchanged. STOP V0: no corrections, merge, F2, deployment or shared infrastructure access authorized. Main remains 1e8be38a40aac63f5c58d6dbb01daaa051326e6b.
