# F2-CP10 — Platform grants (F2-T10) implementation report

Date: 2026-11-25. **Status: F2-T10 — IMPLEMENTATION COMPLETED / READY FOR INDEPENDENT SECURITY REVIEW.** CP10 is **not** accepted; only the owner accepts it. Authorization: owner order of 2026-11-25 (D47, recorded in `1be3d0d` before any code; [execution order](F2-EXECUTION-ORDER.md)). Starting SHA `b24da2a` (CP09 accepted there). The local FULL CI and the GitHub run of the final SHA are in the owner report (a commit cannot record its own run). Nothing was deployed; no persistent database, active realm or shared service was touched; T11–T13 are not started.

[AT-02 §8](../specifications/AT-02-identity-security.md) · [Decision register](F2-DECISION-REGISTER.md) (D22, D23, D28–D30, D44, D47) · [Criteria](F2-ACCEPTANCE-CRITERIA.md) (AC-PLT) · [CP09 report §11](F2-CP09-RECONCILIATION-REPORT.md#11-remaining-t10t13-obligations)

## 1. What T10 delivers

| Area | Implementation |
|---|---|
| Persistence and lifecycle | Migration **0010** (`migrations/versions/0010_platform_grants.py`, next free number after 0001–0009): table `platform_grants`, `PENDING_APPROVAL → ACTIVE → REVOKED` (and `PENDING_APPROVAL → REVOKED`), expiry computed from the mandatory `expires_at`, never deleted. |
| Catalog (D29) | Exactly five types: `PLATFORM_GRANT_ADMIN`, `PLATFORM_USER_ADMIN`, `PLATFORM_AUDIT_VIEW`, `PLATFORM_VERIFICATION_REVIEW` (contract only, effect F3a), `PLATFORM_ACCOUNT_RECOVERY` (authority only, interface T11). No inheritance, no super type; scope `TENANTS`/`QUEUE` for the verification reviewer only. Lifetimes ≤ 365 days, reviewer ≤ 90, bootstrap ≤ 90. |
| Source of truth | `platform_has_grant(type, tenant)` (SQL, `STABLE`, `SECURITY INVOKER`, `EXECUTE` for the platform role only) reads active, unexpired grants of `app.user_id`. Nothing is cached; no token or cookie carries authority. |
| Request pipeline | `require_platform()` (usable account, per-person limit `AUTH_PLATFORM_PER_MIN_USER`, D38) and `platform_scope()` in `app/api/v1/guards.py`: inside the request scope (session validated again, share-locked for mutations) a **platform-role** transaction reads and **share-locks the caller's own grant**, demands **level two** (ten minutes; five for grant changes) measured from the proof of the factor (F-2), and records `authz.platform_grant.used` in the same transaction. Any refusal rolls everything back and is recorded on its own (`authz.denied`, reason code only). |
| Grant management | `app/platform/service.py`, routes in `app/api/v1/platform_grants.py`: `GET /platform/grant-types`, `GET /platform/grants` (signed cursor, filters), `POST /platform/grants`, `POST /platform/grants/{id}/approve`, `…/reject`, `…/revoke`. |
| Privileged authentication | A grant takes effect only for an **active** account with a **permanent factor** (one-time code or passkey; recovery codes alone are refused) at the identity provider, and only after the provider marked the account **`at_mfa_mandatory`** (and `at_mfa_required`): the switch-off is then refused by the application and by the Keycloak provider itself (D22, D44). |
| Bootstrap (D30) | `scripts/identity/bootstrap_platform_admin.py` → `app/platform/bootstrap.py`: owner credentials only, `ENVIRONMENT` `dev`/`test` only (production refused), existing active person with a permanent factor, one `PLATFORM_GRANT_ADMIN` for ≤ 90 days, provider mark, audit `actor_type=SYSTEM`, `reason_code=BOOTSTRAP`. Creates no account, password or service account. |
| Authorities for other packages | `GrantReviewAuthority` (F-4, D37 `MANUAL_REVIEW`: `PLATFORM_USER_ADMIN`, level two ≤ 5 min, only while the platform transaction holding the grant is open) and `authorize_account_recovery` (controlled recovery: `PLATFORM_ACCOUNT_RECOVERY`, level two ≤ 5 min, never oneself, never an account marked `at_mfa_mandatory`, fails closed when the provider cannot answer). **No route, command or task calls either** (interfaces: T11). |
| Platform role policies | `users`: read with `PLATFORM_USER_ADMIN`, or with `PLATFORM_GRANT_ADMIN` only the people a grant names; status columns changeable with `PLATFORM_USER_ADMIN` (used by T11). `user_sessions`: read and revoke with `PLATFORM_USER_ADMIN`. `audit_events`: read with `PLATFORM_AUDIT_VIEW`; insert only own `AUTHZ` records. Tenant tables: nothing (F3a). |
| Notices (D27) | `PLATFORM_GRANT_CHANGED` (Spanish template, no identifiers) to the person when a grant takes effect or an active one ends; best effort after the commit (durable delivery: T11). |

## 2. Migration 0010

| Element | Rule |
|---|---|
| CHECK | type catalog; `expires_at` NOT NULL, in the future at insert/approval, within the type's lifetime; `granted_by <> user_id`; approver ≠ beneficiary and ≠ requester; four-eyes types active only with an approver; bootstrap shape (`granted_by` NULL ⇒ `PLATFORM_GRANT_ADMIN`, `reason='bootstrap'`, ≤ 90 days); scope rules; activation and revocation field pairs; revocation reasons from a closed list. |
| Unique | one live (pending or active) grant per person and type (`platform_grants_live`). |
| Triggers | insert guard (a grant is active at once only for a bootstrap or a type the grantor holds and that needs no four eyes); update guard (immutable columns, only approval or revocation, approver and revoker are `app.user_id`, revoked is final, version counter); **anti-lockout** under an advisory transaction lock (the last active grant administrator is never revoked); beneficiary must be `ACTIVE` (after insert and on activation); no `DELETE` or `TRUNCATE` for anybody, the superuser included. |
| RLS | `ENABLE` + `FORCE`; platform policies require a person in the context and no tenant or sign-in proof; owner policies narrow to the bootstrap (§4, D-T10-06). |
| Privileges | app and worker: none on `platform_grants`. Platform: `SELECT, INSERT` and `UPDATE` of the transition columns; `SELECT` on `users`, `user_sessions`, `SELECT, INSERT` on `audit_events`, `UPDATE` of the status columns of `users` and the revocation columns of `user_sessions`. Explicitly named roles only (R07). |
| Downgrade | exact (`test_rec_migrations_downgrade_to_exactly_what_was_there_and_back[0009]`); upgrade/downgrade/upgrade cycle unchanged. Tested on disposable PostgreSQL 16 only. |

## 3. Security guarantees and their tests

Negative paths first; M = PostgreSQL/Redis tests, K = real Keycloak 26.8.2 with the provider.

| Guarantee | Tests |
|---|---|
| Deny by default; every platform route declared and exercised | `test_workspace_pipeline::test_every_route_declares_its_access…` (6 PLATFORM routes), `…anonymous_callers_are_refused…`; `test_platform_static::test_no_route_reads_a_platform_grant_outside_the_platform_scope`; `test_platform_grants_api::test_without_the_grant_administrator_grant_every_route_is_refused` (M) |
| Database is the only source; revocation and expiry act on the next request | `test_a_revoked_grant_administrator_is_refused_on_the_next_request`, `test_an_expired_grant_is_refused_and_its_expiry_recorded_once` (M), `test_a_grant_works_until_its_expiry_and_not_a_moment_after`, `test_an_expired_or_revoked_grant_gives_no_power`; `test_platform_static::test_the_platform_module_never_reads_a_token_or_a_cookie` |
| TOCTOU: a revocation waits for the request using the grant | `test_a_revocation_waits_for_the_transaction_that_uses_the_grant` (M) |
| No self-grant, no self-approval, four eyes, independent approver | `test_nobody_grants_approves_or_rejects_for_themselves`, `test_four_eyes_types_never_take_effect_at_once`, `test_neither_the_requester_nor_the_beneficiary_approves`, `test_nobody_grants_to_themselves_even_through_sql` (M) |
| No privilege its grantor lacks; no write without the grant administrator grant | `test_a_type_takes_effect_at_once_only_when_its_grantor_holds_it`, `test_a_type_the_requester_holds_takes_effect_at_once_otherwise_it_waits`, `test_without_the_grant_administrator_grant_nothing_can_be_written` (M) |
| Concurrency and replay | `test_two_approvals_at_once_have_exactly_one_winner`, `test_parallel_requests_create_one_grant`, `test_a_repeated_request_decision_or_revocation_changes_nothing`, `test_two_administrators_revoking_each_other_at_once_leave_one` (M) |
| Anti-lockout | `test_the_last_grant_administrator_cannot_be_revoked`, `test_the_last_grant_administrator_stays` (M) |
| Immutability, final revocation, never deleted | `test_an_active_grant_cannot_be_changed` (9 cases), `test_a_revocation_is_final_and_names_its_actor`, `test_grants_are_never_deleted_or_truncated` (4 roles + superuser) (M) |
| Platform role sees nothing without a grant; app/worker have no platform path; grants open no tenant data; tenant roles give no grant | `test_the_platform_role_without_a_grant_sees_nothing`, `test_the_application_and_the_worker_have_no_platform_path`, `test_no_platform_grant_opens_tenant_data`, `test_a_tenant_membership_gives_no_platform_grant`, `test_every_policy_of_the_platform_role_is_behind_a_grant_or_its_own_rows` (M) |
| Separation of duties (verifier, no inheritance) | `test_a_verification_reviewer_has_no_user_or_grant_powers`, `test_a_grant_administrator_inherits_no_other_type`, `test_without_the_user_administrator_grant_status_cannot_change` (M) |
| MFA: no activation through password-only, recovery codes or a stale session | `test_the_person_must_hold_a_permanent_factor_before_a_grant_takes_effect`, `test_bootstrap_needs_a_permanent_factor_too`, `test_when_the_provider_cannot_answer_nothing_takes_effect` (M); `test_a_grant_takes_effect_only_for_a_permanent_factor_and_the_provider_then_keeps_it` (K: password-only and codes-only accounts refused, nothing removed) |
| Level two, five minutes from the real proof | `test_a_grant_holder_without_level_two_is_asked_for_it`, `test_grant_changes_need_a_factor_proven_within_five_minutes`, `test_a_mobile_caller_needs_the_same_level_two_from_its_token` (M); `test_grant_changes_count_five_minutes_from_the_real_proof_of_the_factor`, `test_a_sign_in_without_the_step_up_does_not_open_the_platform` (K) |
| The factor stays mandatory | `test_a_grant_holder_can_no_longer_switch_the_second_factor_off` (M); K: the provider refuses `at-disable-mfa` itself and the application answers 403 `SECOND_FACTOR_MANDATORY`; `test_the_admin_client_marks_the_factor_mandatory_and_keeps_everything_else` (K) |
| Audit in the same transaction, append-only, no sensitive data | `test_every_use_is_recorded_and_rolled_back_with_its_action`, `test_a_four_eyes_grant_needs_a_second_administrator_and_ends_at_once` (no address or reason text in any record), `test_auditors_read_the_trail_and_write_only_their_own_grant_records` (M); catalog test includes `authz.platform_grant.rejected` |
| Bootstrap only DEV/CI, owner only, no backdoor | `test_the_bootstrap_*` (6 tests), `test_the_command_refuses_production_and_a_missing_owner`, `test_the_owner_may_only_insert_a_bootstrap_grant_for_the_one_person_it_names` (M) |
| T10 authorities fail closed | `test_a_user_administrator_with_a_fresh_factor_may_decide_a_held_change`, `test_other_grants_or_none_never_decide_a_held_change`, `test_account_recovery_is_authorised_only_with_its_grant_and_never_for_grant_holders` (M); `test_email_change_review::test_no_route_command_or_task_reaches_the_review` (still no caller) |
| CSRF, limits, configuration | `test_cookie_requests_need_the_csrf_token`, `test_platform_routes_are_limited_per_person`, `test_without_the_platform_role_every_platform_route_answers_503`, `test_anonymous_and_unverified_callers_never_reach_the_grants` (M) |

New tests: 72 in `tests/platform/` (33 database, 28 API, 8 bootstrap and authority, 3 static; with parameters more cases) and 4 in `tests/identity/test_platform_grants_keycloak.py`.

## 4. Significant implementation decisions (within the order's autonomy)

| ID | Decision | Why |
|---|---|---|
| D-T10-01 | **Two-step platform context for other people's grant rows.** A policy of `platform_grants` cannot call `platform_has_grant()` (the function reads that table: the policy would recurse). The rows of others are visible to the platform role only inside a transaction in which `app/platform` verified and share-locked the caller's own grant administrator grant and named it in `app.grant_authority` (G5-02 pattern, set in one place, static test). Every **write** is checked against `platform_has_grant()` again by the policies and the triggers, so the setting alone changes nothing. `platform_has_grant` stays `SECURITY INVOKER` as AT-02 §8.2 requires; no `SECURITY DEFINER`. | AT-02 §8.2 as written cannot be built without recursion; this keeps the INVOKER rule and G5-02. |
| D-T10-02 | **Reading of AT-02 §8.3.2** ("no type the grantor does not hold, except grant administrator with four eyes"): a type the requester holds and that needs no four eyes takes effect at once; **any other request waits for a second grant administrator**. | Read literally nobody could ever receive `PLATFORM_USER_ADMIN` or `PLATFORM_AUDIT_VIEW` after a bootstrap that creates only grant administrators; this reading keeps "no single person creates a privilege they do not hold". |
| D-T10-03 | **Approve and reject**: neither the requester nor the beneficiary (four eyes). **Revoke**: any grant administrator, also the requester (withdrawal, reason `WITHDRAWN`) and also for an own grant, except the last active grant administrator. | Removing a privilege never needs four eyes and must be possible at once (immediate revocation). |
| D-T10-04 | **MFA precondition and mark at activation**: list credentials → permanent factor required → `set_factor_mandatory` (`at_mfa_mandatory` and `at_mfa_required`, whole representation written back) → credentials listed again → activation, all inside the grant transaction. Provider failure → 503, nothing stored. T10 **never removes** a mark (a mark left by a failed commit or after a grant ends is the safe direction). | Fails closed; either the grant takes effect with a confirmed factor and mark, or nothing does. |
| D-T10-05 | **Grant administrators read only the people a grant names** (not all users); user administrators read all. | Least privilege; enough to check the beneficiary and to show grants. |
| D-T10-06 | **Owner bootstrap policies**: read the one account named in `app.bootstrap_email`, insert only a bootstrap-shaped grant administrator grant and its `SYSTEM` audit record. | FORCE RLS applies to the owner; the bootstrap must not switch RLS off. |
| D-T10-07 | **Expiry is enforced by time in the database** and recorded (`authz.platform_grant.expired`, once per grant, deduplicated) when first noticed: a refused use, or a new grant that closes the expired live row (reason `EXPIRED`). | No scheduler before T11; authorization never depends on a sweep. |
| D-T10-08 | **No Idempotency-Key** on the grant routes: replay is refused by state (one live grant per person and type; decided requests answer 409). | Same pattern as the accepted CP07/CP08 deviations; no duplicate privilege can arise. |
| D-T10-09 | **Windows**: catalog ≤ 10 min, list and every change ≤ 5 min (AT-02 §10.2 table). | Literal reading of the accepted table. |
| D-T10-10 | Platform audit inserts are limited to category `AUTHZ` (T11 adds its categories); denied attempts are written by the application role in their own transaction. | Least privilege. |
| D-T10-11 | New catalog action `authz.platform_grant.rejected`; new notice kind `PLATFORM_GRANT_CHANGED`. | AT-02 §8.3.4 requires rejection audit and a notice to the person. |
| D-T10-12 | Platform routes accept web, admin-web and mobile sessions alike (AT-02 does not restrict them to the admin origin). | Not specified; recorded for the review (§6, F-T10-05). |

## 5. Deviations and paths

- Files outside the T10 path list of the execution order (all minimal and additive): `app/api/v1/guards.py` (platform guard and scope), `app/api/v1/router.py` (router), `app/auth/idp.py` and `app/auth/idp_admin.py` (`set_factor_mandatory`), `app/auth/runtime.py` (platform session factory, cursor codec), `app/auth/security/notify.py` (notice kind), `app/audit/catalog.py` (one action), `app/api/app.py` (wiring of the platform role and the cursor key; outside D35 like the T09-REC changes, listed for review), `pyproject.toml` (line-length exemptions for two test files). `scripts/identity/**`, `app/platform/**`, `migrations/versions/**`, `tests/**`, `openapi/**` are on the list.
- The provider README planned "T10 sets **and clears** `at_mfa_mandatory`"; T10 only sets it (D-T10-04). Lifting the mark belongs to the T11 operator interface.
- Existing tests changed (AC-CTX-01, each guarantee kept and made exact):

| Test | Before | Now |
|---|---|---|
| `test_role_sql::test_platform_has_no_table_privileges` (F1) | platform role: no table privilege at all | no privilege on a new table; on the schema **exactly** the listed table and column privileges of 0010 |
| `test_role_sql::test_upgrade_downgrade_upgrade_and_schema_contents` (F1) | non-business tables T03–T09 | plus `platform_grants`; its functions present; same RLS/owner checks |
| `test_idempotency::test_idempotency_table_exists_only_as_a_test_fixture` (F1) | head `0009` | head `0010` |
| `test_openapi_contract` path and schema lists (F1) | T06–T09 | plus the six T10 operations and their schemas |
| `test_workspace_pipeline` route registry (T08) | 25 routes | plus 6 `PLATFORM` routes, anonymous refusal on each |
| `test_users_db`, `test_sessions_db`, `test_audit_db`, `test_t03_isolation_rec` (T03–T05) | platform role: permission denied | platform role without a grant: **0 rows**, no change; non-transition columns still refused |
| `test_email_change_review::test_no_route_command_or_task_reaches_the_review` (T09) | no file mentions the module | only the T10 authority mentions it, and **no file calls `resolve_review`** |
| `test_roles_and_migrations::test_rec_migrations_downgrade…` | targets 0006, 0007 | plus 0009 (exact downgrade of 0010) |
| `test_catalog_and_validation` | catalog | plus `authz.platform_grant.rejected` |

## 6. Findings and limitations (none P0, P1 or P2)

| ID | Class | Finding | Handling |
|---|---|---|---|
| F-T10-01 | P3 | `app.grant_authority` is trusted for **reads** of other people's grant rows (D-T10-01): code that set it without the verification could read grants; writes stay verified. Same trust model as `app.user_id`. | Set in one place (static test); review item. |
| F-T10-02 | P3 | A switch-off already past its own check at the provider at the instant the mark is written is not serialised with the admin write (the provider's lock covers its own decisions only). Activation re-reads the credentials afterwards; the switch-off ends every session; every use still needs level two. | Documented residual; with IR-07 at production review. |
| F-T10-03 | P3 | Level two for platform actions accepts any registered second factor, recovery codes included (accepted F-1R (d), D46), for an account that holds a permanent factor. Codes-only accounts get no grant and cannot sign in. Requiring a permanent factor for each platform step-up would need an `amr`-style claim from the realm: a new decision. | Owner may decide; not changed. |
| F-T10-04 | P3 | Provider calls run inside the grant transaction (D-T10-04): a slow provider holds the share lock of the caller's session and grant for at most the admin timeout. | Bounded by `AUTH_ADMIN_TIMEOUT_SECONDS`. |
| F-T10-05 | P3 | Platform routes are not restricted to admin-web sessions (D-T10-12). | Review item; would be a policy addition. |
| F-T10-06 | P3 | `PLATFORM_ACCOUNT_RECOVERY` follows AT-02 (single approval when the requester holds it). Its authority refuses accounts marked `at_mfa_mandatory`; the recovery interface (T11) should be reviewed with four eyes in mind. | Recommendation for T11. |
| F-T10-07 | P3 | Expiry is audited when first noticed (D-T10-07), not at the moment it happens. | T11 sweep. |
| F-T10-08 | P3 | Notices are best effort (no durable outbox before T11). | T11. |

## 7. Acceptance criteria (T10)

| Criterion | Result | Evidence (M/K, §3) |
|---|---|---|
| AC-PLT-01 mandatory bounded expiry, closed type catalog, `granted_by ≠ user_id` | PASS | `test_types_and_lifetimes_are_closed_and_bounded` (8), `test_expiry_is_mandatory_and_in_the_future`, `test_nobody_grants_to_themselves_even_through_sql`, `test_only_the_verification_reviewer_has_a_narrower_scope` (6), API validation (11) |
| AC-PLT-02 after activation only revoke; no DELETE | PASS | `test_an_active_grant_cannot_be_changed`, `test_a_revocation_is_final_and_names_its_actor`, `test_grants_are_never_deleted_or_truncated` |
| AC-PLT-03 four eyes; parallel approval one winner | PASS | §3 four eyes and concurrency rows |
| AC-PLT-04 no self-grant; no type the grantor lacks | PASS | §3 escalation rows (D-T10-02) |
| AC-PLT-05 revocation and expiry on the next request; TOCTOU | PASS | §3 database/TOCTOU rows |
| AC-PLT-06 anti-lockout | PASS | §3 |
| AC-PLT-07 platform role without grant 0 rows; app role no platform policies | PASS | §3 visibility rows, `test_every_policy_of_the_platform_role…` |
| AC-PLT-08 verifier has no user/grant powers; no inheritance | PASS | §3 separation row |
| AC-PLT-09 no tenant data through a grant | PASS | `test_no_platform_grant_opens_tenant_data` |
| AC-PLT-10 every use audited in the same transaction | PASS | `test_every_use_is_recorded_and_rolled_back_with_its_action` |
| AC-PLT-11 bootstrap: ACTIVE only, audit SYSTEM, owner credentials, DEV/CI | PASS | §3 bootstrap row; K bootstrap with the real provider |
| AC-PLT-12 migration (0010) up/down/up | PASS | `test_migration_lifecycle_on_fresh_owner_connection_up_down_up`, exact downgrade `[0009]`, CI migration step |
| AC-POL-09 grant holder without MFA cannot use platform routes | PASS | M and K level-two rows; permanent-factor precondition |
| AC-POL-10 (T10 part: five minutes for grant changes) | PASS | `test_grant_changes_need_a_factor_proven_within_five_minutes`, K `test_grant_changes_count_five_minutes…` |
| AC-AUTHZ-03 platform and tenant powers independent | PASS | `test_no_platform_grant_opens_tenant_data`, `test_a_tenant_membership_gives_no_platform_grant` |
| AC-USR-06 platform part ("platform role with a grant") | PASS | `test_user_administrators_read_people_and_sessions_and_change_status`, `test_without_the_user_administrator_grant_status_cannot_change`, `test_users_db::test_nobody_can_delete…` |
| AC-SES-07 platform part (read and revoke with `PLATFORM_USER_ADMIN`) | PASS | same, `test_sessions_db::test_privileges_per_role` |
| AC-AUD-08 grant changes and use | T10 part PASS; criterion stays **PARTIAL** (failed Keycloak sign-ins, administrative actions: T11) | §3 audit row |

## 8. Deferred to T11 (interfaces kept, fail closed)

- Interface and operator identity for the controlled recovery of a locked account (authority: `authorize_account_recovery`) and for setting or lifting `at_mfa_required`/`at_mfa_mandatory` (T10 only sets the mandatory mark, never lifts it).
- F-4 interface for D37 `MANUAL_REVIEW` (authority: `GrantReviewAuthority`); still no route, command or task calls `resolve_review`.
- Platform user administration routes using the `users`/`user_sessions` platform policies (status change with session revocation in one transaction, outbox to Keycloak), audit view route (`PLATFORM_AUDIT_VIEW`), durable notices, expiry sweep, Keycloak event ingestion.

## 9. Production blockers

> **2026-11-28 (D50):** PROD-SEC-01 is closed (IR-05 and IR-06). The current list is [PRODUCTION-READINESS-01](../infrastructure/PRODUCTION-READINESS-01.md); the list below is the historical record.

Unchanged and still mandatory: IR-07; the six time-limited image acceptances (renewal needs a severity recheck; zero CRITICAL confirmed manually before production until INFRA-CI-02 binds severity, D47; since 2026-11-27, D48: IR-05 must be resolved and independently verified before production and the manual check stays until [PROD-SEC-01](../infrastructure/PROD-SEC-01.md) is formally closed); production Keycloak upgrade; persistent migration state (F1 R05); existing realms (provider image, user-profile attributes, reconciliation); O15 mail; R11, R12/O20, trusted proxy networks, O06–O17, D13, D43, password blacklist, AT-20/D42; R10. New with T10:
- **Platform database role** credentials and provisioning (`APP_DB_PLATFORM_USER/PASSWORD`, R11) and **`CURSOR_SIGNING_KEY`**: without them the platform routes answer 503.
- **Production bootstrap** of the first grant administrators: refused by design; needs its own owner approval (D30).
- Existing realms need the `at_mfa_mandatory` user-profile attribute (admin view/edit only) before a grant can take effect there; `at-admin-svc` must be able to write it.
