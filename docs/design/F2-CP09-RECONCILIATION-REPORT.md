# F2-CP09 reconciliation — preliminary, blocked

Date: 2026-11-24. F2-T09-REC is authorized; CP09 is **not accepted**. This is an interim report, not acceptance evidence. Initial code SHA: `1e49b43a72b986f80614b7809715dcc4eb4a076a`. Authorization commit: `f7809c326006b9dcf1343a8e82ff53d3e575808c`. No implementation commit or final CI exists yet.

## D37 blocker and proposed minimum

The owner confirmed that the old verified address and login remain unchanged until the new address is verified, and that both addresses receive security notices. D37 is **not implemented**. A PostgreSQL transaction cannot include the Keycloak Admin API. An Admin API timeout can mean the update succeeded even though the response was lost; a crash can also occur after Keycloak changes and before the local transaction commits. The current admin client (`app/auth/idp_admin.py`) has neither an email update nor reconciliation API. The existing notifier (`app/auth/security/notify.py`) is best-effort: SMTP failures are swallowed, and the disabled notifier sends nothing. In-process background tasks can be lost on a crash. Consequently these components alone cannot ensure recoverable synchronization and retryable notices.

Proposed minimum for owner decision: a durable, access-controlled email-change operation record with a hash-only, expiring one-use verification token and a serialized state machine; reserve/check normalized addresses and keep old and new addresses available for recovery and notices. Persist an intent before the Keycloak update, on timeout or restart read Keycloak's actual email, username and verified status, and reconcile idempotently; serialize concurrent changes and fail closed when the outcome is uncertain. After verified Keycloak state, commit the local email, session revocation, audit and two independent durable notification intents atomically. A bounded retry/reconciliation mechanism must process unresolved operations and notices without exposing addresses or tokens to audit/logs. Verification-link delivery needs a separately specified secure design: hash-only token storage is incompatible with simply persisting the raw link for later retries; reissue a fresh token on request or approve an alternative that preserves that constraint. Enforce current authenticated user's identity at confirmation and invalidate replaced/expired tokens. Exact recovery ownership, trigger/scheduling, retention and handling of permanent conflicts require approval; this is a narrow subset, not authorization for all of T11. Production email remains blocked by O15.

The owner explicitly requires a stop when a new architecture decision is needed and asks for a blocker if durable outbox capability is needed. No schema or code for this proposal has been introduced. Platform mandatory-MFA identification also depends on future platform grants; do not claim AC-POL-09 is complete before T10.

## Initial T03 review (not final validation)

| Finding | Initial status | Evidence and remaining work |
|---|---|---|
| R01 bootstrap/authenticated context isolation | OPEN | `tests/test_context_bootstrap.py` permits simultaneous bootstrap subject and session hash and demonstrates combined visibility; inspect real policies and prove mutual isolation, not just pool cleanup. |
| R02 tenant isolation in audit SELECT | OPEN | `0003_audit_events.py` selects by actor/subject and category without a tenant predicate; verify intended global security trail versus tenant context before a safe correction. |
| R03 branch isolation in audit INSERT | OPEN | `audit_insert_app` constrains actor and tenant but does not constrain `branch_id`; test adversarial branch writes. |
| R04 function EXECUTE and PUBLIC | OPEN | `0002_auth_bootstrap_context.py` grants roles but does not explicitly revoke PostgreSQL's default PUBLIC EXECUTE; inspect 0001 and actual effective privileges. |
| R05 audit minimization and full IPs | PARTIAL | `ip_prefix` column restricts masks and `tests/audit/test_catalog_and_validation.py` tests truncation; inspect every free-form column and details against raw IPs and secrets before closure. |
| R06 worker audit INSERT privileges | PARTIAL | 0003 grants INSERT with a SYSTEM/IDP RLS policy; `tests/audit/test_audit_db.py` tests allowed actors and denial of USER. Effective role/default privileges and policy breadth still need full review. |
| R07 explicit expected DB roles in migrations | OPEN | 0002/0003 discover roles by suffix and CONNECT instead of explicitly verifying the expected roles. |

These statuses are conservative source inspection, not a claim that an attack has been reproduced or that all acceptance tests were run. Correcting findings remains in the authorized scope if it does not require a new decision.

## Other observations and outstanding review

- Baseline GitHub Actions [run 45478037858](https://github.com/AutoTramita-es/autotramita/actions/runs/45478037858) reports success for all four jobs and targets the initial SHA. Test counts have not independently been extracted in this review; the handover reports 980 main and 32 Keycloak tests, 0 failures and 0 skips. This run is not evidence for REC.
- `JwksCache.key` continues accepting a cached known key indefinitely when refresh fails, despite the 10-minute cache policy (D05). Maximum stale age and fail-closed behavior require correction and testing; exact handling during the minimum refresh interval needs care.
- AC-POL-13 is only referenced by the T09 notes. Mobile user-agent binding is an accepted CP07 deviation; separately verify rotation and refresh reuse evidence before marking the criterion complete.
- Keycloak spike report still identifies untested S1 lock expiry, S2 direct disabled recovery URL and S3 age/max_age and WebAuthn; T09 confirms some other S2/S3 behavior but not these specific checks.
- Mobile back-channel logout remains web-only; notification of session revocation is not wired. DEV/PROD realm imports, token minimization and optional names remain to be checked and implemented where authorized. Owner has now confirmed the latter two architectural decisions.
- Migrations 0002–0006 require review and disposable upgrade/downgrade/upgrade testing; 0006 is session uniqueness, not platform grants as in the original plan. No migration was applied during this review.
- D42 remains OPEN until AT-20; R10 Dart analysis remains deferred. T10–T13 and production blockers remain outstanding.

## Scope and next steps

Only documentation was changed: execution-order authorization and this preliminary report. No shared infrastructure, production service or persistent database was modified; no deployment, merge or T10–T13 work occurred. No final acceptance matrix, complete CI, test count or final SHA is asserted. After the owner decides the minimum durable recovery mechanism, complete implementation and the full reconciliation, verify CI on the exact implementation SHA, and stop at CP09 for explicit acceptance.
