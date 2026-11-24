# REC-07 — F1 final validation plan
2026-11-24 | v1.0 | PLANNING AUTHORIZED / CORRECTIONS NOT AUTHORIZED / F1 NOT YET ACCEPTED

## Owner decision and evidence baseline
Owner explicitly states: “Prihvaćam CP10 i završetak implementacije T01–T10. Autoriziram REC-07. Prvo pregledaj sve postojeće specifikacije, kod, CI rezultate i otvorene nalaze. Izradi detaljan plan konačne validacije F1 s prioritetima i kriterijima prihvata te ga spremi na GitHub na granu dev. Evidentiraj CP10. Bez implementacije ispravaka u ovom koraku, bez merga u main, bez F2 i bez deploymenta.”
CP10 ACCEPTED; T01–T10 implementation completion accepted collectively. CP01 previously explicitly accepted. Do not invent individual historical CP02–09 approvals or retroactive authorizations. Final F1 acceptance remains separate.
Reviewed baseline dev 5d46c234f75ada37fe7121543fb3236d9d3cdb1f; main 1e8be38a40aac63f5c58d6dbb01daaa051326e6b. GitHub run [45430813346](https://github.com/AutoTramita-es/autotramita/actions/runs/45430813346) verified all three jobs and all steps successful; logs independently confirm 336 passed, one warning in 40.88s, zero skips/failures/errors, mypy 46 files, no leaks, no known vulnerabilities, client generation passed. Earlier T10 run 45430469897 reported failed; correction 5d46c23 changes only test Retry-After upper bound 60 to 120, not limiter. T10 first commit da22db4 also changed tests/test_openapi_contract.py (omitted in report); review exact diff during scope gate.
No tests rerun by planner. Targeted source review, not exhaustive line-by-line security audit or live infrastructure verification.

## Normative sources and precedence
- [AT-01 approved specification](../specifications/AT-01-foundation-infrastructure.md) AC01–15, accepted O01/O02/O03/O18/O19; other 15 decisions remain proposed.
- [G6](../G6-EXECUTION-ORDER.md), [F1 brief](../specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md), [G5](FOUNDATION-G5-REVIEW.md) H1–H6, [roadmap](DESIGN-ROADMAP.md), [blueprint](../MASTER-BLUEPRINT.md), [historical audit](F1-RECONCILIATION-AUDIT.md), [reconciliation plan](F1-RECONCILIATION-PLAN.md), [development guide](../DEVELOPMENT.md).
- ADR-001/002/004/008 govern foundation; ADR-010/011 supersede earlier identity/storage choices. Reopen all relevant ADRs and current sources before executing each packet. Historical status text is not current authorization.
- Reviewed source areas: DB/session, migration guard, role SQL and provisioning, RLS tests, settings, idempotency, pagination, logging, limiter, telemetry, OpenAPI tests/client script, CI workflow, development guide and Gitleaks exceptions. Some files reviewed by targeted excerpts; complete audit is a REC-07 deliverable.

## Priorities and gates
P0 = blocks F1 acceptance; P1 = resolve or explicitly accept bounded residual risk before F1 acceptance; P2 = future phase/live prerequisite, not silently waived. P0 findings cannot be closed by green CI alone. Proposed classification and remedies require owner approval before implementation.
All packets dev only, separate explicit authorization, scoped commit and full isolated CI, STOP for owner review. No shared service access, no business schemas, no deployment, no merge, no F2, no history rewrite, no broad scanner exceptions. Any new architecture choice or out-of-scope file needs explicit approval.

## Findings register
| ID | Priority / gate | Evidence and required outcome |
|---|---|---|
| R01 | P0 / 07.1 | app/core/db.py sessionmaker default autobegin contradicts docstring; manual commit behavior claimed zero rows but context manager may reject further queries. Decide explicit transaction contract (proposed disable implicit transactions and forbid early commit/rollback or document safe rejection); tests prove no protected query outside established context, same connection/transaction, commit/rollback/close. |
| R02 | P0 / 07.1 | migrations/env.py only checks schema_migrations ownership, not superuser/BYPASSRLS or actual owner attributes. Verify expected owner identity and least-privilege attributes, reject privileged impostors and runtime roles even if schema owner; no DDL on rejection. |
| R03 | P0 / 07.1 | _require_owner unconditionally commits supplied connection; proposed reject caller-owned active transaction without commit/rollback, or explicitly approved safe contract. Test caller sentinel changes remain untouched on rejection, migration lifecycle works on fresh owner connection. |
| R04 | P0 / 07.1 | tests/test_rls_harness.py and test_db_layer.py already exercise session_scope and pool reuse; supplement actual scope early commit/rollback/reuse cases, same physical connection, missing context and A/B negative/positive controls, no leak of user/tenant/branch. Worker verified context fixture only; real authorization F2/F3a. |
| R05 | P2 / live gate, P0 if evidence of applied 0002 | G6 records conditional deletion of 0002 and documentary evidence only. Preserve old revision in history; require separate approved read-only inventory of persistent DEV/PROD migration state or equivalent authoritative evidence before first live migration. If condition cannot be established, owner explicitly decides whether F1 can be accepted as local-only with live block; never stamp/drop/restore automatically. |
| R06 | P0 / 07.2 | client_ip trusts configured hop count without verifying peer address. Default zero safe; propose explicit trusted proxy CIDR/peer validation and fail-safe fallback, test direct spoof, malformed/multiple headers, IPv4/v6, multi-hop and missing peer. Real addresses deferred to live gate. |
| R07 | P0 decision / 07.2 | by_principal scopes by tenant, O18 says per user; clarify global user limit vs tenant-user limit and upload/export semantics. Also identity missing currently falls back to IP under same policy; decide fail-closed authenticated/tenant rules before real routes. Test chosen scope across tenants, no quota bypass, all-or-nothing Lua and Redis failure. |
| R08 | P0 / 07.2 | telemetry.route_template reconstructs from request path and stringified params; converter/multi-segment/duplicate values may expose raw path. Use registered template or constant unmatched only; tests include sensitive path/query values, prefixes, converters, repeated params, exceptions and no exporter. |
| R09 | P1 / 07.3 | check-clients.sh uses --skip-validate-spec; test_committed_spec_is_valid_openapi_31 exists. Inspect actual validator coverage and demonstrate independent full OpenAPI validation (or remove skip if compatible); invalid spec must fail CI. |
| R10 | P1 / 07.3 | Dart image now digest-pinned (closed subfinding); Dart generation not analysis/compile, npm transitives unlocked, Node major only. Propose locked npm toolchain, exact Node patch, disposable Dart analysis or documented justified deferral (AC13 requires generation, not full app compilation). No generated clients committed; any new manifest paths separately approved. |
| R11 | P2 / live gate | provision-postgres.py differs from harden.sql (schema_migrations, PUBLIC database TEMP/default function EXECUTE etc.). Before provisioning, reconcile exact grants and test disposable target; no script execution against shared host. Separate approval outside F1 paths. |
| R12 | P2 / live gate | O20 readiness remains proposed; public health liveness only. Decide internal readiness semantics, dependency failures and monitoring before live; no sensitive public details. |
| R13 | P0 scope / 07.4 | main..dev includes maintenance assets/Compose, DNS doc, blueprint, AT-05 plan, G6/brief/plan and .gitleaksignore. Classify each by origin and authorization; preserve history; owner explicitly decides release inclusion/exclusion. Review maintenance routing and assets without changing live service. Review all historical exact Gitleaks fingerprints, not just latest synthetic UUID; no blanket exclusions. |
| R14 | P0 / 07.4 | stale status in G6/brief/blueprint/spec/plan; record CP10 and collective completion now, reconcile individual historical evidence without fabricating approvals. Final AC matrix, decision register and release boundary consistent. |
| R15 | P1 / 07.3 | one Starlette/HTTPX warning, timing-dependent Redis tests; reproduce warning and classify, prefer deterministic boundary tests using Redis time; repeated isolated CI regression, no loosening assertions to mask defects. Verify Retry-After 120 bound and actual computed wait. |

## Execution packets (proposed)
- REC-07.0 planning: this document and CP10 record only. STOP V0 for approval.
- REC-07.1 database/security: R01–04, review complete DB/config/migration/role/RLS source and tests; allowed app/core/db.py, migrations/env.py, relevant tests, DEVELOPMENT.md; any other path requires approval. Real PG16 disposable only. STOP V1.
- REC-07.2 API security/privacy: R06–08, review idempotency/cursor/error/redaction and limiter against accepted O02/O03/O18/O19; resolve R07 before code. Allowed app/core/ratelimit.py, config.py, app/api/telemetry.py and relevant tests/docs; other fixes separately scoped. Real Redis7 and PG16 as needed. STOP V2.
- REC-07.3 contract/CI: R09/10/15, review workflow pins, no skipped tests, all suites counted, no deploy, client validation and dependency audit; allowed openapi/**, .github/workflows/**, relevant tests, DEVELOPMENT.md; new dependency/manifest paths require explicit approval. STOP V3.
- REC-07.4 scope/documentation: R05/11/12 live gates, R13/14; inventory main..dev exact files and approvals, review Gitleaks fingerprints, verify archive unchanged, record deferred decisions and owner release selection. Documentation only unless separately authorized. STOP V4.
- REC-07.5 final acceptance: clean checkout of candidate SHA, locked sync and lock check, Ruff/mypy, full pytest on isolated PG16/Redis7 with zero skips, role SQL twice, migrations up/down/re-up, schema/catalog diff, OpenAPI validation/drift and client generation, full history secret scan and dependency audit. Review exact commit diff, no business tables/generated clients/real secrets, rollback guide. Record logs/run SHA, test counts, exceptions, AC matrix and all findings dispositions. STOP V5 for explicit owner F1 acceptance; no automatic merge or F2.

## AC evidence matrix (preliminary, not final acceptance)
| AC | Current evidence | Final exit |
|---|---|---|
| 01 | CI locked sync; operator reports clean local sync | clean candidate reproducibility, exact versions, residual toolchain limits R10 |
| 02 | settings tests, Gitleaks green | inspect masking/error/log paths and fingerprint exceptions R13 |
| 03 | named migration cycle CI green | R02/R03, disposable owner cycle and no business schema |
| 04 | role SQL/negative tests green | R02 and catalog assertions for all roles |
| 05 | FORCE RLS/missing context tests green | repeat real nonowner fixtures |
| 06 | forged writes/read/join tests green | repeat all cross-tenant negatives and positive controls |
| 07 | composite FK tests green | repeat cross-tenant FK rejection |
| 08 | pool/rollback tests green | R01/R04 actual session lifecycle evidence |
| 09 | worker role and synthetic independent context tested | accept F1 fixture scope only if owner agrees; actual Celery/context verification future gate |
| 10 | API and idempotency fixture tests green | verify accepted contract, replay authorization, atomicity, 24h, cursor binding, optimistic concurrency; no business persistence |
| 11 | real Redis tests green | R06/R07/R15; fail closed 503 Retry-After 5, atomic all limits, scope and spoof tests |
| 12 | health/log/OTel tests green | R08 privacy, request ID, no sensitive health details; R12 deferred live |
| 13 | health/Problem contract and TS/Dart generation green | R09/R10, explicit F1-only coverage |
| 14 | all three CI jobs green | full candidate run, zero skips, pins and audit evidence |
| 15 | DEVELOPMENT rollback and no business schema reported | R13/R14 scope/approval review and rollback verification |

## Final decision rule
All P0 closed with evidence, P1 closed or explicitly accepted by owner with rationale, P2 assigned phase/live gate and owner acknowledgment. No unconditional PASS for unverified persistent migration state. Record final candidate SHA and CI run, AC01–15 disposition (PASS / bounded scope / blocked), all findings, no deployment implication. Merge/release and live infrastructure require separate approvals; F2 requires separate brief and authorization. Documentation commits may trigger CI; final evidence must identify the actual tested candidate, not assume later runs passed.
