# F2-CP09 — reconciliation report (F2-T09-REC)

Date: 2026-11-24. **CP09 is not accepted. It is not proposed as ready for acceptance: two P1 items need an owner decision ([F-0 and F-1](#2-decisions-needed-from-the-owner)).** The rest of the authorized package is implemented and verified. T10–T13, merging, deployment, shared infrastructure and persistent migrations were not touched. D42 stays OPEN (AT-20), R10 Dart analysis stays deferred, O15 blocks production mail.

## 1. Exact revision and evidence

| Item | Value |
|---|---|
| REC start (initial code) | `1e49b43a72b986f80614b7809715dcc4eb4a076a` |
| Handover HEAD (start of this takeover) | `b269f6a04e6a8f10d766b6660cb9c261bff457f1`, CI [45495480897](https://github.com/AutoTramita-es/autotramita/actions/runs/45495480897): 1,047 main + 43 Keycloak |
| **Final implementation SHA** | `6ca14ad7f12702cda8defa132104bdac76cb3c14` |
| **CI on that SHA** | [45504609210](https://github.com/AutoTramita-es/autotramita/actions/runs/45504609210) — all four jobs **success** (logs read); Ruff and format clean (215 files), mypy clean (135 files), migration up/down/up and role SQL 6 passed, rate-limit regression 59 passed three times, OpenAPI valid and current, TypeScript and Dart generation passed, gitleaks full history no leaks, pip-audit no known vulnerabilities, DEV and PROD realms imported |
| Main tests | **1,163 passed**, 0 failed, 0 errors, 0 skipped (54 Keycloak tests deselected here, run in their own job) |
| Keycloak tests | **54 passed**, 0 failed, 0 errors, 0 skipped. Total **1,217** |

The documentation commit that adds this report changes no code; it has its own CI run on `dev`.

The "Result" column of the [acceptance matrix](#8-acceptance-matrix-t01t13) was produced from JUnit files of a local run of the same code (PostgreSQL 16, Redis 7, Keycloak 26.4.7, all disposable, loopback only); the generator refuses a row whose named test did not pass. CI evidence for every row is the run above, which runs the same tests with zero skips allowed. `M` = main job, `K` = Keycloak job.

Commits of the package, oldest first: `f7809c3`, `b9ddb61`, `4d9a43e`, `8b6aab0`, `eea8e9e`, `7e50fdc`, `edc407f`, `8892c9f`, `5224927`, `8eb5410`, `7b04049`, `cc20634`, `b7477e4`, `ab3fa69`, `ba8501a`, `b269f6a` (before the takeover); `a55ed21` (T03 findings), `731e6cb` (D37 hardening and stale sign-ins), `6ca14ad` (remaining checks); then the documentation commit.

## 2. Decisions needed from the owner

| ID | Severity | Finding (shown by test) | Options | Recommendation |
|---|---|---|---|---|
| **F-0** | **P1** (AC-POL-05, D20) | After a password reset, old application sessions end at once only if the person ticks “Sign out from other devices” (not preselected; Keycloak 26.4.7 has no realm setting for it). Otherwise Keycloak sends nothing and a stolen application session stays usable until the next sign-in of that account or its own limits (web idle 30 min / 12 h absolute; mobile 7 d / 30 d). The pending-reset marker lives 24 h: if nobody signs in within that time the check never happens, and a mobile session can then run to its own limits. Fixed in this package: that next sign-in can no longer keep or reopen an old session. | (a) authorize a narrow periodic check of pending password-change markers (reuse of the 60 s worker; new mechanism); (b) close it with the T11 event feed (D32) and accept AC-POL-05 as BOUNDED until then; (c) pre-select the box in a Keycloak theme (the person can untick it; new artefact) | (a) if CP09 must have no open P1; otherwise (b), recorded as BOUNDED |
| **F-1** | **P1** (AC-POL-10, D22/D23; blocks T10) | A person whose only second factor is a passkey reaches LoA2 with the password alone: the committed flow knows only one-time codes and offers to set one up. The same person's passkey can then be removed through the application. The application does not offer passkey enrolment, but Keycloak does (`kc_action=webauthn-register`, account console). By the same flow this applies to a recovery-codes-only account (not separately tested). Changing the flow is an architecture decision, so nothing was changed. | (a) add WebAuthn as an alternative in the LoA2 sub-flow, conditional on the person's credentials; (b) disable the two passkey registration actions until (a) exists | (b) now, (a) as part of the T10 design |
| F-2 | P2 | An MFA step-up answered silently by single sign-on (Keycloak accepts a second factor up to 600 s old) records `step_up_at = now`, so a “≤ 10 min” action can be up to about 20 min after the code was typed. AT-02 §7.6 mentions `prompt=login`/`max_age`; the T06 behaviour accepted at CP06 sends neither for MFA. Seen in code, not reproduced by a test. | send `max_age=0` for MFA step-up, or record the time of the code | decide before T10 (grant changes need ≤ 5 min) |
| F-3 | confirmation | D37 and password change require a fresh **password** (LoA1), also from people who have TOTP. This matches AT-02 §7.2 for password change; D23 does not say whether people with MFA must use it for these actions. | keep, or require LoA2 when a second factor exists | owner confirms |
| F-4 | gap, T11 | A D37 operation in `MANUAL_REVIEW` has no resolution path: the trigger allows no transition out of it, there is no operator tool and the approved rules do not say how it ends. Until resolved the person cannot ask again and, if Keycloak already holds the new address, cannot sign in (fail closed). The worker logs a count. Production D37 is disabled (O15). | define resolution rules and tool with T11 | required before D37 is enabled anywhere real |

## 3. D37 — status: implemented and verified; production disabled (O15)

| Requirement | Implementation | Evidence |
|---|---|---|
| Old verified address and login unchanged until confirmed; no way around it | request stores intent only; Keycloak e-mail read-only for the person | `test_the_old_address_and_login_stay_until_the_change_is_confirmed`, K `test_d37_end_to_end_with_real_mail_and_the_periodic_worker`, K `test_d37_cannot_be_bypassed_inside_keycloak` |
| One-use, hash-only, 30-minute token; reissue invalidates | `email_change.py`, 0007 checks | `test_request_reissue_expiry_replay_and_user_binding`, `test_an_expired_token_changes_nothing`, `test_a_token_only_confirms_its_own_operation_of_its_own_person`, `test_only_the_sha256_of_the_verification_token_is_stored` |
| One active request per person; address reservation | partial unique indexes | `test_one_active_operation_and_reserved_address`, `test_concurrent_requests_reserve_the_address_once`, `test_parallel_requests_of_one_person_leave_one_active_request`, `test_concurrent_confirmation_consumes_token_once` |
| Fresh authentication, CSRF, limits, no enumeration | `me.py` guards | `test_both_steps_need_a_fresh_authentication`, `test_confirmation_needs_the_csrf_token_and_a_session`, `test_a_fourth_request_in_an_hour_sends_nothing_and_looks_the_same`, `test_confirmation_is_rate_limited`, `test_other_user_cannot_confirm_and_duplicate_response_is_generic`, `test_account_lookup_and_delivery_are_deferred_after_generic_response` |
| A request dies with a session ended for security; only plain addresses | `confirm_request`, `prepare_new_address` | `test_a_request_dies_with_the_session_the_person_ended`, `test_an_ordinary_sign_out_does_not_cancel_the_request`, `test_an_address_a_mail_library_could_read_differently_is_refused` |
| Confirmation page | fragment, strict CSP, CSRF | `test_the_content_security_policy_hash_is_the_hash_of_the_served_script`, `test_the_confirmation_script_posts_the_fragment_with_the_csrf_token`, `test_the_confirmation_script_sends_nothing_without_a_link_or_a_session` (script executed with Node) |
| Provider identified by immutable `sub`; never linked by address | `idp_admin.py` | K `test_d37_admin_reads_and_changes_only_the_target_subject`, `test_recovery_decision_fails_closed_on_divergent_identity`, K `test_d37_an_address_taken_in_keycloak_is_held_for_review` |
| Durable intent before the external call; unknown outcome fails closed; idempotent | `CONFIRMED` → `APPLYING`, reread of provider state | `test_timeout_after_idp_update_recovers_without_repeating_update`, `test_a_failure_before_the_external_change_is_retried_and_applied_once`, `test_crash_before_local_commit_recovers_from_actual_idp_state`, `test_a_lost_database_connection_after_the_external_change_is_recovered`, K `test_d37_recovers_real_keycloak_change_after_interruption[timeout, before_commit]` |
| Concurrency, leases, fencing | row lock, lease id, write window | `test_two_sweeps_at_once_apply_a_change_exactly_once`, `test_competing_recovery_workers_only_one_claims`, `test_recovery_lease_expiry_fences_the_old_worker`, `test_a_stale_lease_never_reaches_the_identity_provider`, `test_the_external_write_is_not_started_on_a_lease_about_to_end`, `test_nobody_takes_over_while_the_external_call_is_in_flight`, `test_a_lease_that_ends_during_the_call_forbids_the_local_commit`, `test_worker_email_update_requires_matching_unexpired_lease` |
| Atomic finalisation: local address, other sessions, audit, two jobs | `apply_claim` | `test_recovery_atomically_updates_user_sessions_audit_and_two_jobs`, K end-to-end |
| Other devices stay signed out | sign-in older than the change must authenticate again | `test_a_surviving_sign_on_session_cannot_reopen_a_revoked_session`, `test_the_session_that_asked_for_the_change_may_sign_in_again`, `test_a_mobile_app_with_an_older_sign_in_must_authenticate_again`, `test_old_verified_token_cannot_restore_previous_email`, K end-to-end |
| Periodic worker: 60 s, backoff with jitter, restart, `MANUAL_REVIEW` at 10 attempts / 24 h | `recovery_worker.py`, started by the API lifespan | `test_the_periodic_worker_recovers_on_its_own_and_after_a_restart`, `test_periodic_worker_starts_fail_closed_in_production`, `test_a_cycle_that_cannot_run_reports_not_ready_and_the_worker_goes_on`, `test_ten_failed_attempts_end_in_manual_review`, `test_recovery_after_24_hours_moves_to_manual_review`, `test_backoff_doubles_up_to_an_hour_and_keeps_jitter`, `test_one_failing_record_does_not_hold_back_the_others`, `test_an_exhausted_record_does_not_end_the_sweep` |
| Two independent durable notices, stable Message-ID | `email_change_notifications` | `test_each_notice_is_delivered_independently_and_survives_a_restart`, `test_notification_failure_is_durable_and_retried_with_same_id`, `test_a_crashed_delivery_is_claimed_again_after_its_lease`, `test_an_undeliverable_notice_ends_in_manual_review_and_keeps_its_recipient`, `test_real_smtp_sink_recovers_after_outage` |
| Retention ≤ 30 days; unresolved kept; minimisation | `cleanup` | `test_resolved_records_are_removed_after_thirty_days[29, 31]`, `test_unresolved_records_are_kept_however_old`, `test_addresses_of_a_replaced_request_are_dropped`, `test_cleanup_expires_pending_tokens_and_purges_resolved_records` |
| RLS and effective privileges | 0007, 0008 | `test_ownership_state_and_token_constraints`, `test_worker_and_platform_privileges`, `test_effective_privileges_on_both_tables_are_exactly_these`, `test_the_worker_cannot_confirm_or_reopen_a_request` |
| No personal data or tokens in audit and logs | fixed log messages | `test_no_address_token_or_link_reaches_logs_or_audit`, `test_security_modules_log_fixed_messages_only` |

Of the Keycloak tests, seven cases prove D37: the three `test_d37_*` cases in `test_reconciliation_keycloak.py` and four in `test_security_keycloak.py` (admin by subject, confirmation and recovery, two interruption cases).

Limits that remain by design:
- **The provider write cannot be fenced at Keycloak** (no conditional update). The row lock and lease checks stop a stale worker before it writes; a process frozen between that check and the request for longer than the lease, while its database connection is also lost, could still send the confirmed address later. It can only send an address the person confirmed.
- Keycloak sessions are not ended by D37 (T11). Application sessions are, and older sign-ins from other Keycloak sessions must authenticate again; the margin between the two clocks is the token leeway (30 s).
- Delivery is at least once: a crash after SMTP acceptance repeats a notice with the same Message-ID.
- A verification mail that cannot be sent is not retried (raw tokens are never stored); the person asks again.
- The worker runs inside the API process; it is not the T11 outbox or Celery.

## 4. Defects found and corrected in this takeover

| # | Severity | Defect in `b269f6a` | Correction |
|---|---|---|---|
| 1 | P1 | After a reset, a sign-in through a surviving single sign-on session **kept that session, ended the owner's others and consumed the marker**; a later one was accepted freely. Mobile sign-in did not check at all. A second recovery request could hide a completed change. | the marker keeps the earliest request and the handled change; a sign-in older than the new password is ended and the web flow asks for the password once (`prompt=login`); mobile answers `SESSION_REVOKED`; the same after a password change made in the application |
| 2 | P2 | Sessions ended by D37 could be reopened at once through the surviving Keycloak session | fresh authentication required |
| 3 | P2 | A request could be confirmed after the session that made it was revoked for security | confirmation refused |
| 4 | P2 | One failing record, or one move to `MANUAL_REVIEW`, ended the sweep and could close the D37 routes | per-record isolation; escalation separate from claiming |
| 5 | P2 | The provider write started without rechecking the lease | write window check immediately before it |
| 6 | P2 | Addresses such as `name<other@host>` passed validation | plain addresses only |
| 7 | P3 | Replaced requests kept both addresses for 30 days | cleared by the next sweep |
| 8 | P3 | Mobile callers on the API host got an error instead of a link | configured web origin |
| 9 | P2 | R01, R05, R06, R07 gaps listed in §5 | 0007/0008 and `env.py` |

## 5. T03 security findings

| ID | Problem found | Correction | Negative evidence | Status |
|---|---|---|---|---|
| R01 bootstrap/authenticated isolation | Python and `users`/`user_sessions` reads were strict; session insert, audit and D37 policies still answered a mixed context | `RequestContext` exclusivity; 0008 purity on every remaining policy | `test_bootstrap_and_authenticated_contexts_cannot_be_combined`, `test_sql_policies_reject_mixed_bootstrap_and_user_context`, `test_a_person_context_with_a_bootstrap_proof_sees_and_writes_nothing`, `test_a_session_proof_with_a_tenant_reveals_nothing` | **CLOSED** |
| R02 audit SELECT tenant isolation | own rows readable across tenants | 0008 tenant predicate | `test_own_audit_read_is_limited_to_current_tenant`, `test_another_persons_events_of_the_same_tenant_stay_invisible` | **CLOSED** |
| R03 audit INSERT branch isolation | branch unconstrained | branch must be held by the request and carry a tenant | `test_branch_inserts_require_validated_branch`, `test_forged_branch_writes_are_refused_by_the_database` | **CLOSED** |
| R04 PUBLIC EXECUTE | not revoked explicitly | 0008 revokes on every owner function | `test_context_functions_are_not_executable_by_public`, `test_the_migration_removes_a_public_execute_grant_and_strangers_cannot_call` (also: no `SECURITY DEFINER`) | **CLOSED** |
| R05 minimisation and full IP | raw IPs in free text; short mixed-case strings accepted as detail codes | validator and CHECK constraint; codes limited to constants or short identifiers | `test_audit_rejects_sensitive_data_in_unstructured_fields`, `test_a_detail_code_is_a_constant_or_a_short_identifier`, `test_a_full_client_address_is_stored_nowhere` (IPv4 and IPv6 through real routes), `test_database_rejects_full_addresses` | **CLOSED**, residual: syntax cannot recognise every short secret; the per-action allowlist is the control |
| R06 worker audit INSERT | worker could name a person as actor, any actor session, a branch without tenant | 0008 worker policy | `test_worker_may_insert_system_and_idp_events_only_and_cannot_read`, `test_worker_cannot_forge_identity_provider_source`, `test_the_worker_cannot_write_in_a_persons_name`, `test_the_workers_audit_privilege_is_insert_only` | **CLOSED** |
| R07 explicit DB roles | grants followed a name suffix; only 0008 verified, leftovers only on tables and functions | every migration grants to explicitly named roles, verified before anything runs; 0008 refuses leftover table, column, function, schema, policy and PUBLIC privileges | `test_f2_migration_requires_explicit_matching_runtime_roles`, `test_migrations_check_the_named_runtime_roles_before_the_first_statement` (6 cases), `test_f2_migration_rejects_orphaned_historical_grant`, `test_f2_migration_rejects_any_leftover_privilege_or_policy` (5 cases) | **CLOSED** |

## 6. Remaining T01–T09 obligations

| Item | Result |
|---|---|
| AC-POL-13 | PARTIAL: rotation and web UA binding proven; refresh reuse proven at Keycloak only |
| Keycloak S1 lock expiry | proven with a 5 s window; committed 900 s asserted by the linter and spike; the real 15 min were not waited |
| S2 direct disabled recovery URL | proven (`test_s02_direct_recovery_url_is_denied_when_reset_is_disabled`) |
| S3 LoA age / `max_age` | proven: LoA2 asks again after its age (shortened to 5 s; committed 600 s asserted), `max_age=0` asks again; removing OTP needs LoA2 on Keycloak's own pages too |
| S3 WebAuthn | checked with a software authenticator: enrolment works, it is **not** a LoA2 factor (F-1) |
| DEV and PROD realm import | CI step on separate disposable instances |
| Token minimisation; optional names | `test_real_tokens_exclude_profile_and_role_claims`, `test_login_allows_optional_first_and_last_name`, `test_token_scopes_and_optional_names_are_explicit` |
| Mobile back-channel logout | `test_mobile_backchannel_logout_revokes_app_session` |
| Session revocation notices | wired for one/others/all, best effort (`test_revoking_other_sessions_sends_one_notice_after_commit`); durable general notices are T11 |
| JWKS fail-closed | already implemented in `8892c9f`; `test_provider_down_uses_only_unexpired_cached_keys` — not changed |
| Migrations 0002–0007 review | reviewed; 0001–0005 and 0007 now take explicit role names; 0008 corrects policies; downgrade to 0006 and 0007 restores policies, constraints and ACLs exactly (`test_rec_migrations_downgrade_to_exactly_what_was_there_and_back`) |
| T05 deviations | credential rotation, derived CSRF token, `SESSION_LIMIT`: accepted at CP05, unchanged |
| T07 deviations | no Idempotency-Key, no cursor for sessions, no mobile UA binding, migration 0006: accepted at CP07, unchanged |
| T08 deviations | accepted at CP08, unchanged |
| T09 deviation 1 (D37 missing) | closed (§3) |
| T09 deviation 2 (reset detected at next sign-in) | open, F-0 |
| T09 deviation 3 (no second recovery notice) | unchanged: Keycloak's mail is the notice |
| T09 deviation 4 (new-country notice) | open: no geo source decided; blocked/deactivated notices are T11 |
| T09 deviations 5, 6 | closed: token minimisation applied; revocation notices wired |
| T09 deviation 7 | unchanged: audit reason `CREDENTIAL_CHANGED` |
| T09 deviation 8 | unchanged: other background mails can be lost on a crash (T11) |

Observation outside the listed obligations: Keycloak's built-in `admin-cli` client in the application realm keeps direct access grants; D02 excludes them for the three application clients, which the linter checks. Review with the D43 live hardening.

## 7. Migrations, files, changed tests and scope

- 0007 belongs to D37, 0008 to context and audit isolation. 0001–0005, 0007 and 0008 were edited in place: no persistent migration was run by this package; the state of any persistent database stays unverified (F1 R05). **T10 and T11 take the next free numbers (0009 onward).**
- Running any migration now requires the app, worker and platform role names (`.env`: `POSTGRES_USER`, `APP_DB_WORKER_USER`, `APP_DB_PLATFORM_USER`). 0008 validates existing audit rows and ACLs and stops on unsafe data.
- Outside the D35 path list, disclosed for review: `migrations/env.py`, `app/api/app.py` and `app/api/middleware.py` (D35 lists `migrations/versions/**` and `app/api/v1/**`). They carry the role check, the worker lifecycle and the no-store headers.
- Existing tests changed: `test_a_completed_reset_ends_other_sessions_at_the_next_sign_in_and_says_so` now gives the later sign-ins an authentication time after the new password (before, it modelled exactly defect 1) and checks that no second notice is sent; `test_missing_kid_is_rejected` gained an assertion. No test was removed or loosened by the takeover. The uncommitted Keycloak test left by Codex is committed unchanged. Before the takeover, `b7477e4` had replaced the combined-context expectations in `tests/test_context_bootstrap.py` to enforce R01.
- Full file list: `git diff --name-status 1e49b43..6ca14ad`.
- Scope confirmation: work only on `dev`; no new branch, force push, merge, deployment, shared infrastructure change, persistent database, production mail or T10–T13 code. Local verification used disposable PostgreSQL, Redis and Keycloak containers bound to loopback.

## 8. Acceptance matrix T01–T13

`PASS` is evidence, not acceptance. `PARTIAL` and `OPEN` are never treated as `BOUNDED`; only the owner can bound a criterion.

Summary: OPEN (P1): 2; DEFERRED: 34; PARTIAL: 7; PASS: 79; PASS with accepted deviation: 4; total 126.

| Criterion | Status | Implementation | Test(s) | Result (local, same code) | Deviation / dependency |
|---|---|---|---|---|---|
| AC-KC-01 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s07_realm_import_resolves_env_secrets_and_service_account_is_least_privilege` | 1/1 pass (K) | CI identity job imports the test realm into a fresh container; a separate step imports DEV and PROD |
| AC-KC-02 | PASS | `tests/identity/realm_lint.py` | `test_realm_lint::test_linter_rejects_each_violation`<br>`test_realm_lint::test_committed_realms_comply_with_policy` | 25/25 pass (M) | — |
| AC-KC-03 | PASS | `identity/keycloak/realm-template.json` | `test_realm_lint::test_dev_and_prod_share_nothing_environment_specific` | 1/1 pass (M) | DEV/PROD import: CI step, no test-case id |
| AC-KC-04 | PASS | spike report | `test_keycloak_spike::test_s01_temporary_lockout_expires_with_short_test_window`<br>`test_keycloak_spike::test_s02_direct_recovery_url_is_denied_when_reset_is_disabled`<br>`test_keycloak_spike::test_s03_max_age_zero_requires_fresh_login`<br>`test_reconciliation_keycloak::test_s03_level_two_expires_after_its_configured_age`<br>`test_reconciliation_keycloak::test_s03_webauthn_enrols_but_the_realm_does_not_use_it_for_level_two` | 5/5 pass (K) | S1 expiry and S3 age use shortened windows (committed 900 s / 600 s asserted); S3 WebAuthn is disproved as a second level, see F-1 |
| AC-KC-05 | PASS | `identity/keycloak/realm-template.json` | `test_tokens_keycloak::test_rotation_new_realm_key_is_picked_up_without_restart`<br>`test_keycloak_spike::test_kc05_key_rotation_new_key_published_and_old_kept` | 2/2 pass (K) | — |
| AC-KC-06 | PASS | `.github/workflows/ci.yml` | `test_identity_environment::test_test_image_is_pinned_by_digest_to_the_version_in_compose`<br>`test_identity_environment::test_disposable_compose_has_no_persistent_state_and_no_shared_services`<br>`test_ci_workflow::test_runners_images_and_tools_are_pinned` | 3/3 pass (M) | — |
| AC-TOK-01 | PASS | `app/auth/tokens.py` | `test_tokens::test_valid_token_is_accepted_and_exposes_only_identity_fields`<br>`test_tokens_keycloak::test_real_access_token_validates_and_matches_the_user` | 3/3 pass (M+K) | — |
| AC-TOK-02 | PASS | `app/auth/tokens.py` | `test_tokens::test_alg_none_is_rejected`<br>`test_tokens::test_hmac_signed_with_the_public_key_is_rejected_before_key_use`<br>`test_tokens::test_algorithms_outside_the_allowlist_are_rejected` | 8/8 pass (M) | — |
| AC-TOK-03 | PASS | `app/auth/tokens.py` | `test_tokens::test_each_claim_check_rejects_exactly_its_own_violation`<br>`test_tokens::test_an_id_token_shaped_token_is_not_an_access_token` | 17/17 pass (M) | — |
| AC-TOK-04 | PASS | `app/auth/tokens.py` | `test_tokens::test_expiry_boundary_with_leeway`<br>`test_tokens::test_not_before_and_future_issue_time_boundaries` | 2/2 pass (M) | — |
| AC-TOK-05 | PASS | `app/auth/tokens.py` | `test_tokens::test_unknown_kid_triggers_one_refetch_per_interval_then_is_rejected`<br>`test_tokens::test_provider_down_without_cache_fails_closed_with_503`<br>`test_tokens::test_provider_down_uses_only_unexpired_cached_keys` | 3/3 pass (M) | — |
| AC-TOK-06 | PASS | `app/auth/tokens.py` | `test_tokens::test_tokens_never_reach_logs_or_exception_text` | 1/1 pass (M) | — |
| AC-TOK-07 | PASS | `app/auth/tokens.py` | `test_token_mutations::test_switching_off_a_check_is_noticed_by_the_token_tests`<br>`test_token_mutations::test_the_unmutated_copy_passes_and_the_checks_are_found` | 16/16 pass (M) | mutation set covers `verify_signed` and the access-token claim checks; ID and logout validators are covered by negative tests only |
| AC-TOK-08 | PASS | `app/auth/tokens.py` | `test_tokens::test_malformed_input_is_a_401_never_a_server_error`<br>`test_tokens::test_oversized_token_is_rejected_before_parsing` | 14/14 pass (M) | — |
| AC-AUD-01 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_runtime_roles_cannot_update_delete_or_truncate`<br>`test_audit_db::test_trigger_refuses_changes_even_for_a_superuser` | 12/12 pass (M) | — |
| AC-AUD-02 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_forced_rls_and_per_person_visibility`<br>`test_t03_isolation_rec::test_another_persons_events_of_the_same_tenant_stay_invisible`<br>`test_t03_isolation_rec::test_own_audit_read_is_limited_to_current_tenant` | 3/3 pass (M) | platform has no read at all until T10 |
| AC-AUD-03 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_tenant_scope_requires_a_tenant_and_there_is_no_foreign_key`<br>`test_t03_isolation_rec::test_forged_branch_writes_are_refused_by_the_database` | 5/5 pass (M) | — |
| AC-AUD-04 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_catalog_and_validation::test_secret_like_values_are_rejected_in_details`<br>`test_t03_isolation_rec::test_audit_rejects_sensitive_data_in_unstructured_fields`<br>`test_t03_isolation_rec::test_a_detail_code_is_a_constant_or_a_short_identifier`<br>`test_t03_isolation_rec::test_a_full_client_address_is_stored_nowhere`<br>`test_audit_db::test_database_rejects_full_addresses` | 27/27 pass (M) | a short all-lower-case or upper-case secret cannot be told from a code by syntax; the per-action allowlist is the control |
| AC-AUD-05 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_catalog_and_validation::test_every_action_accepts_its_own_allowlisted_details`<br>`test_catalog_and_validation::test_unknown_action_and_unlisted_detail_keys_are_rejected` | 35/35 pass (M) | — |
| AC-AUD-06 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_identity_provider_event_ingestion_is_idempotent` | 1/1 pass (M) | long hashed dedup keys would be refused by 0008; T11 must use provider ids |
| AC-AUD-07 | PASS | 0003 | `test_audit_db::test_downgrade_removes_everything_and_upgrade_restores_it`<br>`test_roles_and_migrations::test_rec_migrations_downgrade_to_exactly_what_was_there_and_back` | 3/3 pass (M) | — |
| AC-AUD-08 | PARTIAL | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_every_catalog_action_can_be_stored`<br>`test_web_flow::test_login_session_logout_and_the_old_cookie_is_dead` | 2/2 pass (M) | failed logins (provider events), grant and administration events: T10–T11 |
| AC-AUD-09 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_audit_rolls_back_with_its_business_transaction`<br>`test_audit_db::test_independent_audit_survives_a_failed_request` | 2/2 pass (M) | — |
| AC-AUD-10 | DEFERRED | — | — | — | T11 |
| AC-AUD-11 | DEFERRED | — | — | — | T11 |
| AC-CTX-01 | PARTIAL | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_context_bootstrap::test_new_fields_default_to_none_and_old_usage_is_unchanged` | 1/1 pass (M) | literal “F1 tests unchanged” is not met: F1 tests were extended for F2 routes, tables, head revision and CI job, and the migration helper now names roles (R07). Owner review |
| AC-CTX-02 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_context_bootstrap::test_bootstrap_context_does_not_leak_through_the_pool` | 1/1 pass (M) | — |
| AC-CTX-03 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py`, 0008 | `test_context_bootstrap::test_bootstrap_fields_are_used_nowhere_outside_the_auth_module_and_the_db_layer`<br>`test_t03_isolation_rec::test_sql_policies_reject_mixed_bootstrap_and_user_context`<br>`test_t03_isolation_rec::test_a_person_context_with_a_bootstrap_proof_sees_and_writes_nothing`<br>`test_t03_isolation_rec::test_a_session_proof_with_a_tenant_reveals_nothing` | 5/5 pass (M) | — |
| AC-CTX-04 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_a_selected_workspace_scopes_every_request_and_client_hints_are_ignored` | 1/1 pass (M) | — |
| AC-CTX-05 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_a_tenant_without_membership_and_a_tenant_that_does_not_exist_answer_the_same` | 1/1 pass (M) | — |
| AC-CTX-06 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_ending_a_membership_blocks_the_next_request_and_other_workspaces_stay_available`<br>`test_workspace_pipeline::test_role_and_branch_changes_apply_immediately` | 3/3 pass (M) | membership port double; real memberships are AT-03 |
| AC-CTX-07 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_two_sessions_of_one_person_keep_their_own_workspace` | 1/1 pass (M) | — |
| AC-CTX-08 | PASS with accepted deviation | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_switching_needs_the_current_version_and_is_audited`<br>`test_workspace_pipeline::test_parallel_switches_from_the_same_version_have_exactly_one_winner` | 2/2 pass (M) | no Idempotency-Key (CP08) |
| AC-CTX-09 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_each_person_only_ever_sees_the_tenant_of_their_workspace`<br>`test_workspace_pipeline::test_the_database_refuses_a_forged_tenant_even_inside_a_valid_scope` | 2/2 pass (M) | — |
| AC-CTX-10 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_an_outage_of_the_membership_store_refuses_workspace_routes_and_selection` | 1/1 pass (M) | — |
| AC-CTX-11 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_tenant_limits_follow_the_validated_workspace_not_client_hints` | 1/1 pass (M) | — |
| AC-CTX-12 | PASS | `app/auth/runtime.py` | `test_workspace_pipeline::test_the_production_authorizer_denies_every_workspace`<br>`test_workspace_pipeline::test_test_doubles_are_never_imported_by_the_application` | 2/2 pass (M) | — |
| AC-USR-01 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_first_login_creates_an_active_user_for_a_verified_email`<br>`test_users_db::test_unverified_email_starts_pending_and_verification_activates_it` | 2/2 pass (M) | — |
| AC-USR-02 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_parallel_first_logins_of_one_subject_create_exactly_one_user` | 1/1 pass (M) | — |
| AC-USR-03 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_same_email_under_another_subject_is_a_conflict_never_a_merge` | 1/1 pass (M) | — |
| AC-USR-04 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_unique_subject_and_email_and_immutable_subject` | 1/1 pass (M) | — |
| AC-USR-05 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_database_status_transitions_match_the_model`<br>`test_email_and_status_model::test_transition_table_is_exactly_the_specified_one` | 13/13 pass (M) | — |
| AC-USR-06 | PARTIAL | `app/auth/users/`, 0004 | `test_users_db::test_application_role_cannot_change_status_but_can_edit_its_profile`<br>`test_users_db::test_nobody_can_delete_and_platform_has_no_access_until_its_grants_exist` | 2/2 pass (M) | “platform only with a grant”: T10 |
| AC-USR-07 | PASS | `app/auth/users/`, 0004, 0008 | `test_users_db::test_rls_a_person_sees_only_the_own_row_and_cannot_forge_or_touch_others` | 1/1 pass (M) | — |
| AC-USR-08 | PASS | `app/auth/users/`, 0004 | `test_users_db::test_users_carry_no_tenant_customer_role_or_membership_columns` | 1/1 pass (M) | — |
| AC-USR-09 | PASS | `app/auth/email.py` | `test_email_and_status_model::test_normalisation_is_deterministic_and_does_not_merge_mailboxes`<br>`test_email_and_status_model::test_plus_tags_and_dots_stay_different_mailboxes` | 7/7 pass (M) | — |
| AC-USR-10 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_a_pending_person_only_reaches_the_routes_that_allow_it` | 1/1 pass (M) | — |
| AC-SES-01 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_database_holds_only_the_hash_and_logs_never_show_the_secret` | 1/1 pass (M) | — |
| AC-SES-02 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_idle_deadline_is_exclusive_and_lifetimes_follow_the_client_type`<br>`test_sessions_db::test_expiry_needs_no_cleanup_job_and_unknown_or_malformed_credentials_are_rejected` | 2/2 pass (M) | — |
| AC-SES-03 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_single_other_and_all_revocation`<br>`test_security_policies::test_revoking_other_sessions_sends_one_notice_after_commit` | 2/2 pass (M) | provider sessions are ended only from T11 |
| AC-SES-04 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_deactivation_revokes_every_session_in_its_own_transaction`<br>`test_sessions_db::test_a_sign_in_cannot_slip_past_a_concurrent_deactivation` | 2/2 pass (M) | — |
| AC-SES-05 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_revocation_waits_for_a_request_in_flight_and_every_later_request_sees_it` | 1/1 pass (M) | — |
| AC-SES-06 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_parallel_sign_ins_never_exceed_the_cap`<br>`test_sessions_db::test_the_oldest_live_sessions_are_evicted_beyond_the_cap` | 2/2 pass (M) | — |
| AC-SES-07 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_people_cannot_see_or_revoke_each_others_sessions`<br>`test_sessions_db::test_privileges_per_role` | 2/2 pass (M) | “platform only with a grant”: T10 |
| AC-SES-08 | PASS with accepted deviation | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_the_database_keeps_immutable_columns_immutable_even_for_a_superuser` | 7/7 pass (M) | credential hash rotation (CP05) |
| AC-SES-09 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_touch_is_throttled_extends_idle_and_never_passes_the_absolute_deadline` | 1/1 pass (M) | — |
| AC-SES-10 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_a_changed_browser_family_revokes_the_session_through_its_own_transaction`<br>`test_sessions_db::test_a_new_country_is_flagged_and_audited_but_does_not_revoke` | 2/2 pass (M) | no country notice and no geo source in production (undecided); mobile has no UA binding (CP07) |
| AC-SES-11 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_rotation_invalidates_the_old_credential_at_once`<br>`test_sessions_db::test_step_up_records_the_level_and_rotates_web_credentials_only` | 2/2 pass (M) | — |
| AC-SES-12 | PASS | 0005 | `test_role_sql::test_upgrade_downgrade_upgrade_and_schema_contents` | 1/1 pass (M) | — |
| AC-WEB-01 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow_keycloak::test_sign_in_session_and_logout_with_keycloak` | 1/1 pass (K) | — |
| AC-WEB-02 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_validators_and_helpers::test_session_cookie_attributes`<br>`test_web_flow::test_cookie_attributes_and_the_flow_cookie_is_cleared` | 2/2 pass (M) | — |
| AC-WEB-03 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow_keycloak::test_a_replayed_keycloak_callback_and_a_foreign_state_are_refused`<br>`test_web_flow::test_a_token_for_another_nonce_is_refused`<br>`test_web_flow::test_pkce_is_enforced_by_the_code_exchange` | 3/3 pass (M+K) | — |
| AC-WEB-04 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_no_token_is_ever_returned_to_the_browser` | 1/1 pass (M) | — |
| AC-WEB-05 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_signing_in_replaces_a_planted_cookie_and_two_sign_ins_never_share_a_credential` | 1/1 pass (M) | — |
| AC-WEB-06 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_validators_and_helpers::test_everything_else_falls_back_to_the_root`<br>`test_validators_and_helpers::test_same_site_paths_are_kept` | 26/26 pass (M) | — |
| AC-WEB-07 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_unsafe_requests_need_the_csrf_token_and_a_proof_of_origin` | 1/1 pass (M) | — |
| AC-WEB-08 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_cookie_and_bearer_together_are_refused_and_no_credential_is_a_401` | 1/1 pass (M) | — |
| AC-WEB-09 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow_keycloak::test_keycloaks_back_channel_logout_token_is_accepted_once_and_ends_the_session`<br>`test_web_flow::test_invalid_logout_requests_are_refused`<br>`test_web_flow::test_a_logout_token_is_accepted_once` | 3/3 pass (M+K) | — |
| AC-WEB-10 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow_keycloak::test_reauthentication_step_up_through_keycloak_rotates_the_credential`<br>`test_validators_and_helpers::test_loa2_needs_a_recorded_second_factor_step_up_within_the_window` | 2/2 pass (M+K) | freshness precision: see F-2 |
| AC-WEB-11 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_every_answer_of_the_sign_in_routes_is_no_store_errors_included` | 1/1 pass (M) | — |
| AC-WEB-12 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_sign_in_routes_have_their_own_ip_limit`<br>`test_web_flow::test_when_the_limiter_is_down_sign_in_fails_closed` | 2/2 pass (M) | — |
| AC-MOB-01 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_opening_a_session_creates_it_once_and_returns_it_afterwards`<br>`test_mobile_flow::test_a_valid_token_without_an_application_session_is_a_401` | 2/2 pass (M) | — |
| AC-MOB-02 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_tokens_that_are_not_mobile_access_tokens_are_refused`<br>`test_mobile_flow::test_another_persons_token_cannot_reach_my_session` | 7/7 pass (M) | — |
| AC-MOB-03 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_a_revoked_session_stays_revoked_although_the_token_is_still_valid` | 1/1 pass (M) | — |
| AC-MOB-04 | PARTIAL | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_keycloak_spike::test_s06_refresh_rotation_and_reuse_detection`<br>`test_reconciliation_keycloak::test_refresh_token_reuse_is_refused_by_keycloak_without_telling_the_application` | 2/2 pass (K) | Keycloak refuses reuse but sends nothing: `REFRESH_REUSE` in the application needs T11 event ingestion |
| AC-MOB-05 | PASS with accepted deviation | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_somebody_elses_or_unknown_sessions_look_like_they_do_not_exist`<br>`test_mobile_flow::test_the_list_shows_my_sessions_only_and_marks_the_current_one` | 2/2 pass (M) | no cursor, at most ten (CP07) |
| AC-MOB-06 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_no_token_of_any_kind_is_ever_stored` | 1/1 pass (M) | — |
| AC-MOB-07 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_parallel_openings_of_one_keycloak_session_give_one_session` | 1/1 pass (M) | — |
| AC-MOB-08 | PASS | `docs/design/F2-MOBILE-AUTH-NOTES.md` | — | — | document artefact; Dart analysis stays deferred (R10) |
| AC-AUTHZ-01 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_every_route_declares_its_access_and_the_set_is_exactly_the_reviewed_one`<br>`test_workspace_pipeline::test_anonymous_callers_are_refused_before_anything_else_on_every_protected_route` | 2/2 pass (M) | — |
| AC-AUTHZ-02 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_workspace_pipeline::test_claims_in_a_token_never_grant_a_workspace_or_a_role`<br>`test_workspace_pipeline::test_ending_a_membership_blocks_the_next_request_and_other_workspaces_stay_available` | 2/2 pass (M) | membership double; AT-03 |
| AC-AUTHZ-03 | DEFERRED | — | — | — | T10 |
| AC-POL-01 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s01_brute_force_five_failures_lock_and_do_not_disclose`<br>`test_keycloak_spike::test_s01_temporary_lockout_expires_with_short_test_window` | 2/2 pass (K) | — |
| AC-POL-02 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s01_brute_force_five_failures_lock_and_do_not_disclose` | 1/1 pass (K) | Keycloak registration still reveals existence (accepted residual, D26) |
| AC-POL-03 | PASS | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | `test_security_policies::test_a_fourth_recovery_request_in_an_hour_sends_nothing_and_looks_the_same`<br>`test_security_policies::test_recovery_is_limited_per_address_of_the_caller_too`<br>`test_security_keycloak::test_the_fourth_recovery_request_in_an_hour_sends_no_fourth_mail` | 3/3 pass (M+K) | — |
| AC-POL-04 | PASS | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | `test_security_policies::test_recovery_answers_every_account_the_same_way`<br>`test_security_policies::test_recovery_does_no_account_dependent_work_before_answering`<br>`test_recovery_timing::test_the_time_to_answer_does_not_depend_on_the_account` | 3/3 pass (M) | — |
| AC-POL-05 | **OPEN (P1)** | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | `test_security_keycloak::test_the_recovery_link_works_once`<br>`test_reconciliation_keycloak::test_a_password_reset_and_the_sessions_that_existed_before_it`<br>`test_security_policies::test_a_sign_on_session_older_than_the_new_password_cannot_open_the_application` | 5/5 pass (M+K) | revocation is immediate only if the person ticks “sign out from other devices”; otherwise old sessions live until a sign-in within 24 h detects the change, or until their own limits. See F-0 |
| AC-POL-06 | PASS | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | `test_security_keycloak::test_password_change_through_keycloak_ends_other_sessions_and_rotates_this_one`<br>`test_reconciliation_keycloak::test_d37_end_to_end_with_real_mail_and_the_periodic_worker`<br>`test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2` | 3/3 pass (M+K) | fresh LoA1 also for people with TOTP: see F-3 |
| AC-POL-07 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s10_password_policy_enforced_including_blacklist` | 1/1 pass (K) | production blacklist is a live prerequisite |
| AC-POL-08 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s03_step_up_loa2_requires_otp_and_loa1_does_not`<br>`test_security_keycloak::test_a_second_factor_is_enrolled_listed_required_for_removal_and_removed` | 2/2 pass (K) | — |
| AC-POL-09 | DEFERRED | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | — | — | T10; F-1 must be decided first |
| AC-POL-10 | **OPEN (P1)** | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | `test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2`<br>`test_reconciliation_keycloak::test_keycloak_needs_level_two_to_remove_a_second_factor`<br>`test_reconciliation_keycloak::test_s03_webauthn_enrols_but_the_realm_does_not_use_it_for_level_two` | 3/3 pass (M+K) | a passkey-only account reaches LoA2 with the password alone (F-1); freshness precision F-2; platform actions T10 |
| AC-POL-11 | PASS | `app/auth/security/notify.py` | `test_security_units::test_every_notice_is_spanish_short_and_carries_nothing_but_the_kind_and_the_time`<br>`test_security_units::test_production_default_sends_nothing_and_smtp_needs_a_host` | 7/7 pass (M) | — |
| AC-POL-12 | PASS with accepted deviation | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_a_logout_token_is_accepted_once`<br>`test_web_flow::test_a_replayed_callback_is_refused` | 2/2 pass (M) | no Idempotency-Key (CP07, CP08) |
| AC-POL-13 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_a_changed_browser_family_revokes_the_session_through_its_own_transaction`<br>`test_sessions_db::test_rotation_invalidates_the_old_credential_at_once`<br>`test_reconciliation_keycloak::test_refresh_token_reuse_is_refused_by_keycloak_without_telling_the_application` | 3/3 pass (M+K) | `REFRESH_REUSE` reason: T11; country notice undecided |
| AC-POL-14 | PASS | `app/core/config.py` | `test_security_units::test_rate_limit_settings_say_the_application_enforces_recovery` | 1/1 pass (M) | — |
| AC-PLT-01 | DEFERRED | — | — | — | T10 |
| AC-PLT-02 | DEFERRED | — | — | — | T10 |
| AC-PLT-03 | DEFERRED | — | — | — | T10 |
| AC-PLT-04 | DEFERRED | — | — | — | T10 |
| AC-PLT-05 | DEFERRED | — | — | — | T10 |
| AC-PLT-06 | DEFERRED | — | — | — | T10 |
| AC-PLT-07 | DEFERRED | — | — | — | T10 |
| AC-PLT-08 | DEFERRED | — | — | — | T10 |
| AC-PLT-09 | DEFERRED | — | — | — | T10 |
| AC-PLT-10 | DEFERRED | — | — | — | T10 |
| AC-PLT-11 | DEFERRED | — | — | — | T10 |
| AC-PLT-12 | DEFERRED | — | — | — | T10; migration is no longer 0006 |
| AC-ADM-01 | DEFERRED | — | — | — | T11 |
| AC-ADM-02 | DEFERRED | — | — | — | T11 |
| AC-ADM-03 | DEFERRED | — | — | — | T11 |
| AC-ADM-04 | DEFERRED | — | — | — | T11 |
| AC-ADM-05 | DEFERRED | — | — | — | T11 |
| AC-ADM-06 | DEFERRED | — | — | — | T11 |
| AC-ADM-07 | DEFERRED | — | — | — | T11 |
| AC-ADM-08 | DEFERRED | — | — | — | T11 |
| AC-ADM-09 | DEFERRED | — | — | — | T11 |
| AC-ADM-10 | DEFERRED | — | — | — | T11; migration is no longer 0007 |
| AC-API-01 | DEFERRED | — | — | — | T12 |
| AC-API-02 | DEFERRED | — | — | — | T12 |
| AC-API-03 | DEFERRED | — | — | — | T12 |
| AC-API-04 | DEFERRED | — | — | — | T12 |
| AC-API-05 | DEFERRED | — | — | — | T12; current drift, validator and client checks pass in CI |
| AC-API-06 | DEFERRED | — | — | — | T12 |
| AC-API-07 | DEFERRED | — | — | — | T12 |
| AC-API-08 | DEFERRED | — | — | — | T12 |

## 9. Open production blockers

R05 (persistent database migration state), R11 (provisioning script vs `harden.sql`, Keycloak database), R12/O20 (readiness), real `TRUSTED_PROXY_CIDRS`, O06–O17 including **O15 mail provider** (D37 and notices stay disabled in production), D13 (same-origin route) and D43 (Keycloak hardening), production password blacklist, AT-20 legal basis and retention (**D42 OPEN**). Added by this report: F-0, F-1 and F-4 before real users.

## 10. Remaining T10–T13 obligations and dependencies

- **T10:** platform grants and mandatory LoA2 for grant holders (AC-PLT, AC-POL-09, AC-AUTHZ-03, platform parts of AC-USR-06 and AC-SES-07); depends on F-1 and F-2.
- **T11:** administration, general durable outbox and Celery, Keycloak event ingestion (immediate reset revocation unless F-0 is closed earlier, `REFRESH_REUSE`, failed logins), ending Keycloak sessions on revocation, D37 manual-review resolution (F-4).
- **T12:** frozen API contract (AC-API).
- **T13:** final acceptance and traceability test (`tests/test_f2_traceability.py`).
