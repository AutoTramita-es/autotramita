# F2-CP09 — reconciliation report (F2-T09-REC)

Date: 2026-11-25. **Status: F2-CP09 — NOT READY FOR OWNER ACCEPTANCE.** One P1 finding stays open (F-1R-B) and needs an owner decision, because every fix found changes an accepted decision ([§2](#2-owner-decision-needed)). F-1R, F-2, F-3 and F-4 are implemented and verified within the limits stated here. T10–T13, merging, deployment, shared infrastructure and persistent migrations were not touched. D42 stays OPEN (AT-20), R10 Dart analysis stays deferred, O15 blocks production mail.

## 1. Revisions and evidence

| Item | Value |
|---|---|
| Start of this order | `ef36c87840d9d01e809b29608ab4eb9adb3eb1bf` |
| **Final implementation SHA** | `7945a060f9d5264348b0d90ca648710f4566ea51` |
| **Local FULL CI on that SHA** | run `20261125-013406-55ff7f`, clean tree (tree `e515d84140652abd204c9e63e9c35c8c5674d4ba`), **PASS**, 352.3 s (main job 350.3 s, Keycloak job 247.8 s, secret scan 4.8 s, audit 4.8 s) |
| **GitHub CI on that SHA** | [45527442553](https://github.com/AutoTramita-es/autotramita/actions/runs/45527442553), all four jobs **success**, about 6.5 min; `compare-github.sh`: **EQUIVALENT** |
| Main tests | **1,359 passed**, 0 failed, 0 errors, 0 skipped (the 118 Keycloak tests run in their own job) |
| Keycloak tests | **118 passed**, 0 failed, 0 errors, 0 skipped. **Total 1,477** distinct tests (previous report: 1,241) |
| Repeated runs in the same CI | migration step 6 passed; rate-limit regression 59 passed three times |
| Other checks | Ruff lint and format, mypy (144 files), upgrade/downgrade/upgrade with role SQL twice, exactly one migration head (local), OpenAPI valid and current, TypeScript and Dart generation, DEV and PROD realm import with flow assertions, gitleaks (525 commits and files) no leaks, pip-audit no known vulnerabilities |

Commits of this order, oldest first: `e8eddf0` (owner authorization, before the code), `84728a8` (realm, F-1R), `eee26a0` (F-2, F-3, refused-attempt audit), `6c37657` (F-4, migration 0009), `7945a06` (Keycloak tests); then the documentation commit that adds this report (no code; its own CI run on `dev`). Earlier packages: see the [execution order](F2-EXECUTION-ORDER.md) and Git history from `1e49b43`.

Development runs that failed before the final one are not evidence; their failures were corrected before the commit. Local CI limits LCI-04 and LCI-05 (network-enabled steps reach host services published on all interfaces) apply as accepted.

The matrix in [§8](#8-acceptance-matrix-t01t13) was generated from the JUnit files of the local run above; the generator refuses a row whose named test is missing or did not pass. `M` = main job, `K` = Keycloak job.

## 2. Owner decision needed

### F-1R-B (P1) — abandoned recovery-code regeneration is served after the password alone

Shown by K `test_open_finding_unfinished_new_recovery_codes_can_be_taken_with_the_password`:
1. A person has a one-time code **and** recovery codes, and uses the last recovery code.
2. Keycloak removes the codes and requires new ones. The person leaves that page. The requirement stays on the account.
3. Somebody who knows only the password signs in. Keycloak serves the pending set-up **without asking for the one-time code**.
4. They create their own codes and reach level two with them. With level two they could then remove the real factor (this follows from the level rule; not separately tested).

Preconditions: all twelve codes used, the mandatory page abandoned, and the password known. The same cause leaves an account whose **only** factor was recovery codes without any factor in step 2; the password alone may then set up a new one (seen in exploration on the same version).

### F-3K (P2) — Keycloak's password form does not ask for the second factor

K `test_open_finding_keycloak_changes_a_password_without_the_second_factor`. With the password alone, `kc_action=UPDATE_PASSWORD` opens the new-password form for a person who has a second factor. `UpdatePassword` is not a credential action in Keycloak 26.4.7, so no level setting covers it (checked in the shipped classes; factor set-up and removal are covered). The application requires the factor before it starts a change, asks the provider for level two, and ends **every** session when a change returns without it. A change made only on Keycloak's pages is not seen before T11. No level is gained: the attacker already knows the password and still cannot pass level two.

### Options

| Option | Change | Closes | Leaves open | Cost |
|---|---|---|---|---|
| **A** (recommended) | Whoever enters the password and has a second factor must prove it in the same sign-in (one more sub-flow at level one) | F-1R-B for every account that has a one-time code or passkey; F-3K | An account with **only** recovery codes still becomes factorless in step 2 | Changes D23 (“level one = password”) for people who enrolled a factor: they enter it at every password sign-in. Nothing changes for people without one (I07) |
| B | Switch the recovery-code enrolment action off, as passkey registration is (F-1 b) | F-1R-B for accounts with another factor; no new recovery-codes-only account | F-3K; an existing codes-only account after its last code | Changes D41: no new recovery codes. A lost authenticator then has no self-service way back |
| A + B | Both | Everything above except an already existing codes-only account | — | Both costs |
| C | Keep as is | — | F-1R-B, F-3K | CP09 cannot be proposed (an open P1) |

A and B were each tried with a one-time-code account on a disposable Keycloak 26.4.7 (exploration, not committed tests): with A a password-only sign-in is asked for the code before a password change, before new recovery codes and before a pending set-up, one code is enough for level two, and people without a factor see no change. With B existing codes still verify and the pending set-up is skipped. The combination was not run. Whichever is chosen needs the realm change, tests that turn the two `test_open_finding_*` tests into protection tests, and a new CI run.

**Recommendation: A**, and rate the remaining codes-only case (suggested P2: it needs an account without any other factor, all codes used and the mandatory page abandoned). Add B only if that case is not acceptable.

Why this was not decided here: the order requires the factor at level two, and both fixes change what an accepted decision says (ADR-008). It is recorded as the architectural blocker of this order.

## 3. Status of the findings

| ID | Status | Summary |
|---|---|---|
| F-0 (a) | **CLOSED within stated limits** | 60 s check ends web and mobile sessions after a reset ([§5](#5-f-0-and-f-1-reviewed-again)) |
| F-1 (b) | **CLOSED** | passkey registration off in all realms |
| F-1R (d) | **Implemented; one P1 left (F-1R-B)** | level two proves any existing factor |
| F-2 | **CLOSED** | window counts from the proven authentication |
| F-3 | **Application path CLOSED; F-3K (P2) open** | account actions need the factor if there is one |
| F-4 | **Domain mechanism CLOSED; interface T11, authorisation T10** | retry or cancel, refused by default |
| R01 bootstrap/user context isolation | **CLOSED** | `test_sql_policies_reject_mixed_bootstrap_and_user_context` and the other tests of the previous report |
| R02 audit read isolation | **CLOSED** | `test_own_audit_read_is_limited_to_current_tenant` |
| R03 audit branch isolation | **CLOSED** | `test_forged_branch_writes_are_refused_by_the_database` |
| R04 PUBLIC EXECUTE | **CLOSED** | `test_context_functions_are_not_executable_by_public`; 0009 keeps privileges |
| R05 audit minimisation and full IP | **CLOSED**, residual: syntax cannot recognise every short secret | `test_a_full_client_address_is_stored_nowhere` |
| R06 worker audit insert | **CLOSED** | `test_the_worker_cannot_write_in_a_persons_name` |
| R07 explicit database roles | **CLOSED** | `test_migrations_check_the_named_runtime_roles_before_the_first_statement` |

R01–R07 here are the T03 findings of F2-T09-REC; the F1 live gate R05 (persistent database state) is separate and **open** ([§6](#6-migrations-and-paths)). All their tests are in the run of §1.

## 4. What was implemented

### Defects found and corrected by this order (1–3 reproduced on Keycloak 26.4.7 before the change)

| # | Severity | Before | Now |
|---|---|---|---|
| 1 | P1 | The built-in `admin-cli` allowed a password grant; for a codes-only account its token deleted the recovery codes through the account API | every password grant is refused (`directGrantFlow`), K `test_no_client_may_exchange_a_password_for_a_token` |
| 2 | P1 | A password alone could create recovery codes on an account with a one-time code (and would have reached level two once codes counted) | Keycloak asks for the existing factor, K `test_the_password_alone_cannot_add_a_factor` |
| 3 | P1 | A codes-only or passkey-only account was offered a new one-time code after the password (F-1R) | asked for its own factor, K `test_with_a_second_factor_the_password_alone_never_reaches_level_two` |
| 4 | P2 | A level-two answer from single sign-on started a new ten-minute window (F-2) | the factor's own time counts, M `test_single_sign_on_does_not_extend_the_window` |
| 5 | P3 | Refused bearer tokens and refused workspaces were not audited (AT-02 §4.3, AC-AUD-08) | recorded without token or tenant, M `test_denied_attempts` |

### F-1R — level two

Flow: password → (level two) any existing factor: one-time code, passkey, passwordless passkey or recovery code; only an account without any factor is offered a one-time code set-up. Proven on Keycloak for seven kinds of account (each factor alone and in pairs): the password alone cannot reach level two, add or remove a factor (own pages, crafted `kc_action`, account API); every factor reaches level two; a recovery code works once; forged passkey and wrong code are refused; a password recovery keeps the factors. The same flow is generated for DEV, TEST and PROD and fixed by the linter. Nothing deletes an existing credential. Registration of passkeys stays off.

Policy limit, unchanged by design: an account **without** a factor may set one up after the password (F-3, I07). T10 must require an enrolled factor before a platform grant takes effect.

### F-2 — step-up window

Keycloak's session note `loa-map` is mapped into the claim `loa_map`; its level-two entry is the time the factor was last proven. Neither single sign-on, a token refresh nor a later password sign-in moves it (K `test_neither_single_sign_on_nor_a_refresh_nor_the_password_moves_the_factor_time`; `auth_time` does move on a password sign-in, so it is not used for level two). The application accepts level two only with that time, measures at most ten minutes from it (configuration can only shorten), sends `prompt=login` for both step-up purposes and refuses an answer older than the request. The stricter five-minute limit is supported and tested at its boundary by the guard; no route uses it before T10. Clock leeway 30 s; a time further in the future is ignored.

### F-3 — account actions

Password change, adding a factor, e-mail change request and confirmation, and “sign out everywhere” ask Keycloak whether the person has a factor on every request: without one a fresh password is enough, with one the factor must have been proven within ten minutes. Removing a factor always needs level two. Provider unreachable or not configured: 503, nothing happens. Forgotten-password recovery is unchanged and needs no factor. Tests M `tests/auth/security/test_account_step_up.py` (four factor kinds × six actions) and K for one-time code, recovery code and passkey.

### F-4 — D37 held in MANUAL_REVIEW

`app/auth/security/email_change_review.py`, migration 0009. `RETRY` returns the operation to the worker (new series of ten attempts / 24 h) only when the provider, read by immutable subject, holds the old or the confirmed address and nothing local conflicts. `CANCEL` frees the address only when the provider proves the change was never made. No address is written by the review. Row lock and advisory lock serialise decisions; repeating one changes nothing; every decision and refusal is audited as `identity.email.change_reviewed` (actor `SYSTEM`) without addresses. Authority is a port that refuses by default; **no route, command or task calls it**. Tests: M `test_email_change_review.py`.

Dependencies: T10 supplies the authority (platform grant, level two ≤ 5 min) and a policy for the platform role; T11 the interface and the operator identity in the audit record. A divergent provider state stays held until a person corrects it at the provider. D37 stays disabled in production (O15).

D37 itself (request, confirmation, recovery worker, notices, retention) is unchanged. Its requirement-by-requirement evidence table is §3 of the [2026-11-24 report](https://github.com/AutoTramita-es/autotramita/blob/8cd58204d40291dace041f62777cf8b6de35971e/docs/design/F2-CP09-RECONCILIATION-REPORT.md); its tests passed again in the run of §1.

### Behaviour changes to note

- An MFA step-up always asks for password and factor again.
- Account actions call the provider; during an outage they answer 503, “sign out everywhere” included (signing out one or all other sessions still works).
- New callback result `security_action=reauthentication_required` (session cookie cleared).
- A realm without the `loa_map` mapper never gives level two (fail closed).
- Expired bearer tokens now create an audit record too; volume is bounded by the per-address rate limit.
- `AUTH_STEP_UP_WINDOW_MINUTES` above 10 is rejected.

## 5. F-0 and F-1 reviewed again

| Subject | State | Evidence or dependency |
|---|---|---|
| Web and mobile sessions after a reset | both end within one worker cycle with `PASSWORD_CHANGED`; neither the old nor a refreshed mobile token opens a new session | K `test_a_reset_ends_web_and_mobile_sessions_and_the_phone_cannot_come_back` (new) |
| 60 s limit | **partial protection**: a stolen session lives until the next cycle plus the sweep (about 60 s); one provider call per pending person per minute per instance; pending people are watched for link lifetime + 1 h, markers expire after 24 h; losing Redis loses the detection | `test_password_check.py` |
| Password changed outside the application's recovery flow | **not detected** until T11 event ingestion (includes F-3K on Keycloak's pages) | T11, AC-AUD-10 |
| Keycloak sessions after a reset or D37 | survive; the application refuses their older sign-in | T11 |
| Production | sessions end, no mail is sent (O15); the worker needs its own database credentials and the admin client, otherwise only the sign-in check works | start-up warning |
| Existing realms | an import changes **nothing** in an existing realm; the flow, grant flow, mapper and required actions must be applied by hand ([identity/README](../../identity/README.md)) | live prerequisite |
| Existing passkeys | kept; asked for at level two after the realm change; registration of new ones stays off | K `test_s03_a_passkey_enrolled_earlier_is_the_second_level` |
| Remaining security dependencies | F-1R-B, F-3K (owner); grant holders must have a factor (T10); event ingestion, Keycloak session revocation, durable notices (T11); D43 admin console hardening, production password blacklist (live) | |

## 6. Migrations and paths

### 0001–0009

| Migration | History in Git |
|---|---|
| 0001–0005 | edited in place once after first commit (`a55ed21`: explicit role names, R07) |
| 0006 | never edited |
| 0007 | created `5224927`, edited in place by `cc20634`, `a55ed21` |
| 0008 | created `b7477e4`, edited in place by `ba8501a`, `a55ed21` |
| 0009 | new in this order; replaces one trigger function's body, no grant, policy or constraint change; downgrade restores it exactly |

**Was an earlier version ever applied to a persistent database? Not confirmable — open blocker.** Non-destructive evidence reviewed: no AutoTramita database volume exists in Docker; the only AutoTramita PostgreSQL containers are two disposable ones from earlier work (`autotramita-d37-pg-ephemeral` and its Redis, still running, not touched); the application is not deployed and the repository documents say its databases and roles were never provisioned; a search of the local agent session logs found no migration or provisioning command against a non-disposable database (provisioning script was only compiled). **Not examined:** the shared PostgreSQL server (access is prohibited), and anything run outside those logs. Before the first persistent migration a separately approved read-only inventory is required (F1 R05); if any of 0001–0008 was applied in an older form, Alembic will not re-run it and the difference must be reconciled first.

On disposable PostgreSQL 16: full upgrade/downgrade/upgrade, role SQL twice, effective privileges and RLS tests, exact downgrade of 0007, 0008 and 0009, and data written under 0008 kept and resolvable after 0009 (`test_a_change_held_before_the_migration_can_be_resolved_after_it`). **T10 and T11 take 0010 onward.**

### Changes outside the D35 path list

This order added none. Earlier ones, with their need (owner review):

| Path | Need |
|---|---|
| `app/api/app.py` | starts and stops the D37 recovery worker and wires the F-0 check; no other place owns the application lifecycle |
| `app/api/middleware.py` | `Cache-Control: no-store` on authentication answers, errors included (AC-WEB-11) |
| `migrations/env.py` | verifies the named runtime roles before any statement (R07) |
| `compose.ci.yml`, `.gitignore`, `scripts/ci/**` | Local CI (INFRA-CI-01, separately authorized; conditionally accepted 2026-11-25) |

## 7. Criteria that stay PARTIAL

| Criterion | Done in T01–T09 | Missing evidence | Package and criterion that must supply it |
|---|---|---|---|
| AC-AUD-08 | sign-in, sign-out, security settings, revocation, context change, refused callbacks, tokens, CSRF and workspaces | failed sign-ins at Keycloak; grant changes; administrative actions | T11 (AC-AUD-10, AC-ADM-01/04), T10 (AC-PLT-10) |
| AC-CTX-01 | context change is additive; all tests green | the words “F1 tests unchanged”: 16 of 21 F1 test files are unchanged, 5 changed: `test_ci_workflow` (job counts), `test_idempotency` (head revision), `test_openapi_contract` (route and schema lists, one test renamed, redirects now count as success without a problem body — a relaxation for redirect routes), `test_role_sql` (table and function lists), `test_roles_and_migrations` (additions only) | **owner decision** (accept or reword) |
| AC-USR-06 | application role cannot change status; platform role has no access | “platform with a grant” | T10 (AC-PLT-07) |
| AC-SES-07 | own sessions only; platform role has no access | “platform with a grant” | T10 (AC-PLT-07) |
| AC-SES-10 | browser change revokes; country change audited when known | notice, production geo source | source undecided; proposed T11 (AC-ADM-07) |
| AC-MOB-04 | Keycloak refuses reuse | revocation `REFRESH_REUSE` | T11 (AC-AUD-10 ingestion) |
| AC-POL-06 | application path with factor | Keycloak's password form (F-3K) | **owner decision**, T09 scope |
| AC-POL-13 | rotation, UA binding, Keycloak reuse refusal | `REFRESH_REUSE`, country notice | T11 |

None is marked PASS, and no deviation is accepted on the owner's behalf. AC-POL-10 is **OPEN**, not bounded. AC-POL-06 moved from PASS to PARTIAL because of F-3K.

## 8. Acceptance matrix T01–T13

`PASS` is evidence, not acceptance. `PARTIAL` and `OPEN` are never treated as `BOUNDED`; only the owner can bound a criterion.

Summary: DEFERRED: 34; OPEN (P1): 1; PARTIAL: 8; PASS: 78; PASS with accepted deviation: 5; total 126.

| Criterion | Status | Implementation | Test(s) | Result (local run, same SHA) | Deviation / dependency |
|---|---|---|---|---|---|
| AC-KC-01 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s07_realm_import_resolves_env_secrets_and_service_account_is_least_privilege` | 1/1 pass (K) | CI identity job imports the test realm into a fresh container; a separate step imports DEV and PROD |
| AC-KC-02 | PASS | `tests/identity/realm_lint.py` | `test_realm_lint::test_linter_rejects_each_violation`<br>`test_realm_lint::test_committed_realms_comply_with_policy`<br>`test_realm_lint::test_every_second_factor_the_application_knows_is_proven_at_level_two` | 38/38 pass (M) | also fixes the exact authentication flows, the refused password grant, the level map and the `loa_map` mapper |
| AC-KC-03 | PASS | `identity/keycloak/realm-template.json` | `test_realm_lint::test_dev_and_prod_share_nothing_environment_specific` | 1/1 pass (M) | DEV/PROD import with flow and mapper assertions: CI step, no test-case id |
| AC-KC-04 | PASS | spike report | `test_keycloak_spike::test_s01_temporary_lockout_expires_with_short_test_window`<br>`test_keycloak_spike::test_s02_direct_recovery_url_is_denied_when_reset_is_disabled`<br>`test_keycloak_spike::test_s03_max_age_zero_requires_fresh_login`<br>`test_reconciliation_keycloak::test_s03_level_two_expires_after_its_configured_age`<br>`test_reconciliation_keycloak::test_s03_a_passkey_enrolled_earlier_is_the_second_level` | 5/5 pass (K) | S1 expiry and S3 age use shortened windows (committed 900 s / 600 s asserted); the T01/REC S3 WebAuthn finding is superseded: a passkey is proven at level two (registration stays off) |
| AC-KC-05 | PASS | `identity/keycloak/realm-template.json` | `test_tokens_keycloak::test_rotation_new_realm_key_is_picked_up_without_restart`<br>`test_keycloak_spike::test_kc05_key_rotation_new_key_published_and_old_kept` | 2/2 pass (K) | — |
| AC-KC-06 | PASS | `.github/workflows/ci.yml` | `test_identity_environment::test_test_image_is_pinned_by_digest_to_the_version_in_compose`<br>`test_identity_environment::test_disposable_compose_has_no_persistent_state_and_no_shared_services`<br>`test_ci_workflow::test_runners_images_and_tools_are_pinned` | 3/3 pass (M) | — |
| AC-TOK-01 | PASS | `app/auth/tokens.py` | `test_tokens::test_valid_token_is_accepted_and_exposes_only_identity_fields`<br>`test_tokens_keycloak::test_real_access_token_validates_and_matches_the_user`<br>`test_second_factor_time::test_only_a_well_formed_level_two_time_is_read` | 21/21 pass (M+K) | — |
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
| AC-AUD-05 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_catalog_and_validation::test_every_action_accepts_its_own_allowlisted_details`<br>`test_catalog_and_validation::test_unknown_action_and_unlisted_detail_keys_are_rejected`<br>`test_email_change_review::test_neither_audit_nor_log_holds_an_address_subject_or_provider_message` | 37/37 pass (M) | — |
| AC-AUD-06 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_identity_provider_event_ingestion_is_idempotent` | 1/1 pass (M) | long hashed dedup keys would be refused by 0008; T11 must use provider ids |
| AC-AUD-07 | PASS | 0003 | `test_audit_db::test_downgrade_removes_everything_and_upgrade_restores_it`<br>`test_roles_and_migrations::test_rec_migrations_downgrade_to_exactly_what_was_there_and_back`<br>`test_roles_and_migrations::test_the_review_migration_only_widens_the_guard_and_downgrades_exactly` | 4/4 pass (M) | — |
| AC-AUD-08 | PARTIAL | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_every_catalog_action_can_be_stored`<br>`test_web_flow::test_login_session_logout_and_the_old_cookie_is_dead`<br>`test_denied_attempts::test_a_refused_bearer_token_is_recorded_by_its_reason_only`<br>`test_denied_attempts::test_a_malformed_token_is_recorded_too`<br>`test_denied_attempts::test_a_refused_workspace_switch_is_recorded_without_the_requested_tenant`<br>`test_denied_attempts::test_using_a_workspace_after_the_membership_ended_is_recorded`<br>`test_email_change_review::test_a_retry_hands_the_change_back_to_the_worker_which_finishes_it` | 11/11 pass (M) | T01–T09 part complete (refused tokens and workspaces added). Missing: failed sign-ins at Keycloak (T11, AC-AUD-10), grant changes and use (T10, AC-PLT-10), administrative actions (T11, AC-ADM-01/04) |
| AC-AUD-09 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_audit_rolls_back_with_its_business_transaction`<br>`test_audit_db::test_independent_audit_survives_a_failed_request` | 2/2 pass (M) | — |
| AC-AUD-10 | DEFERRED | — | — | — | T11 |
| AC-AUD-11 | DEFERRED | — | — | — | T11 |
| AC-CTX-01 | PARTIAL | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py` | `test_context_bootstrap::test_new_fields_default_to_none_and_old_usage_is_unchanged` | 1/1 pass (M) | literal “F1 tests unchanged” cannot be met: 5 of 21 F1 test files changed (see §9). Owner decision; no later package changes this |
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
| AC-USR-06 | PARTIAL | `app/auth/users/`, 0004 | `test_users_db::test_application_role_cannot_change_status_but_can_edit_its_profile`<br>`test_users_db::test_nobody_can_delete_and_platform_has_no_access_until_its_grants_exist` | 2/2 pass (M) | today the platform role has no access at all. Missing “with a grant”: T10, proven there with AC-PLT-07 |
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
| AC-SES-07 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_people_cannot_see_or_revoke_each_others_sessions`<br>`test_sessions_db::test_privileges_per_role` | 2/2 pass (M) | today the platform role has no access at all. Missing “with a grant”: T10, proven there with AC-PLT-07 |
| AC-SES-08 | PASS with accepted deviation | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_the_database_keeps_immutable_columns_immutable_even_for_a_superuser` | 7/7 pass (M) | credential hash rotation (CP05) |
| AC-SES-09 | PASS | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_touch_is_throttled_extends_idle_and_never_passes_the_absolute_deadline` | 1/1 pass (M) | — |
| AC-SES-10 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_a_changed_browser_family_revokes_the_session_through_its_own_transaction`<br>`test_sessions_db::test_a_new_country_is_flagged_and_audited_but_does_not_revoke` | 2/2 pass (M) | browser change revokes; country change is audited when a country is given. Missing: the notice and a production geo source. No package owns the source decision; propose T11 (notices, AC-ADM-07). Mobile has no UA binding (accepted, CP07) |
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
| AC-WEB-10 | PASS | `app/api/v1/auth.py`, `app/auth/web/stepup.py` | `test_web_flow_keycloak::test_reauthentication_step_up_through_keycloak_rotates_the_credential`<br>`test_validators_and_helpers::test_loa2_needs_a_recorded_second_factor_step_up_within_the_window`<br>`test_account_step_up::test_a_step_up_answered_from_single_sign_on_is_refused`<br>`test_account_step_up::test_a_real_step_up_opens_the_window_from_the_factor_time`<br>`test_account_step_up::test_single_sign_on_does_not_extend_the_window`<br>`test_account_step_up::test_the_factor_counts_for_ten_minutes_whatever_the_password_age`<br>`test_second_factor_time::test_a_web_session_counts_level_two_from_the_factor_to_the_second` | 10/10 pass (M+K) | F-2 closed: the window counts from the proven factor |
| AC-WEB-11 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_every_answer_of_the_sign_in_routes_is_no_store_errors_included` | 1/1 pass (M) | — |
| AC-WEB-12 | PASS | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_sign_in_routes_have_their_own_ip_limit`<br>`test_web_flow::test_when_the_limiter_is_down_sign_in_fails_closed` | 2/2 pass (M) | — |
| AC-MOB-01 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_opening_a_session_creates_it_once_and_returns_it_afterwards`<br>`test_mobile_flow::test_a_valid_token_without_an_application_session_is_a_401` | 2/2 pass (M) | — |
| AC-MOB-02 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_tokens_that_are_not_mobile_access_tokens_are_refused`<br>`test_mobile_flow::test_another_persons_token_cannot_reach_my_session` | 7/7 pass (M) | — |
| AC-MOB-03 | PASS | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_mobile_flow::test_a_revoked_session_stays_revoked_although_the_token_is_still_valid` | 1/1 pass (M) | — |
| AC-MOB-04 | PARTIAL | `app/auth/mobile/`, `app/api/v1/sessions.py` | `test_keycloak_spike::test_s06_refresh_rotation_and_reuse_detection`<br>`test_reconciliation_keycloak::test_refresh_token_reuse_is_refused_by_keycloak_without_telling_the_application` | 2/2 pass (K) | Keycloak refuses reuse but tells nobody. Missing: revocation with reason `REFRESH_REUSE` from `REFRESH_TOKEN_ERROR` events: T11 (with AC-AUD-10) |
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
| AC-POL-05 | PASS with accepted deviation | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py`, `app/auth/security/{markers,recovery_worker}.py` | `test_security_keycloak::test_the_recovery_link_works_once`<br>`test_reconciliation_keycloak::test_f0_the_periodic_check_ends_old_sessions_after_a_reset_without_a_sign_in`<br>`test_reconciliation_keycloak::test_a_password_reset_and_the_sessions_that_existed_before_it`<br>`test_password_check::test_a_reset_ends_every_old_session_without_anybody_signing_in`<br>`test_password_check::test_checks_racing_each_other_give_one_record_and_one_notice`<br>`test_password_check::test_the_application_wires_the_check_into_its_worker`<br>`test_security_policies::test_a_sign_on_session_older_than_the_new_password_cannot_open_the_application`<br>`test_second_factor_keycloak::test_a_reset_ends_web_and_mobile_sessions_and_the_phone_cannot_come_back`<br>`test_second_factor_keycloak::test_a_forgotten_password_is_recovered_and_the_factor_stays` | 12/12 pass (M+K) | owner-authorized F-0 (a): sessions end within one 60 s worker cycle, not in the reset transaction; limits in §2 |
| AC-POL-06 | PARTIAL | `app/auth/security/{step_up,actions}.py`, `app/api/v1/{auth,me,sessions}.py` | `test_security_keycloak::test_password_change_through_keycloak_ends_other_sessions_and_rotates_this_one`<br>`test_reconciliation_keycloak::test_d37_end_to_end_with_real_mail_and_the_periodic_worker`<br>`test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2`<br>`test_account_step_up::test_with_a_second_factor_a_password_alone_is_refused`<br>`test_account_step_up::test_a_change_made_without_the_existing_factor_ends_every_session`<br>`test_second_factor_keycloak::test_the_application_asks_for_the_factor_before_every_account_action`<br>`test_second_factor_keycloak::test_a_password_change_of_a_person_with_a_factor_runs_through_it`<br>`test_second_factor_keycloak::test_open_finding_keycloak_changes_a_password_without_the_second_factor` | 36/36 pass (M+K) | application path enforced. **Open F-3K (P2):** Keycloak’s own password form does not require the second factor (T09 scope, needs an owner decision, §2) |
| AC-POL-07 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s10_password_policy_enforced_including_blacklist` | 1/1 pass (K) | production blacklist is a live prerequisite |
| AC-POL-08 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s03_step_up_loa2_requires_otp_and_loa1_does_not`<br>`test_security_keycloak::test_a_second_factor_is_enrolled_listed_required_for_removal_and_removed` | 2/2 pass (K) | — |
| AC-POL-09 | DEFERRED | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | — | — | T10; must also require an enrolled factor before a grant takes effect (a person without one may set it up with the password) |
| AC-POL-10 | **OPEN (P1)** | `app/auth/security/step_up.py`, `app/auth/web/stepup.py`, `identity/keycloak/realm-template.json` | `test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2`<br>`test_reconciliation_keycloak::test_keycloak_needs_level_two_to_remove_a_second_factor`<br>`test_reconciliation_keycloak::test_f1_nobody_can_register_a_passkey`<br>`test_reconciliation_keycloak::test_recovery_codes_alone_protect_level_two`<br>`test_second_factor_keycloak::test_with_a_second_factor_the_password_alone_never_reaches_level_two`<br>`test_second_factor_keycloak::test_every_registered_factor_reaches_level_two_and_records_when`<br>`test_second_factor_keycloak::test_the_password_alone_cannot_add_a_factor`<br>`test_second_factor_keycloak::test_the_password_alone_cannot_remove_a_factor`<br>`test_second_factor_keycloak::test_no_client_may_exchange_a_password_for_a_token`<br>`test_second_factor_keycloak::test_a_recovery_code_works_once`<br>`test_second_factor_keycloak::test_neither_single_sign_on_nor_a_refresh_nor_the_password_moves_the_factor_time`<br>`test_second_factor_keycloak::test_open_finding_unfinished_new_recovery_codes_can_be_taken_with_the_password`<br>`test_second_factor_keycloak::test_open_finding_keycloak_changes_a_password_without_the_second_factor`<br>`test_account_step_up::test_with_a_second_factor_proven_the_action_is_open`<br>`test_account_step_up::test_without_a_second_factor_a_fresh_password_is_enough`<br>`test_account_step_up::test_a_refreshed_bearer_token_does_not_renew_the_step_up` | 87/87 pass (M+K) | **Open F-1R-B (P1):** abandoned recovery-code regeneration is served after the password alone; **F-3K (P2)**. Two tests named `test_open_finding_*` pass by showing the gap: they are not proof of protection. 5-minute grant actions: T10 |
| AC-POL-11 | PASS | `app/auth/security/notify.py` | `test_security_units::test_every_notice_is_spanish_short_and_carries_nothing_but_the_kind_and_the_time`<br>`test_security_units::test_production_default_sends_nothing_and_smtp_needs_a_host` | 7/7 pass (M) | — |
| AC-POL-12 | PASS with accepted deviation | `app/api/v1/auth.py`, `app/auth/web/` | `test_web_flow::test_a_logout_token_is_accepted_once`<br>`test_web_flow::test_a_replayed_callback_is_refused` | 2/2 pass (M) | no Idempotency-Key (CP07, CP08) |
| AC-POL-13 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_a_changed_browser_family_revokes_the_session_through_its_own_transaction`<br>`test_sessions_db::test_rotation_invalidates_the_old_credential_at_once`<br>`test_reconciliation_keycloak::test_refresh_token_reuse_is_refused_by_keycloak_without_telling_the_application` | 3/3 pass (M+K) | rotation and web UA binding proven; refresh reuse proven at Keycloak only. Missing: `REFRESH_REUSE` (T11, with AC-MOB-04); country notice (see AC-SES-10) |
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
| AC-PLT-12 | DEFERRED | — | — | — | T10; migration number is now 0010 or later |
| AC-ADM-01 | DEFERRED | — | — | — | T11 |
| AC-ADM-02 | DEFERRED | — | — | — | T11 |
| AC-ADM-03 | DEFERRED | — | — | — | T11 |
| AC-ADM-04 | DEFERRED | — | — | — | T11 |
| AC-ADM-05 | DEFERRED | — | — | — | T11 |
| AC-ADM-06 | DEFERRED | — | — | — | T11 |
| AC-ADM-07 | DEFERRED | — | — | — | T11 |
| AC-ADM-08 | DEFERRED | — | — | — | T11 |
| AC-ADM-09 | DEFERRED | — | — | — | T11 |
| AC-ADM-10 | DEFERRED | — | — | — | T11; migration number is now 0010 or later |
| AC-API-01 | DEFERRED | — | — | — | T12 |
| AC-API-02 | DEFERRED | — | — | — | T12 |
| AC-API-03 | DEFERRED | — | — | — | T12 |
| AC-API-04 | DEFERRED | — | — | — | T12 |
| AC-API-05 | DEFERRED | — | — | — | T12; current drift, validator and client checks pass in CI |
| AC-API-06 | DEFERRED | — | — | — | T12 |
| AC-API-07 | DEFERRED | — | — | — | T12 |
| AC-API-08 | DEFERRED | — | — | — | T12 |

## 9. Changed tests

No test is skipped or deselected. Two Keycloak tests that **asserted the vulnerability** were replaced by tests asserting the protection: `test_s03_webauthn_enrols_but_the_realm_does_not_use_it_for_level_two` → `test_s03_a_passkey_enrolled_earlier_is_the_second_level`; `test_recovery_codes_alone_do_not_protect_level_two` → `test_recovery_codes_alone_protect_level_two`.

Existing tests adjusted for intended behaviour:
- MFA step-up now carries `prompt=login`: expectations in `test_web_flow` and `test_validators_and_helpers`; the Keycloak removal test answers the password prompt.
- `test_account_lookup_and_delivery_are_deferred_after_generic_response`: before the answer the caller's own credentials are now read (F-3); it asserts exactly that call and still no look-up of the new address.
- The fake identity provider adds `loa_map` to level-two tokens, as the realm does; the mobile fixture configures the fake admin client (“sign out everywhere” needs it).
- `test_idempotency` head revision 0009; audit catalogue list has the new action. The WebAuthn helper can now sign in.

## 10. Open production blockers

- **F-1R-B (P1)** and F-3K (P2), §2.
- Persistent database migration state unverified (F1 R05, §6).
- Existing realms need the manual steps of [identity/README](../../identity/README.md); passkey and codes-only accounts checked.
- D37: O15 mail provider; F-4 needs T10 authority and T11 interface.
- R11 (provisioning script vs `harden.sql`, Keycloak database), R12/O20 (readiness), real `TRUSTED_PROXY_CIDRS`, O06–O17, D13 (same-origin route), D43 (Keycloak hardening), production password blacklist, AT-20 legal basis and retention (**D42 OPEN**).
- Dart analysis deferred (R10). Local CI limits LCI-04/05.

## 11. Remaining T10–T13 obligations

- **T10:** platform grants and mandatory level two for grant holders with an already enrolled factor (AC-PLT, AC-POL-09, AC-AUTHZ-03, platform parts of AC-USR-06 and AC-SES-07); five-minute window for grant changes; the F-4 authority; migrations from 0010.
- **T11:** administration, durable outbox and Celery, Keycloak events (AC-AUD-08/10, AC-MOB-04, changes made on Keycloak's pages), ending Keycloak sessions, the F-4 interface, country notice if a source is decided.
- **T12:** frozen API contract (AC-API).
- **T13:** final acceptance and traceability test.

## 12. CP09 proposal

**Do not accept CP09 yet.** Decide F-1R-B and F-3K (§2; recommended: A). After that change, its tests and a green CI run, propose “F2-CP09 — READY FOR OWNER ACCEPTANCE” with: AC-POL-10 and AC-POL-06 re-evaluated, your decision on the remaining PARTIAL criteria (§7, each stays assigned to T10/T11, AC-CTX-01 to you), and the production blockers of §10 acknowledged as not closed by CP09. CP09 is not accepted by this report and T10 is not started.
