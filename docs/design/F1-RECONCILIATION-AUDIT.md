# F1 reconciliation audit — 2026-11-24
Status: REVIEWED FINDINGS — F1 NOT ACCEPTED
Source: Claude Code read-only audit supplied by owner; findings below are a faithful summary, not independently rerun tests.
Baseline main 0973e24; implementation e22ae3b; common ancestor 8bec72d. Local main was stale. Implementation preceded the later brief and T01-only authorization. Branch G6 records broader authorization (c467005); original owner statement not verified. Do not infer unauthorized historical work solely from later authorization.

## Task findings
| Task | Status | Findings |
|---|---|---|
| T01 | PARTIAL | Python 3.12 not exact patch; OTel missing; lock exists; tool versions and PG16/Redis7 documentation incomplete; audit job green but detailed output not extracted. |
| T02 | PARTIAL | Pydantic SecretStr and reserved Keycloak settings; separate worker URL missing; four role configuration not verified. |
| T03 | PARTIAL | Sync SQLAlchemy/psycopg, transaction-local context and pool tests; separate worker test missing. |
| T04 | PARTIAL | Baseline, harden.sql, role and migration tests; 0002 persistent idempotency schema requires decision. |
| T05 | PARTIAL | FORCE RLS, missing context, forged writes, joins, composite FK, SET ROLE tested; worker/platform coverage incomplete. |
| T06 | NON-COMPLIANT | Lowercase codes, unprotected cursor, O03 mismatch. |
| T07 | NON-COMPLIANT | Fixed window, fail-open default, 250ms timeout, incorrect codes/Retry-After. |
| T08 | PARTIAL | Minimal exempt health; additional readiness endpoint touches DB/Redis; O20 open; OTel hook missing. |
| T09 | PARTIAL | Deterministic export, TS/Dart generation and tests; contracts reflect incorrect codes/headers. |
| T10 | PARTIAL | Green CI; actions tag-pinned not SHA-pinned, uv version unpinned, rollback/version documentation and final report missing. |

## Acceptance criteria
AC01 PARTIAL (CI locked sync; no local clean run); AC02 PARTIAL (settings tests, gitleaks caveat); AC03 PARTIAL (migration tests, 0002 disputed); AC04 PARTIAL (role tests); AC05–08 COMPLIANT per reported CI (FORCE RLS, cross-tenant, composite FK, pool); AC09 NOT VERIFIED (worker); AC10–11 NON-COMPLIANT (API and limiter); AC12–14 PARTIAL (OTel, contract, CI pinning/audit evidence); AC15 NON-COMPLIANT (scope and rollback).
Totals: 4 compliant per reported CI, 7 partial, 3 non-compliant, 1 not verified.

## Accepted decision gaps
O01: exact Python patch and OTel missing; lock mitigates dependency ranges.
O02: RATE_LIMIT_FAIL_OPEN defaults true; 250ms instead of 500ms; lowercase code; missing Retry-After 5.
O03: scope user|method|route plus RLS rather than explicit actor/tenant/operation/key; conflict 422 instead of 409; replay reauthorization absent; canonical JSON fingerprint chosen without explicit decision.
O18: INCR/EXPIRE fixed window, no Redis time, sequential limits; lowercase code; trusted proxy/spoof tests exist.
O19: 412/428, ETag, bounds 25/1/100 and no total present; about:blank, lowercase codes, base64 JSON cursor lacks integrity and tenant/filter/sort binding.
Already accepted decisions remain binding; only unresolved implementation choices require new approval.

## Scope and infrastructure
13 paths reported outside F1 whitelist: docker-compose.maintenance.yml; eight maintenance/** files; .gitleaksignore; docs/DNS-NEXTCLOUD-MAIL.md, docs/MASTER-BLUEPRINT.md, docs/G6-EXECUTION-ORDER.md. Maintenance images not LFS tracked. Gitleaks exceptions refer to reported synthetic identifiers in historical commit dcc2640; review narrowly, do not expose values. These changes may belong to separately authorized work; provenance not established.
Audit reports running autotramita-maintenance container and documentation claiming public PROD routing. Actual tunnel configuration and authorization not verified. Do not stop or change live services.
Migration 0002 creates persistent idempotency_keys with FORCE RLS and sentinel UUID for no tenant. Decide persistence and sentinel separately; no destructive migration on shared DB.

## Reported CI evidence
[Run 45398235580](https://github.com/AutoTramita-es/autotramita/actions/runs/45398235580) at e22ae3b: three jobs green; Ruff, mypy 34 sources, pytest 93 passed/1 warning/no skips, OpenAPI drift and TS/Dart generation. Gitleaks 388 commits with exceptions; dependency audit job green, detailed pip-audit output not extracted. Earlier run 45394666353 failed Dart cleanup (fix 4278f95); 45395262985 cancelled. No local tests run. Evidence is historical and not proof of compliance with later specification.
Original audit was read-only. No implementation acceptance or new authorization implied.
