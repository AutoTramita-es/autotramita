# F2-CP09 — reconciliation report (F2-T09-REC)

Date: 2026-11-25 (revised after the CP09 independent security review, F2-CP09-REC, D46). **Status: F2-CP09-REC — corrections implemented ([§1.0](#10-cp09-independent-review-corrections-f2-cp09-rec)); the local FULL CI and the GitHub run of the final SHA are reported to the owner** (a commit cannot record the run of itself). Keycloak runs 26.8.2 in development, tests and CI (owner authorization, D45), with the security provider 1.1.1. The image scan went from **9 CRITICAL / 93 HIGH to 0 CRITICAL / 6 HIGH** (same databases); the six HIGH findings are accepted by the owner for a limited time (commit `cfbc8f7`; [§2.0](#20-keycloak-security-upgrade-2026-11-25)), and the gate passes. No P0 or P1 finding of the AutoTramita code is open. **CP09 is not accepted**; T10 is not started; nothing was deployed, no existing realm or persistent database was touched. D42 stays OPEN (AT-20), R10 stays deferred, O15 blocks production mail.

> **Owner acceptance (2026-11-25, D47):** F2-CP09 is **CLOSED / ACCEPTED** and F2-T09 **COMPLETED / ACCEPTED** on the verified SHA `b24da2a` (GitHub run [45673597875](https://github.com/AutoTramita-es/autotramita/actions/runs/45673597875), five jobs successful; local FULL CI `20261125-181014-774b23`; 1,706 distinct tests, 1,889 executions, 0 failures, errors or skipped; local and GitHub equivalent; KC-SP-01 to KC-SP-20 PASS). The owner accepted the independent verification, AC-POL-10, AC-CTX-01, the documented deviations and the evidence limitations. IR-05 and IR-06 stay deferred to INFRA-CI-02, which **must** include severity binding of vulnerability acceptances; until then the severity is reassessed at every renewal and zero CRITICAL findings are confirmed manually before production. IR-07 and every production blocker of §10 stay mandatory. Only F2-T10 is authorized. The status lines below are the state before this acceptance.

## 1.0 CP09 independent review corrections (F2-CP09-REC)

The independent security review (2026-11-25, on `cfbc8f7`; report kept outside the repository: `F2-CP09-INDEPENDENT-SECURITY-REVIEW.md`) found no P0 or P1. GitHub run [45648436800](https://github.com/AutoTramita-es/autotramita/actions/runs/45648436800) on `cfbc8f7` failed in two test jobs (IR-01, IR-02); its image scan passed with the owner's acceptances. Owner decisions: D46 (decision register; recorded in `0035e8c` before the code).

| Finding | Severity | Decision (D46) | Result |
|---|---|---|---|
| IR-01 clock-dependent Keycloak test of new recovery codes from single sign-on | P2 | deterministic test; a recovery code may be offered at the re-authentication, but never authorizes new codes or a credential change alone | **CLOSED** (`4792291`): Keycloak counts `max_auth_age` 0 in whole seconds. Within the sign-in's second the request is a step-up (only the permanent factor is offered: `test_new_recovery_codes_from_single_sign_on_need_the_permanent_factor_again`). Later it is a forced re-authentication (password again; one-time code and recovery code offered; a recovery code signs in but no codes are issued until the one-time code is proven; the one-time code alone is enough: `test_new_recovery_codes_after_the_fresh_sign_in_need_the_permanent_factor`, 4 cases). Each path is reached on purpose and also issues the new codes. Targeted run 5 times in a row: 6/6 each. Provider and realm unchanged. The earlier fix `d3aa3a1` answered the password question but kept an assertion that holds only within the second |
| IR-02 `test_the_committed_acceptances_accept_nothing` contradicted the owner's acceptances | P2 | test the authorized acceptances | **CLOSED** (`4792291`): replaced by four tests (9 cases): exactly the six authorized pairs with their expiry dates, owner reference and review, no duplicates; every entry rests on the review (HIGH only, no later than its recommended and proposed expiry); with the committed file the gate passes the six findings until they expire and refuses expired ones (fixed reference times 2026-11-25, 2026-12-31, 2027-01-01, 2027-02-23); every other finding is blocked. `scan_gate.py` and the acceptances unchanged; the earlier negative tests unchanged (30 tests in the file) |
| IR-03 stale documentation | P3 | update | **CLOSED**: this report, the acceptance criteria header, the provider and identity READMEs, the decision register |
| IR-04 severity of CVE-2026-91403 | P3 | document | **CLOSED**: Red Hat rates it **Critical** (CVSS 6.8), Trivy reports HIGH; the gate counts Trivy's severity. Recorded in §2.0 and in `vulnerability-review-26.8.2.json`; the mitigation analysis, the scanner data and the acceptance are unchanged |
| IR-05 scan-gate hardening (match also the installed version, exact image binding, upload the summary) | P3 | deferred | **DEFERRED to INFRA-CI-02** |
| IR-06 Local CI broker: `docker build` without `--network none` | P3 | deferred, no extension of network access | **DEFERRED to INFRA-CI-02** |
| IR-07 production cache stack and database failover not demonstrated | P3 / production | mandatory production blocker | **OPEN — production blocker** (§10) |

## 1. Revisions and evidence

**Superseded for the final state by §1.0.** The table below records the Keycloak Security Upgrade; its CI on `d9b9aba` stays valid evidence for that content.

| Item | Value |
|---|---|
| Start of the Keycloak Security Upgrade | `ad693c50cf7d7e1c860520017d663d69ad3c606b` |
| Owner decisions recorded before the code | `77caf18` (D45, ADR-008, execution order) |
| **Final implementation SHA** | `d9b9aba70f123dc5b805c01fe8c426da16a2c998` (code `abe7916`, documentation `d9b9aba`); this table was filled in by the results commit that follows it |
| **Local FULL CI on that SHA** | run `20261125-152202-af5d5c`, clean tree (`c4614eafc4e71c5bc76f9d784fede4e7fba33705`), 401.2 s: **every test job PASS**; `image-scan` **FAIL** at its gate (6 HIGH, §2.0), so the run is FAIL |
| **GitHub CI on that SHA** | [45645703628](https://github.com/AutoTramita-es/autotramita/actions/runs/45645703628): every test job **success**, `image-scan` **failure** at its gate (the same 6 HIGH, the same databases `1581858e…` / `538098aa…`), 444 s; `compare-github.sh`: **EQUIVALENT** (same steps and results, 1,437 + 257 tests, DEV and PROD realm import, 545 commits scanned) |
| Main tests | **1,437 passed**, 0 failed, 0 errors, 0 skipped (one more than before: the new linter case) |
| Keycloak tests | **257 passed** (one node, two nodes on one database, the application), 0 failed, 0 errors, 0 skipped. **Total 1,694** distinct tests; all invocations **1,877** |
| Keycloak | **26.8.2**, `quay.io/keycloak/keycloak:26.8.2@sha256:7e66a96e4739239070aeaf72e4c5decf0f7f682cfc725b9f7ea2b336eaba38b3` (index; amd64 `sha256:75b5c435…`), RHEL 9.9, OpenJDK 21.0.13.1 |
| Provider | **1.1.1**, jar SHA-256 `d61ac28e362008f530b3ab6b5642fbbb892eda5f0137669d5be96b935b7c574a` (built twice per build, identical; decision table 2,048 cases) |
| Image scan | Trivy 0.76.2 (pinned by digest); vulnerability DB schema 2 updated 2026-11-25T13:07Z (`1581858e…`), Java DB schema 1 updated 2026-11-25T00:58Z (`538098aa…`), the same databases as the 26.4.7 scan; **0 CRITICAL, 6 HIGH**, none accepted on `d9b9aba`; accepted by the owner in `cfbc8f7` (gate PASS in run 45648436800) |
| Targeted runs during the work | Local CI `keycloak` profile: first run 178/257 (the tests' software passkey could not read 26.8.2's page, §2.0), after the helper fix **257/257**; `security` profile: gate FAIL on the 6 HIGH |

Previous revision (Final Completion Order, provider 1.1.0 on 26.4.7): final SHA `8e49b91`, local FULL `20261125-140644-a99236`, GitHub run [45632069412](https://github.com/AutoTramita-es/autotramita/actions/runs/45632069412), 1,436 main and 257 Keycloak tests; see Git history (`ad693c5`).

The matrix in [§8](#8-acceptance-matrix-t01t13) is checked against the JUnit files of the final local run: every named test exists and passed. `M` = main job, `K` = Keycloak job.

## 2. Keycloak security provider

### 2.0 Keycloak Security Upgrade (2026-11-25)

Owner authorization D45: Keycloak 26.4.7 → **26.8.2** directly, one-time exception to the 14-day rule for development, tests and CI only. Upgrade details, rehearsal and production steps: [identity/keycloak/UPGRADE-26.8.2.md](../../identity/keycloak/UPGRADE-26.8.2.md); SPI review per extension point: [provider README](../../identity/keycloak/provider/README.md#extension-points-keycloak-2682).

**Checks before the change.**

| Check | Result |
|---|---|
| Official availability | GitHub release 26.8.2 ("Latest"), tag commit `e514445f`; image on `quay.io/keycloak/keycloak` (the location keycloak.org names) |
| Release date | **Deviation from the CP09 report:** the GitHub release is dated **2026-11-05**, not 19 Nov. The image tag was published three times (2026-11-09, 11-12, **11-19**, base image rebuilds); the pinned digest is the image of 19 Nov, so the image is younger than 14 days and the owner's exception is needed for it. 26.8.1 is not used (owner) |
| Release notes and advisories | 26.8.2 lists 40+ security fixes (among them account takeover via stale SSO notes, stored XSS on the login page, a session takeover through logout, SAML parser denial of service, token-exchange lifetimes); 26.5–26.8.1 hold the fixes of the 90 findings of 26.4.7 |
| Upgrade guide 26.5.0–26.8.2 (`docs/documentation/upgrading`, tag 26.8.2) | relevant: **Admin REST API audience check** (26.8.2, breaks a service account without `kc-admin-api`), required actions one-time by default, transactions may not be restarted by extensions (the provider never starts one), login failures in the database, email no longer verified by other flows, refresh-token expiry capped by session idle, SCIM API enabled as a feature but off per realm (`scimApiEnabled` false; not set by the realms), secondary-authentication lockout (`maxSecondaryAuthFailures` default 0, not set: AC-POL-01 unchanged), `session_state`/`sid` no longer UUIDs (now 24 characters of base64url, `SecretGenerator.generateBase64SecureId(18)`, inside the application's `kc_session_id` check `^[A-Za-z0-9._:-]{1,128}$` of 0005; the application reads them as strings; real sign-in and back-channel logout tests pass) |
| PostgreSQL | 13 is end of life, 16 supported; the database user should be able to read `pg_class`/`pg_namespace` for faster migrations (warning only); driver 42.7.13 |
| Realm configurations | DEV, PROD and TEST realm files import into fresh 26.8.2 instances with every flow, action, mapper and profile attribute asserted (CI step); one realm change needed (`kc-admin-api` on `at-admin-svc`) |
| Java and build | runtime OpenJDK 21.0.13.1 (was 21.0.9); the provider still compiles with `--release 21` in the unchanged pinned `eclipse-temurin:21-jdk` image; two deprecations (`-Werror`) corrected |
| Internal SPIs of the provider | compared class by class with the 26.4.7 sources; no change weakens a guarantee; provider 1.1.1 (two source corrections, policy unchanged) |
| Authenticity and digest | official repository; SLSA provenance names the GitHub repository and the tag commit; Keycloak jars byte-identical (SHA-1) to Maven Central 26.8.2; no cosign signature exists for Keycloak images (recorded, not a blocker: digest pin plus provenance plus Maven Central comparison) |
| Reported scan results | confirmed: 0 CRITICAL / 6 HIGH with the same databases as the 26.4.7 scan |

**Changes.** Pins in `Dockerfile`, `ci.yml` (three places, job name), `identity/docker-compose.keycloak-test.yml` and the new prepared `identity/docker-compose.keycloak-production.yml` (not applied; the live `docker-compose.yml` keeps naming 26.4.7, and a test allows that only while the prepared file states it replaces that version); provider 1.1.1 (`Time.currentTimeSeconds()`, `@SuppressWarnings("removal")` on `getEntities()`, version, manifest); realm template: `kc-admin-api` default scope on `at-admin-svc` (linter rule and negative case); tests' software passkey reads 26.8.2's page; `scripts/identity/upgrade_rehearsal.py` (disposable containers only). No other component was upgraded (JDK build image, PostgreSQL, Redis, Trivy unchanged).

**Migration (disposable containers only).** Clean install and realm import: CI. Upgrade of a 26.4.7 database (realm of `ad693c5`, accounts with each factor, one session): migrated in 16.8 s; users, credentials (stored hashes), obligations, guard rows identical; every factor signs in; the session from before continues and its refresh token works; the provider decides on the migrated database; `at-admin-svc` 401 until the scope is added, then 200; restore of the backup under 26.4.7 gives back the exact earlier state; 26.4.7 on the migrated database **starts with a warning only**, so the procedure forbids it (no supported downgrade). Result file: [`upgrade-rehearsal-26.8.2.json`](../../identity/keycloak/upgrade-rehearsal-26.8.2.json).

**KC-SP-12 after the upgrade (result: FAIL, owner decision required).** Same scanner, same gate, same databases (`1581858e…`, `538098aa…`):

| | 26.4.7 | 26.8.2 |
|---|---|---|
| CRITICAL | 9 | **0** |
| HIGH | 93 | **6** |
| distinct CRITICAL/HIGH | 90 | 6 (all carried over, none new) |

| CVE | Component | Severity, CVSS | Applicability | Fix | Recommendation | Recheck |
|---|---|---|---|---|---|---|
| CVE-2026-102554 | Guava 33.6.0-jre (Keycloak lib) | HIGH; Red Hat 7.5, GHSA 5.9 | not reachable: no Java deserialization of untrusted input; upstream `status/not-vulnerable` (keycloak#54855) | Guava 33.7.2, expected in a 26.8.x patch (`backport/26.8`) | time-limited acceptance to 2026-12-31, then the patch release | every 26.8.x release |
| CVE-2026-91403 | java-21-openjdk-headless 21.0.13.1 | HIGH (Trivy); Red Hat **Critical**, CVSS 6.8 (IR-04: the gate counts Trivy's severity; the mitigation decides) | mitigated: Red Hat "will not fix" in the JDK, the fix is ca-certificates (CVE-2026-114406, RHSA-2026:88459), whose fixed version is in the image and is the JDK's trust store | none for the JDK by design | time-limited acceptance (vendor mitigation installed) to 2027-02-22 | every image update |
| CVE-2026-119373 | sqlite-libs 3.34.1 (FTS5) | HIGH; 7.8 local | not reachable: the Keycloak JVM loads neither libsqlite3 nor NSS softokn (`/proc/1/maps`), nothing takes SQL or FTS5 tables | none for RHEL 9 | time-limited acceptance to 2027-02-22 | monthly |
| CVE-2026-119374 | sqlite-libs 3.34.1 (FTS5 secure delete) | HIGH; 7.8 local | Red Hat: RHEL 9 sqlite **not affected**; also not reachable | not needed per vendor | time-limited acceptance (false positive) to 2027-02-22 | when the database follows the vendor |
| CVE-2026-119379 | sqlite-libs 3.34.1 (session extension) | HIGH; 7.8 local | not reachable (no changesets applied anywhere) | none for RHEL 9 | time-limited acceptance to 2027-02-22 | monthly |
| CVE-2026-119586 | sqlite-libs 3.34.1 (`sqlite3` shell `.recover`) | HIGH; 7.8 local | not applicable: the shell is not installed | none for RHEL 9 | time-limited acceptance to 2027-02-22 | monthly |

Per finding (preconditions, protections, sources, removal): [`vulnerability-review-26.8.2.json`](../../identity/keycloak/vulnerability-review-26.8.2.json), which also holds the proposed acceptance entries. **Nothing was accepted:** `vulnerability-acceptances.json` is empty, `scan_gate.py` is unchanged. No supported fix exists inside 26.8.2: removing or replacing the Guava jar or OS packages of the official image is not authorized (and sqlite-libs belongs to the base image's rpm database and NSS).

### 2.1 Final Completion Order (2026-11-25)

**KC-SP-12 — image scan (result on 26.4.7: FAIL, blocker; superseded by the upgrade, [§2.0](#20-keycloak-security-upgrade-2026-11-25)).** Job `image-scan` in `ci.yml` (and Local CI): build the image; the pinned scanner downloads its two databases (the only container with a network: the job's egress network in Local CI); `docker save`; scan with `--network none` (OS and Java, JSON); `scripts/identity/scan_gate.py` fails on a database older than 48 h (Java 7 days) or missing, a report of another image or scanner version or without OS and Java coverage, and every CRITICAL or HIGH without a time-limited owner acceptance (`identity/keycloak/vulnerability-acceptances.json`, empty; 22 tests in `tests/identity/test_scan_gate.py`, the false-PASS cases above all). No automatic exception exists. Result: 90 distinct CRITICAL/HIGH findings, reviewed in [`vulnerability-review-26.4.7.json`](../../identity/keycloak/vulnerability-review-26.4.7.json):

| Group | Findings | Applicability | Remedy |
|---|---|---|---|
| Keycloak (`keycloak-services`, `-server-spi-private`, `-saml-core`; one CRITICAL CVE-2026-18963) | 19 | applicable: the internet-facing sign-in | Keycloak upgrade |
| JDK (`java-21-openjdk-headless`; one CRITICAL) | 14 | applicable: the runtime | Keycloak upgrade; CVE-2026-91403 will not be fixed by Red Hat |
| HTTP stack (Netty, Quarkus Vert.x HTTP; one CRITICAL) | 23 | applicable | Keycloak upgrade |
| JSON (Jackson) | 8 | applicable | Keycloak upgrade |
| Cryptography (Bouncy Castle; two CRITICAL) | 4 | applicable | Keycloak upgrade |
| Templates (FreeMarker, CRITICAL) | 1 | applicable: every login page | Keycloak upgrade |
| JDBC (PostgreSQL applicable; SQL Server not loaded) | 3 | 2 applicable, 1 not | Keycloak upgrade |
| Other libraries (HTML sanitizer, Guava, Micrometer) | 3 | likely / conditional | Keycloak upgrade (Guava fix not yet in 26.8.2) |
| OS packages (ca-certificates CRITICAL; pcre2, sqlite, libcap, libacl) | 15 | ca-certificates applicable, others limited | Keycloak upgrade (newer UBI); sqlite has no fix |

Same database, published releases: **26.8.2** (19 Nov 2026) 0 CRITICAL / 6 HIGH (JDK will-not-fix, 4 sqlite without fix, Guava); **26.8.1** (31 Oct 2026) 1 / 10; **26.7.5** 2 / 18; **26.4.7** 9 / 93. The 26.4 patch releases named by some advisories are not published as community images. Upgraded on 2026-11-25 after the owner's authorization (§2.0); the counts of 26.8.2 were confirmed.

**Recovery-only accounts (closed).** Provider 1.1.0: a recovery code never authorizes a permanent factor, also not for an account holding codes only (`controlled_recovery_required`); the realm refuses such an account before a code is asked (`browser-deny-codes-only`, `browser-loa-1-legacy-enrol` removed), so no code is spent and nothing is deleted. Codes still never authorize new codes, a password change or the switch-off. K `test_a_codes_only_account_waits_for_the_controlled_recovery` (marked and unmarked, every client and request, credential untouched), `test_an_application_request_cannot_move_a_codes_only_account_either`, `test_recovery_codes_alone_protect_level_two`, the codes-only rows of the option-A tests; first factor of people without MFA: `test_the_first_permanent_factor_makes_the_obligation_permanent`, `test_without_a_second_factor_level_two_means_setting_one_up`. `PolicyCheck` has the invariant "no permanent factor after a recovery code".

**Broker review (Local CI).** Found and corrected:
1. The build context was compared after resolving both sides, so `identity/keycloak` as a link to elsewhere passed. It must now be reached without any link.
2. The Dockerfile was not checked. A `# syntax=` directive would pull an arbitrary frontend image, and `ADD <url>`, `COPY --from=<image>`, `RUN --network=host`, `--security=insecure` and ssh, secret or cache mounts would reach past the sandbox. All are refused now; FROM may only name the two build arguments, and ARG defaults must be pinned images of the workflow.
3. Builds shared the host's build cache. They now run with `--no-cache`.
4. Built images of finished runs were not removed by `cleanup.sh`. They are now.

New operations, each as narrow as possible: `docker save` of the built image into the workspace (handed to uid 1001, read only), the scanner's download (exact arguments, one cache mount, egress network only for it), `--network none`. Command injection: none possible (argument lists, no shell). 9 new negative self-tests (22 in all), including the repository's own Dockerfile passing. Not changed: host firewall, Docker daemon, networks, branch protection.

**Focused security check of the provider and the last corrections.**

| Topic | Result |
|---|---|
| F-1R-C, F-3K, held recovery-code sign-in | protection tests pass (one and two nodes) |
| Recovery-only accounts | closed (above) |
| Automatic `at_mfa_required`, controlled switch-off, `at_mfa_mandatory` | tests pass |
| Concurrency and several instances | tests pass |
| Freshness of the state | credentials always fresh; attribute limit documented |
| Transactions and rollback | one transaction per change; a refusal writes nothing |
| Admin API | outside the guard (trust boundary). New note: an administrator removing the last permanent factor while a sign-in waits at the factor question lets that sign-in finish with a recovery code (still two factors); documented |
| Without the provider | nobody signs in (CI step) |
| Database unavailable (exploration on two nodes) | stopped database: the form answers 500, nothing written; paused database: the request waits and the decision is taken when the database returns |
| Internal SPIs | unchanged risk, upgrade procedure mandatory |
| Earlier findings | all regression tests pass |

No new P0 or P1 finding.

Design, invariants, guarantees, upgrade, rollback and limits: [provider README](../../identity/keycloak/provider/README.md). Summary of what the analysis of the exact version (sources of 26.4.7 from Maven Central; the image's jars are byte-identical to those artifacts) established:

| Question | Finding on 26.4.7 (rechecked on 26.8.2: unchanged, [§2.0](#20-keycloak-security-upgrade-2026-11-25)) |
|---|---|
| Extension points | required actions, authenticators, JPA entity providers, theme resources. Keycloak itself classifies these SPIs as **internal** (start-up warning, no compatibility promise): upgrades need the mandatory regression suite |
| Replacing a built-in action | a custom factory with the same ID wins (`ProviderManager.compareFactories`); it must extend the built-in class, because three authenticators cast to it (found when the forced set-up failed; fixed) |
| Life cycle of a required action | the form is shown in `requiredActionChallenge`, the change happens in `processAction` when it is submitted (`LoginActionsService.requiredActionPOST`), inside the request's database transaction; `FAILURE` ends with `access_denied` to the client |
| Transaction boundary | the credential write, the obligation and the lock row are in one JPA transaction; commit or rollback together |
| Authentication sessions | survive reloads indefinitely in practice; a sign-out, disabling, new password or `notBefore` does not end a form already shown |
| Proof of a permanent factor | Keycloak's note of the credential types verified in this sign-in (`AuthenticatorUtil.getAuthnCredentials`) plus the provider's own start time; `acr` and single sign-on are not used |
| Concurrency, several instances | a pessimistic row lock in Keycloak's database (supported custom-entity SPI) serialises a person's guarded changes across instances; no in-memory lock |
| User cache | evicted under the lock and the account re-read from the database; credentials are read by query each time |
| Paths that change credentials | the four set-up actions, the password action, the e-mail action token (password only), the account console (only through those actions; removal off), the admin REST API (trusted, outside the guard) |

### Acceptance of the provider (KC-SP)

| ID | Status | Evidence (K = Keycloak job, M = main job) |
|---|---|---|
| KC-SP-01 SPI feasible | **PASS** (26.8.2) | analysis above and the review per extension point of 26.8.2 ([provider README](../../identity/keycloak/provider/README.md#extension-points-keycloak-2682)); provider 1.1.1 loaded and replacing every action: K `test_the_provider_replaces_every_credential_action_and_guards_the_sign_in`; CI import step asserts it for DEV and PROD |
| KC-SP-02 F-1R-C closed | **PASS** | K `test_a_set_up_page_opened_before_the_first_factor_is_refused_after_it` (was `test_open_finding_…_still_adds_one`), `test_a_held_form_is_refused_and_the_refusal_is_recorded` |
| KC-SP-03 rest of F-3K closed | **PASS** | K `test_a_password_form_opened_before_the_first_factor_is_refused_after_it` (was `test_open_finding_…_still_changes_it`), `test_a_password_change_needs_the_permanent_factor_not_a_code` |
| KC-SP-04 held recovery-code sign-in closed | **PASS** | K `test_a_sign_in_held_open_with_a_code_gets_no_new_codes_after_the_last_one` (was `test_known_gap_…`), `test_a_link_sent_past_the_application_runs_no_set_up_either` |
| KC-SP-05 automatic obligation | **PASS** | K `test_the_first_permanent_factor_makes_the_obligation_permanent` (one-time code and passkey), `test_opening_and_abandoning_a_set_up_never_sets_the_obligation`, two-node tests assert it |
| KC-SP-06 controlled switch-off | **PASS** | K `test_a_person_switches_the_second_factor_off_with_the_factor_and_a_confirmation`, `test_a_recovery_code_cannot_switch_the_second_factor_off`, `test_the_switch_off_is_refused_at_the_provider_itself` (no confirmation, mandatory, password only); M `test_mfa_disable.py` (11) |
| KC-SP-07 no automatic downgrade | **PASS** | `PolicyCheck` invariants (2,048 cases, every build); K `test_an_obliged_account_without_a_factor_cannot_set_one_up`, `test_the_last_code_of_a_codes_only_account_leaves_it_closed`, `test_without_the_permanent_factor_the_last_code_signs_nobody_in` |
| KC-SP-08 concurrency | **PASS** | one node: `test_two_first_activations_at_once_leave_exactly_one_factor` (3 rounds); two nodes on one database with local caches: `test_a_form_held_on_one_node_is_refused_after_the_factor_was_set_up_on_the_other`, `test_first_activations_on_two_nodes_at_once_leave_exactly_one_factor` (first change and lock wait, 3 rounds each), `test_new_recovery_codes_on_two_nodes_at_once_leave_one_set`, `test_a_password_form_and_a_first_activation_on_two_nodes_end_in_a_serial_state`; M `test_two_removals_at_once_cannot_both_take_a_permanent_factor` |
| KC-SP-09 Keycloak paths | **PASS** | web, phone and account console in `test_the_password_alone_cannot_add_a_factor` (now including the password action), `test_the_password_alone_cannot_remove_a_factor`, `test_nobody_removes_a_credential_at_the_provider`; e-mail links: `test_a_recovery_link_runs_no_pending_set_up`, `test_a_link_sent_past_the_application_runs_no_set_up_either` |
| KC-SP-10 fail closed | **PASS** | CI step "Without the security provider the realm signs nobody in"; refusals end with `access_denied` and roll back; the loser of a concurrent first change rolls back |
| KC-SP-11 reproducible image | **PASS** | two builds per build compared byte for byte; same jar hash on every machine (1.1.1: `d61ac28e…`); static tests keep the pinned references equal (Dockerfile, CI, developer compose and the prepared production file; the live compose may only name the version the prepared file replaces) |
| KC-SP-12 Java dependencies and image | **PASS** (owner acceptance) | Trivy gate on 26.8.2: **0 CRITICAL / 6 HIGH** (was 9 / 93 on 26.4.7, same databases), each analysed (§2.0, `vulnerability-review-26.8.2.json`) and accepted by the owner for a limited time (`cfbc8f7`; Guava to 2026-12-31, the others to 2027-02-22); the independent review verified the analysis against the vendor sources and the image; gate PASS in run 45648436800; no automatic exception. Still holds: no third-party Java dependency of the provider (build classpath = the pinned image's jars, no download; jar entries allow-listed; imports restricted by a test); runtime = pinned upstream + one 0444 jar, non-root (test) |
| KC-SP-13 upgrade and rollback | **PASS** (documentation and rehearsal) | the upgrade to 26.8.2 followed the provider's procedure; [UPGRADE-26.8.2.md](../../identity/keycloak/UPGRADE-26.8.2.md): production steps, backup, rollback by restore only; rehearsal on disposable containers (migration, data kept, provider works, restore works, downgrade starts with a warning only, so it is forbidden); rollback that never restores unguarded actions while MFA accounts exist |
| KC-SP-14 earlier regressions | **PASS** (final run: §1.0, owner report) | every F-0, F-1, F-1R, F-1R-B, F-1R-C, F-2, F-3, F-3K, F-4, recovery-only and R01–R07 test passed on 26.8.2 in the run of §1 (one test helper adapted to 26.8.2's page, no assertion changed, §9) |
| KC-SP-15 FULL local CI | **on the final SHA of F2-CP09-REC** (reported to the owner) | before: §1 (`d9b9aba`, image gate FAIL before the acceptances); no local FULL ran on `cfbc8f7` |
| KC-SP-16 GitHub CI on the final SHA | **on the final SHA of F2-CP09-REC** (reported to the owner) | run 45648436800 on `cfbc8f7` failed (IR-01, IR-02; image scan PASS); corrected in §1.0 |
| KC-SP-17 matrix of 126 criteria | **PASS** | §8 (checked against the JUnit files of the final run) |
| KC-SP-18 no open P0/P1 in scope | **PASS** | §3; independent review: no P0/P1 (§1.0) |
| KC-SP-19 no unauthorized infrastructure change | **PASS** | only `dev`; no deployment, existing realm, shared service or persistent database touched; the live `docker-compose.yml` unchanged (production configuration prepared in a separate file, not applied); the rehearsal used its own disposable containers on loopback; no Local CI change in this order |
| KC-SP-20 ready for independent review | **PASS** — the independent review was performed (no P0/P1); its findings are corrected (§1.0); a targeted verification of the corrections and the owner's acceptance remain | §1.0, §12 |

### Automatic obligation and existing accounts
`at_mfa_required` is set by the provider with the first permanent factor, in the same transaction; it is lifted only by the controlled switch-off, together with every factor. `at_mfa_mandatory` (administrators only) blocks the switch-off in the application and in the provider; T10 sets it for grant holders, nothing sets it today (enforcement point tested). Existing realms: `scripts/identity/reconcile_mfa_obligation.py` marks accounts with a permanent factor or codes, withdraws pending set-ups, deletes nothing and lists `locked` and `never` accounts for review (Keycloak keeps no history, so "never" is not proof); K `test_existing_accounts_are_reconciled_without_deleting_anything` on a disposable realm. Accounts holding codes only from before can **not** move to a permanent factor with a code (owner decision of the Final Completion Order, provider 1.1.0+: `controlled_recovery_required`); the realm refuses them before a code is asked, and they wait for the controlled recovery (T10/T11).

## 3. Status of the findings

| ID | Status | Summary |
|---|---|---|
| F-0 (a) | **CLOSED within stated limits** | 60 s check ends web and mobile sessions after a reset |
| F-1 (b) | **CLOSED** | passkey registration off in all realms (and guarded if switched on) |
| F-1R (d) | **CLOSED** | level two proves any existing factor |
| F-1R-B | **CLOSED** | option A; codes a backup; codes-only accounts handled |
| F-1R-C (P1) | **CLOSED** | provider: decision at submit, under a lock, on fresh state (KC-SP-02, KC-SP-08) |
| F-2 | **CLOSED** | window counts from the proven authentication |
| F-3 | **CLOSED** | account actions need the factor if there is one; every action is a fresh sign-in at the provider |
| F-3K | **CLOSED** | the rest closed by the provider (KC-SP-03); a password changed on Keycloak's pages (now only with the factor) is seen by the application with T11 |
| Held recovery-code sign-in | **CLOSED** | KC-SP-04 |
| Recovery-only transition | **CLOSED** | owner decision; provider 1.1.0 (1.1.1 on 26.8.2) and realm (§2.1) |
| Upstream image vulnerabilities | **CLOSED by owner acceptance (time-limited)** | Keycloak 26.8.2: 0 CRITICAL / 6 HIGH (was 9 / 93 on 26.4.7); 84 of 90 removed by the upgrade; the six accepted by the owner (`cfbc8f7`) until 2026-12-31 (Guava) and 2027-02-22; recheck at every 26.8.x release and before expiry (§2.0) |
| IR-01 … IR-07 (independent review) | IR-01–IR-04 **CLOSED**, IR-05/IR-06 **DEFERRED (INFRA-CI-02)**, IR-07 **OPEN production blocker** | §1.0 |
| F-4 | **Domain mechanism CLOSED; interface T11, authorisation T10** | unchanged |
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

### Keycloak security provider — see §2

Behaviour changes: every account security action asks for a fresh sign-in (password, and the one-time code or passkey for people who have one); a person who picks a recovery code there is refused for that change and starts again; adding a second factor, new codes or a password change on Keycloak's pages need a one-time code or passkey of the same sign-in; the first factor makes the second factor permanent: removing the last permanent factor through the application answers 409, and switching MFA off is the explicit switch-off (all sessions end, a notice is sent); a held form submitted after the account changed is refused with `access_denied`; without the provider nobody can sign in.

### Final MFA decision (option A)

Behaviour changes: a person with a second factor enters it at **every** password sign-in (web, phone, account console); new recovery codes need a one-time code or passkey; a person without any factor who asks for recovery codes sets up a one-time code first; no credential can be removed on Keycloak's pages (people use the application); spending the last recovery code signs the person out everywhere else; a codes-only account must be marked by an operator or it is refused; the application answers 409 `LAST_PERMANENT_FACTOR`; every Keycloak e-mail link is preceded by withdrawing pending credential set-ups. The test realm accepts one-time codes up to 30 steps ahead **in tests only** (the `admin` fixture), so tests need not wait for the next 30-second step; committed realms keep Keycloak's window.

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
| Existing realms | an import changes **nothing** in an existing realm; the flows, grant flow, mapper, user-profile attribute and required actions must be applied by hand, codes-only accounts marked first ([identity/README](../../identity/README.md)) | live prerequisite |
| Existing passkeys | kept; asked for at level two after the realm change; registration of new ones stays off | K `test_s03_a_passkey_enrolled_earlier_is_the_second_level` |
| Remaining security dependencies | F-1R-C and residual F-3K (owner, new component, §2); grant holders must have a factor (T10); event ingestion, Keycloak session revocation, durable notices (T11); D43 admin console hardening, production password blacklist (live) | |

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

| Criterion | Implemented in T01–T09 | Missing | Package | CP09 blocker? | Owner decision needed? |
|---|---|---|---|---|---|
| AC-AUD-08 | sign-in, sign-out, security settings, revocation, context change, refused callbacks, tokens, CSRF, workspaces; provider refusals stored as Keycloak events | failed sign-ins at Keycloak; grant changes; administrative actions | T11 (AC-AUD-10, AC-ADM-01/04), T10 (AC-PLT-10) | no | no (acknowledge the assignment) |
| AC-USR-06 | application role cannot change status; platform role has no access | "platform with a grant" | T10 (AC-PLT-07) | no | no |
| AC-SES-07 | own sessions only; platform role has no access | "platform with a grant" | T10 (AC-PLT-07) | no | no |
| AC-SES-10 | browser change revokes; country change audited when known | notice; production geo source | T11 (AC-ADM-07); the owner deferred the geo source decision to T11 (D45) | no | no (deferred by the owner) |
| AC-MOB-04 | Keycloak refuses refresh reuse | revocation with `REFRESH_REUSE` from Keycloak events | T11 (AC-AUD-10) | no | no |
| AC-POL-06 | application path; Keycloak's password form needs the factor (F-3K closed) | ending application sessions and the notice for a password changed directly on Keycloak's pages | T11 (AC-AUD-10) | no | no |
| AC-POL-13 | rotation, UA binding, Keycloak reuse refusal | `REFRESH_REUSE`, country notice | T11 | no | no |

None is marked PASS, and no deviation is accepted on the owner's behalf. AC-POL-10 is **PASS** (its P1 findings closed and proven by protection tests). AC-CTX-01 left this table: the owner reworded it (D45) and the equivalence below proves it, so it is **PASS** as evidence (acceptance stays with the owner at CP09).

### 7.1 AC-CTX-01 — equivalence of the F1 security guarantees

Reworded criterion (D45): every previously accepted F1 security guarantee is preserved; F1 tests may change or grow only if no guarantee is removed, no assertion is weakened, the equivalence is documented and proven, and the regressions pass. Basis: the 21 F1 test files as of the F2 plan commit `0e5a2d1` compared with this revision: 16 are byte-identical, 5 changed, and none lost a test function:

| F1 test (module::test) | F1 guarantee | F1 check | Check now | Equivalence | Proof |
|---|---|---|---|---|---|
| `test_ci_workflow::test_toolchain_versions_match_the_project` | every CI job that installs Python tooling uses the project's pinned uv and Python; every job has a timeout | uv and Python versions equal in each of **2** jobs; **3** `timeout-minutes` (3 jobs) | the same equality in each of **3** jobs that install uv (`test`, `identity`, `dependencies`); **5** timeouts (5 jobs: F2 added `identity` and `image-scan`) | same rule, over every job that now exists; a job without a pin or timeout still fails the test | M, passes |
| `test_idempotency::test_idempotency_table_exists_only_as_a_test_fixture` | the idempotency table is a test fixture, never a migration | single head `0001`; no migration mentions `idempotency`; the fixture holds the `CREATE TABLE` | single head `0009`; the other two assertions **unchanged** | the guarantee is carried by the unchanged scan of every migration file; the head now names the end of the F2 chain (D37 0007, isolation 0008, review 0009), still exactly one head | M, passes; `run-migrations` also checks one head |
| `test_openapi_contract::test_every_operation_is_described_and_has_a_success_response` | every documented operation has a summary and a success response | a `2xx` for every operation | a `2xx` for every operation **except exactly** `GET /api/v1/auth/login` and `GET /api/v1/auth/callback`, which must declare `302` (browser navigations of the sign-in) | strictly bounded: a third operation without `2xx` fails, as before (tightened in this order; the interim relaxation `2xx or 3xx` for any route is gone) | M, passes |
| `test_openapi_contract::test_errors_are_problem_json_and_no_default_validation_schema` | every error answer is `application/problem+json`; no default validation schema | every non-`2xx` answer is problem JSON | every non-`2xx`, non-`3xx` answer is problem JSON | the only `3xx` answers are the two redirects above (no body); every 4xx/5xx is still checked | M, passes |
| `test_openapi_contract::test_only_the_health_route_is_exposed_and_nothing_else_is_documented` → `test_only_the_documented_routes_are_exposed_and_nothing_else` | nothing is exposed or documented that was not reviewed | the path list **equals** `[/api/v1/health]`; schemas **equal** `{Health, Problem}` | the path list **equals** F1's health route plus the reviewed F2 routes; schemas **equal** the reviewed set | exact equality kept, so an unreviewed route or schema still fails; the reviewed set grew with authorized packages T06–T09 | M, passes; route access set fixed again by `test_workspace_pipeline::test_every_route_declares_its_access_and_the_set_is_exactly_the_reviewed_one` |
| `test_role_sql` (`NON_BUSINESS_TABLES`), `test_upgrade_downgrade_upgrade_and_schema_contents` | no business table in `public` before AT-03; upgrade/downgrade/upgrade exact | allow-list of technical tables **empty** | allow-list **exactly** `audit_events`, `users`, `user_sessions`, `email_change_operations`, `email_change_notifications` (D17 additive amendment); three new assertions on guard functions | any other table still fails; new assertions only add | M and migration step, pass |
| `test_roles_and_migrations` | runtime roles, grants, RLS and migrations as accepted in F1 | — | **only additions** (207 added lines, none removed): named runtime roles before the first statement (R07), exact downgrades of 0007–0009 | stronger | M, passes |

No F1 test was skipped, deselected or removed; every F1 test module runs in the main job of §1 and passes. Unchanged modules: `conftest`, `idempotency_fixture`, `rls_probe`, `test_api_conventions`, `test_api_types`, `test_config`, `test_db`, `test_db_layer`, `test_health`, `test_pagination_versioning`, `test_ratelimit`, `test_rls`, `test_rls_harness`, `test_telemetry_route`, `test_toolchain`, `test_versioning_db`.

## 8. Acceptance matrix T01–T13

`PASS` is evidence, not acceptance. `PARTIAL` and `OPEN` are never treated as `BOUNDED`; only the owner can bound a criterion.

Summary: DEFERRED: 34; PARTIAL: 7; PASS: 80; PASS with accepted deviation: 5; total 126. (Change in this order: AC-CTX-01 PARTIAL → PASS after the owner's rewording and §7.1.)

| Criterion | Status | Implementation | Test(s) | Result (local run, same SHA) | Deviation / dependency |
|---|---|---|---|---|---|
| AC-KC-01 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s07_realm_import_resolves_env_secrets_and_service_account_is_least_privilege` | 1/1 pass (K) | CI identity job imports the test realm into a fresh container; a separate step imports DEV and PROD |
| AC-KC-02 | PASS | `tests/identity/realm_lint.py` | `test_realm_lint::test_linter_rejects_each_violation`<br>`test_realm_lint::test_committed_realms_comply_with_policy`<br>`test_realm_lint::test_every_second_factor_the_application_knows_is_proven_at_level_two` | 56/56 pass (M) | also fixes the exact authentication flows, the refused password grant, the level map and the `loa_map` mapper |
| AC-KC-03 | PASS | `identity/keycloak/realm-template.json` | `test_realm_lint::test_dev_and_prod_share_nothing_environment_specific` | 1/1 pass (M) | DEV/PROD import with flow and mapper assertions: CI step, no test-case id |
| AC-KC-04 | PASS | spike report | `test_keycloak_spike::test_s01_temporary_lockout_expires_with_short_test_window`<br>`test_keycloak_spike::test_s02_direct_recovery_url_is_denied_when_reset_is_disabled`<br>`test_keycloak_spike::test_s03_max_age_zero_requires_fresh_login`<br>`test_reconciliation_keycloak::test_s03_level_two_expires_after_its_configured_age`<br>`test_reconciliation_keycloak::test_s03_a_passkey_enrolled_earlier_is_the_second_level` | 5/5 pass (K) | S1 expiry and S3 age use shortened windows (committed 900 s / 600 s asserted); the T01/REC S3 WebAuthn finding is superseded: a passkey is proven at level two (registration stays off) |
| AC-KC-05 | PASS | `identity/keycloak/realm-template.json` | `test_tokens_keycloak::test_rotation_new_realm_key_is_picked_up_without_restart`<br>`test_keycloak_spike::test_kc05_key_rotation_new_key_published_and_old_kept` | 2/2 pass (K) | — |
| AC-KC-06 | PASS | `.github/workflows/ci.yml` | `test_identity_environment::test_test_image_is_pinned_by_digest_to_the_version_in_compose`<br>`test_identity_environment::test_disposable_compose_has_no_persistent_state_and_no_shared_services`<br>`test_ci_workflow::test_runners_images_and_tools_are_pinned`<br>`test_identity_environment::test_the_image_is_built_from_the_same_pinned_images_everywhere`<br>`test_identity_environment::test_the_runtime_stage_adds_one_read_only_jar_and_stays_non_root`<br>`test_identity_environment::test_the_provider_is_built_offline_from_keycloak_s_own_libraries` | 6/6 pass (M) | — |
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
| AC-AUD-05 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_catalog_and_validation::test_every_action_accepts_its_own_allowlisted_details`<br>`test_catalog_and_validation::test_unknown_action_and_unlisted_detail_keys_are_rejected`<br>`test_email_change_review::test_neither_audit_nor_log_holds_an_address_subject_or_provider_message` | 38/38 pass (M) | — |
| AC-AUD-06 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_identity_provider_event_ingestion_is_idempotent` | 1/1 pass (M) | long hashed dedup keys would be refused by 0008; T11 must use provider ids |
| AC-AUD-07 | PASS | 0003 | `test_audit_db::test_downgrade_removes_everything_and_upgrade_restores_it`<br>`test_roles_and_migrations::test_rec_migrations_downgrade_to_exactly_what_was_there_and_back`<br>`test_roles_and_migrations::test_the_review_migration_only_widens_the_guard_and_downgrades_exactly` | 4/4 pass (M) | — |
| AC-AUD-08 | PARTIAL | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_every_catalog_action_can_be_stored`<br>`test_web_flow::test_login_session_logout_and_the_old_cookie_is_dead`<br>`test_denied_attempts::test_a_refused_bearer_token_is_recorded_by_its_reason_only`<br>`test_denied_attempts::test_a_malformed_token_is_recorded_too`<br>`test_denied_attempts::test_a_refused_workspace_switch_is_recorded_without_the_requested_tenant`<br>`test_denied_attempts::test_using_a_workspace_after_the_membership_ended_is_recorded`<br>`test_email_change_review::test_a_retry_hands_the_change_back_to_the_worker_which_finishes_it` | 11/11 pass (M) | T01–T09 part complete (refused tokens and workspaces added). Missing: failed sign-ins at Keycloak (T11, AC-AUD-10), grant changes and use (T10, AC-PLT-10), administrative actions (T11, AC-ADM-01/04) |
| AC-AUD-09 | PASS | `app/audit/{record,catalog}.py`, 0003, 0008 | `test_audit_db::test_audit_rolls_back_with_its_business_transaction`<br>`test_audit_db::test_independent_audit_survives_a_failed_request` | 2/2 pass (M) | — |
| AC-AUD-10 | DEFERRED | — | — | — | T11 |
| AC-AUD-11 | DEFERRED | — | — | — | T11 |
| AC-CTX-01 | PASS | `app/core/db.py`, `app/auth/context.py`, `app/api/v1/guards.py`; F1 test modules | `test_context_bootstrap::test_new_fields_default_to_none_and_old_usage_is_unchanged`<br>`test_openapi_contract::test_every_operation_is_described_and_has_a_success_response`<br>`test_idempotency::test_idempotency_table_exists_only_as_a_test_fixture` | 3/3 pass (M) | reworded by the owner (D45): F1 security guarantees preserved; equivalence matrix §7.1; every F1 test module passes |
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
| AC-SES-10 | PARTIAL | `app/auth/sessions/`, 0005, 0006 | `test_sessions_db::test_a_changed_browser_family_revokes_the_session_through_its_own_transaction`<br>`test_sessions_db::test_a_new_country_is_flagged_and_audited_but_does_not_revoke` | 2/2 pass (M) | browser change revokes; country change is audited when a country is given. Missing: the notice and a production geo source. The owner deferred the source decision to T11 (D45); notices with AC-ADM-07. Mobile has no UA binding (accepted, CP07) |
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
| AC-POL-05 | PASS with accepted deviation | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py`, `app/auth/security/{markers,recovery_worker}.py` | `test_security_keycloak::test_the_recovery_link_works_once`<br>`test_reconciliation_keycloak::test_f0_the_periodic_check_ends_old_sessions_after_a_reset_without_a_sign_in`<br>`test_reconciliation_keycloak::test_a_password_reset_and_the_sessions_that_existed_before_it`<br>`test_password_check::test_a_reset_ends_every_old_session_without_anybody_signing_in`<br>`test_password_check::test_checks_racing_each_other_give_one_record_and_one_notice`<br>`test_password_check::test_the_application_wires_the_check_into_its_worker`<br>`test_security_policies::test_a_sign_on_session_older_than_the_new_password_cannot_open_the_application`<br>`test_second_factor_keycloak::test_a_reset_ends_web_and_mobile_sessions_and_the_phone_cannot_come_back`<br>`test_second_factor_keycloak::test_a_forgotten_password_is_recovered_and_the_factor_stays`<br>`test_recovery_codes_keycloak::test_a_recovery_link_runs_no_pending_set_up`<br>`test_recovery_codes_keycloak::test_the_worker_withdraws_a_set_up_that_became_pending_after_the_mail`<br>`test_password_check::test_while_the_link_lives_pending_credential_setups_are_withdrawn` | 16/16 pass (M+K) | owner-authorized F-0 (a): sessions end within one 60 s worker cycle, not in the reset transaction; limits in §2 |
| AC-POL-06 | PARTIAL | `app/auth/security/{step_up,actions}.py`, `app/api/v1/{auth,me,sessions}.py` | `test_security_keycloak::test_password_change_through_keycloak_ends_other_sessions_and_rotates_this_one`<br>`test_reconciliation_keycloak::test_d37_end_to_end_with_real_mail_and_the_periodic_worker`<br>`test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2`<br>`test_account_step_up::test_with_a_second_factor_a_password_alone_is_refused`<br>`test_account_step_up::test_a_change_made_without_the_existing_factor_ends_every_session`<br>`test_second_factor_keycloak::test_the_application_asks_for_the_factor_before_every_account_action`<br>`test_second_factor_keycloak::test_a_password_change_of_a_person_with_a_factor_runs_through_it`<br>`test_second_factor_keycloak::test_a_session_older_than_the_second_factor_cannot_change_a_credential`<br>`test_second_factor_keycloak::test_a_password_form_opened_before_the_first_factor_is_refused_after_it`<br>`test_security_provider_keycloak::test_a_password_change_needs_the_permanent_factor_not_a_code`<br>`test_security_provider_keycloak::test_people_without_a_factor_change_their_password_as_before` | 40/40 pass (M+K) | application path enforced; F-3K closed by the Keycloak security provider (a held password form is refused at submit). Missing: ending application sessions and the notice for a password changed directly on Keycloak's pages (now only with the factor): T11 (AC-AUD-10) |
| AC-POL-07 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s10_password_policy_enforced_including_blacklist` | 1/1 pass (K) | production blacklist is a live prerequisite |
| AC-POL-08 | PASS | `identity/keycloak/realm-template.json` | `test_keycloak_spike::test_s03_step_up_loa2_requires_otp_and_loa1_does_not`<br>`test_security_keycloak::test_a_second_factor_is_enrolled_listed_and_kept_as_the_last_one` | 2/2 pass (K) | — |
| AC-POL-09 | DEFERRED | `app/auth/security/`, `app/api/v1/{auth,me,sessions}.py` | — | — | T10: must require an enrolled factor before a grant takes effect and set `at_mfa_mandatory` for grant holders (the switch-off is refused then; enforcement point tested) |
| AC-POL-10 | PASS | `identity/keycloak/provider/`, `identity/keycloak/realm-template.json`, `app/auth/security/{step_up,actions}.py`, `app/auth/web/stepup.py` | `test_security_policies::test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2`<br>`test_reconciliation_keycloak::test_keycloak_needs_level_two_to_remove_a_second_factor`<br>`test_reconciliation_keycloak::test_f1_nobody_can_register_a_passkey`<br>`test_reconciliation_keycloak::test_recovery_codes_alone_protect_level_two`<br>`test_second_factor_keycloak::test_with_a_second_factor_the_password_alone_never_reaches_level_two`<br>`test_second_factor_keycloak::test_every_registered_factor_reaches_level_two_and_records_when`<br>`test_second_factor_keycloak::test_the_password_alone_cannot_add_a_factor`<br>`test_second_factor_keycloak::test_the_password_alone_cannot_remove_a_factor`<br>`test_second_factor_keycloak::test_no_client_may_exchange_a_password_for_a_token`<br>`test_second_factor_keycloak::test_a_recovery_code_works_once`<br>`test_second_factor_keycloak::test_neither_single_sign_on_nor_a_refresh_nor_the_password_moves_the_factor_time`<br>`test_account_step_up::test_with_a_second_factor_proven_the_action_is_open`<br>`test_account_step_up::test_without_a_second_factor_a_fresh_password_is_enough`<br>`test_account_step_up::test_a_refreshed_bearer_token_does_not_renew_the_step_up`<br>`test_second_factor_keycloak::test_nobody_removes_a_credential_at_the_provider`<br>`test_second_factor_keycloak::test_people_who_never_set_up_a_second_factor_see_no_change`<br>`test_second_factor_keycloak::test_the_application_keeps_the_last_permanent_factor_at_the_real_provider`<br>`test_second_factor_keycloak::test_the_application_reads_the_factor_obligation_from_the_real_provider`<br>`test_second_factor_keycloak::test_a_set_up_page_opened_before_the_first_factor_is_refused_after_it`<br>`test_recovery_codes_keycloak::test_a_person_without_a_factor_sets_up_a_one_time_code_before_recovery_codes`<br>`test_recovery_codes_keycloak::test_recovery_codes_are_generated_only_after_a_permanent_factor`<br>`test_recovery_codes_keycloak::test_a_step_up_of_an_existing_session_never_takes_a_recovery_code`<br>`test_recovery_codes_keycloak::test_spending_the_last_code_needs_the_permanent_factor_and_ends_every_other_session`<br>`test_recovery_codes_keycloak::test_an_abandoned_regeneration_is_never_served_to_the_password_alone`<br>`test_recovery_codes_keycloak::test_two_sign_ins_at_once_leave_no_session_from_before_the_last_code`<br>`test_recovery_codes_keycloak::test_a_codes_only_account_waits_for_the_controlled_recovery`<br>`test_recovery_codes_keycloak::test_an_application_request_cannot_move_a_codes_only_account_either`<br>`test_recovery_codes_keycloak::test_an_obliged_account_without_any_factor_stays_closed`<br>`test_recovery_codes_keycloak::test_a_sign_in_left_at_the_factor_question_gains_nothing_when_the_factor_goes`<br>`test_recovery_codes_keycloak::test_the_user_can_neither_see_nor_lift_the_factor_obligation`<br>`test_recovery_codes_keycloak::test_a_sign_in_held_open_with_a_code_gets_no_new_codes_after_the_last_one`<br>`test_last_permanent_factor::test_the_last_permanent_factor_stays_while_recovery_codes_remain`<br>`test_last_permanent_factor::test_two_removals_at_once_cannot_both_take_a_permanent_factor`<br>`test_last_permanent_factor::test_an_account_that_must_keep_a_factor_never_ends_without_a_permanent_one`<br>`test_security_provider_keycloak::test_the_provider_replaces_every_credential_action_and_guards_the_sign_in`<br>`test_security_provider_keycloak::test_a_held_form_is_refused_and_the_refusal_is_recorded`<br>`test_security_provider_keycloak::test_the_first_permanent_factor_makes_the_obligation_permanent`<br>`test_security_provider_keycloak::test_a_second_one_time_code_needs_the_permanent_factor_in_this_sign_in`<br>`test_security_provider_keycloak::test_an_obliged_account_without_a_factor_cannot_set_one_up`<br>`test_security_provider_keycloak::test_a_person_switches_the_second_factor_off_with_the_factor_and_a_confirmation`<br>`test_security_provider_keycloak::test_a_recovery_code_cannot_switch_the_second_factor_off`<br>`test_security_provider_keycloak::test_the_switch_off_is_refused_at_the_provider_itself`<br>`test_security_provider_keycloak::test_two_first_activations_at_once_leave_exactly_one_factor`<br>`test_security_provider_keycloak::test_a_form_held_on_one_node_is_refused_after_the_factor_was_set_up_on_the_other`<br>`test_security_provider_keycloak::test_first_activations_on_two_nodes_at_once_leave_exactly_one_factor`<br>`test_security_provider_keycloak::test_new_recovery_codes_on_two_nodes_at_once_leave_one_set`<br>`test_mfa_disable::test_a_password_alone_cannot_start_it`<br>`test_mfa_disable::test_a_mandatory_second_factor_cannot_be_switched_off` | 215/215 pass (M+K) | F-1R-B closed (option A); F-1R-C, the rest of F-3K and the held recovery-code sign-in closed by the Keycloak security provider (decision at submit, under a database lock, on fresh state; two nodes tested); a recovery code never authorizes a permanent factor, accounts holding codes only wait for the controlled recovery (T10/T11). The 5-minute window for grant changes is applied by T10 (AC-PLT) |
| AC-POL-11 | PASS | `app/auth/security/notify.py` | `test_security_units::test_every_notice_is_spanish_short_and_carries_nothing_but_the_kind_and_the_time`<br>`test_security_units::test_production_default_sends_nothing_and_smtp_needs_a_host` | 8/8 pass (M) | — |
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

**F2-CP09-REC (D46):** `test_new_recovery_codes_from_single_sign_on_need_the_permanent_factor_again` now reaches the step-up within the sign-in's second on purpose (same assertions: only the permanent factor offered, then new codes; it also checks the codes were replaced); the forced re-authentication after that second is the new `test_new_recovery_codes_after_the_fresh_sign_in_need_the_permanent_factor` (a recovery code may sign in, no codes before the permanent factor). `Account.choices` (helper) returns the page to continue from. `test_the_committed_acceptances_accept_nothing` (an empty list) is replaced by tests of the authorized acceptances (§1.0, IR-02); no negative test was weakened.

No test is skipped or deselected. Two Keycloak tests that **asserted the vulnerability** were replaced by tests asserting the protection: `test_s03_webauthn_enrols_but_the_realm_does_not_use_it_for_level_two` → `test_s03_a_passkey_enrolled_earlier_is_the_second_level`; `test_recovery_codes_alone_do_not_protect_level_two` → `test_recovery_codes_alone_protect_level_two`.

Existing tests adjusted for intended behaviour:
- MFA step-up now carries `prompt=login`: expectations in `test_web_flow` and `test_validators_and_helpers`; the Keycloak removal test answers the password prompt.
- `test_account_lookup_and_delivery_are_deferred_after_generic_response`: before the answer the caller's own credentials are now read (F-3); it asserts exactly that call and still no look-up of the new address.
- The fake identity provider adds `loa_map` to level-two tokens, as the realm does; the mobile fixture configures the fake admin client (“sign out everywhere” needs it).
- `test_idempotency` head revision 0009; audit catalogue list has the new action. The WebAuthn helper can now sign in.

Final MFA decision (2026-11-25): tests that asserted the old behaviour were turned into protection tests, none removed without a replacement:
- `test_open_finding_unfinished_new_recovery_codes_can_be_taken_with_the_password` → `test_an_abandoned_regeneration_is_never_served_to_the_password_alone` (and the other recovery-code tests of §2); `test_open_finding_keycloak_changes_a_password_without_the_second_factor` → `test_a_password_change_of_a_person_with_a_factor_runs_through_it[parameter_dropped]` and `test_the_password_alone_cannot_add_a_factor[…UPDATE_PASSWORD…]`.
- `test_the_last_factor_can_be_removed_only_after_proving_it` → `test_nobody_removes_a_credential_at_the_provider` (Keycloak removes nothing now) and the application tests of `test_last_permanent_factor.py`; `test_keycloak_needs_level_two_to_remove_a_second_factor` now also asserts that the account console refuses after level two.
- The codes-only account in the parameter lists is now made as an older account (`codes_only_account`, marked); `test_recovery_codes_alone_protect_level_two` uses it.
- Password-only sign-ins in tests of accounts with a factor now answer the factor (`Account.sign_in`, `Rig.sign_in(prove=…)`); tests that open Keycloak's password form answer its new sign-in question; `test_recovery_codes_can_be_enrolled_through_keycloak_d41` sets up the one-time code that now comes first.
- `test_neither_single_sign_on_nor_a_refresh_nor_the_password_moves_the_factor_time`: a password re-entry is now answered with the factor question and moves nothing.
- `test_linter_rejects_each_violation`: three expectations reworded for the exact-flow check; 13 cases added.
- Three new tests record open behaviour and pass by **showing** it (`test_open_finding_*` ×2, `test_known_gap_*`): they are not evidence of protection.

Keycloak security provider order (2026-11-25):
- The three tests that showed a gap became protection tests: `test_open_finding_a_set_up_page_opened_before_the_first_factor_still_adds_one` → `test_a_set_up_page_opened_before_the_first_factor_is_refused_after_it`; `test_open_finding_a_password_form_opened_before_the_first_factor_still_changes_it` → `test_a_password_form_opened_before_the_first_factor_is_refused_after_it`; `test_known_gap_a_sign_in_held_open_with_a_code_receives_the_pending_new_codes` → `test_a_sign_in_held_open_with_a_code_gets_no_new_codes_after_the_last_one`. `test_the_provider_itself_runs_pending_set_ups_for_a_link` → `test_a_link_sent_past_the_application_runs_no_set_up_either`.
- The first factor now sets the obligation, so removing the only permanent factor answers 409: `test_a_second_factor_is_enrolled_listed_required_for_removal_and_removed` → `test_a_second_factor_is_enrolled_listed_and_kept_as_the_last_one`; `test_the_application_keeps_the_last_permanent_factor_at_the_real_provider` asserts 409 after the codes went.
- Credential actions follow a fresh sign-in: helpers answer it (`Account.password_again`, `at_provider`); `locked_account` expects the refusal after the last code; `codes_only_account(marked=False)` removes the marker the provider now sets.
- `test_realm_lint`: five new cases; `test_identity_environment`: three supply-chain tests; Local CI self-test: two broker cases.
- No test was removed without a replacement, none is skipped.

Final Completion Order: `test_an_unmarked_codes_only_account_is_refused` → `test_a_codes_only_account_waits_for_the_controlled_recovery` (marked and unmarked); `test_a_marked_codes_only_account_moves_to_a_permanent_factor` and `test_the_application_request_moves_a_codes_only_account_too` → `test_an_application_request_cannot_move_a_codes_only_account_either` (the transition is forbidden now); `test_the_last_code_of_a_codes_only_account_leaves_it_closed` → `test_an_obliged_account_without_any_factor_stays_closed`; `test_a_sign_in_left_at_the_code_question_gains_nothing_when_the_codes_run_out` → `test_a_sign_in_left_at_the_factor_question_gains_nothing_when_the_factor_goes` (a codes-only account no longer reaches the code question); the option-A tests expect a refusal for the codes-only account; `test_recovery_codes_alone_protect_level_two` expects the refusal; the reconciliation test lists codes-only accounts for review. New: `tests/identity/test_scan_gate.py` (22), 9 broker self-tests, realm linter case for the codes-only refusal. No assertion was weakened: every changed test asserts the stricter policy.

Keycloak Security Upgrade (26.8.2): no test removed, skipped or weakened.
- `tests/identity/webauthn.py` (helper, not a test): reads the challenge and relying-party id in both forms the login theme writes (26.4: `'…'`, 26.8: FreeMarker `?c`, `"…"`) and, like a browser, reports `authenticatorAttachment=platform` for its built-in key. Before this, 79 passkey tests failed on 26.8.2 at the helper's own assertion, not at a security assertion.
- `test_identity_environment::test_test_image_is_pinned_by_digest_to_the_version_in_compose`: the tests' pin must equal the prepared production file (version **and** digest; before: version only, against the live compose); the live `docker-compose.yml` may name only the version the prepared file replaces. `test_the_image_is_built_from_the_same_pinned_images_everywhere` also covers the prepared file.
- `realm_lint` and `test_realm_lint`: `at-admin-svc` must carry `kc-admin-api` (one new rule, one new negative case).
- `test_security_provider_keycloak` and the CI import step expect provider version 1.1.1.
- `test_openapi_contract::test_every_operation_is_described_and_has_a_success_response`: tightened back to F1 strength (§7.1).
- Docstrings and one recorded spike observation name 26.8.2.

## 10. Open production blockers

- **Image vulnerabilities (KC-SP-12)**: Keycloak 26.8.2 — 0 CRITICAL / 6 HIGH, accepted by the owner for a limited time; the acceptances expire 2026-12-31 (Guava: upgrade to the 26.8.x patch with Guava 33.7.2) and 2027-02-22; production needs them valid, or renewed by the owner after a recheck.
- **IR-07 (mandatory, D46)**: guarded credential changes with Keycloak's production cache stack (default Infinispan of `start`) and a database failover or restart during a change have not been tested (evidence: two nodes with local caches); test before production.
- **Production Keycloak upgrade**: prepared, not applied ([UPGRADE-26.8.2.md](../../identity/keycloak/UPGRADE-26.8.2.md), `identity/docker-compose.keycloak-production.yml`); needs its own authorization; the one-time 14-day exception does not cover production; existing realms need `kc-admin-api` on `at-admin-svc`; backup first, rollback only by restore.

- Persistent database migration state unverified (F1 R05, §6).
- Existing realms: the AutoTramita image first, then `reconcile_mfa_obligation.py` and the manual steps of [identity/README](../../identity/README.md); production start-up options of the image (D43).
- D37: O15 mail provider; F-4 needs T10 authority and T11 interface.
- R11 (provisioning script vs `harden.sql`, Keycloak database), R12/O20 (readiness), real `TRUSTED_PROXY_CIDRS`, O06–O17, D13 (same-origin route), D43 (Keycloak hardening), production password blacklist, AT-20 legal basis and retention (**D42 OPEN**).
- Dart analysis deferred (R10). Local CI limits LCI-04/05.

## 11. Remaining T10–T13 obligations

- **T10 (implemented 2026-11-25, [CP10 report](F2-CP10-REPORT.md); `at_mfa_mandatory` is set, never lifted, by T10):** set `at_mfa_mandatory` for grant holders (the switch-off is then refused, enforcement tested); authority for the controlled recovery of a locked account (marked, no factor left); platform grants and mandatory level two for grant holders with an already enrolled factor (AC-PLT, AC-POL-09, AC-AUTHZ-03, platform parts of AC-USR-06 and AC-SES-07); five-minute window for grant changes; the F-4 authority; migrations from 0010.
- **T11:** interface for the controlled recovery and for setting `at_mfa_required`; notices for factors added on Keycloak's pages (`UPDATE_TOTP`, `UPDATE_CREDENTIAL`); administration, durable outbox and Celery, Keycloak events (AC-AUD-08/10, AC-MOB-04, changes made on Keycloak's pages), ending Keycloak sessions, the F-4 interface, country notice if a source is decided.
- **T12:** frozen API contract (AC-API).
- **T13:** final acceptance and traceability test.

## 12. Status, blocker and independent security review

**Update 2026-11-25 (F2-CP09-REC):** the owner accepted the six findings (`cfbc8f7`), the independent review was performed and its findings are corrected or assigned (§1.0). The text below is the state before those steps and is kept as history.

**F2-T09-REC — IMPLEMENTATION COMPLETED / OWNER SECURITY DECISION REQUIRED.** The upgrade, the provider's compatibility, the preservation of the security policy, the migration rehearsal, AC-CTX-01 and the regressions are complete and pass. KC-SP-12 is not a technical blocker any more: 84 of 90 findings are gone, and the six HIGH findings left have no supported fix inside 26.8.2. Each is analysed (§2.0); the gate correctly fails until the owner decides, and nothing was accepted on the owner's behalf.

**Decision needed from the owner (minimal proposal).** For each of the six findings, either a time-limited acceptance in `vulnerability-acceptances.json` (`accepted_by: owner`, decision reference, expiry at most 90 days; proposed entries and dates in `vulnerability-review-26.8.2.json`) or waiting for the next release:
1. CVE-2026-102554 (Guava): accept to 2026-12-31, then upgrade to the 26.8.x patch that ships Guava 33.7.2 (patch release, same procedure).
2. CVE-2026-91403 (JDK): accept to 2027-02-22; the vendor's mitigation (ca-certificates RHSA-2026:88459) is in the image.
3. CVE-2026-119373, -119374, -119379, -119586 (sqlite-libs): accept to 2027-02-22; not loaded by the service, -119374 not affected per Red Hat, -119586 concerns a program that is not installed.
Not recommended: disabling the gate, automatic exceptions, or replacing jars or OS packages of the official image.

**Significant decisions taken within the order's autonomy:**
- the live `docker-compose.yml` is not changed: it is the definition of the running stack directory, and the first start of 26.8.2 migrates the Keycloak database irreversibly; the future production configuration is a separate prepared file, and a test ties the tests' pin to it (version and digest);
- `at-admin-svc` gets `kc-admin-api` with its earlier default scopes (the set of Keycloak's own `admin-cli`); roles unchanged; disabling the audience check was not considered;
- provider version 1.1.1 (compatibility only); `Time.currentTimeSeconds()`; the removal warning of the still abstract `getEntities()` is suppressed on that method only;
- the tests' software passkey adapted to 26.8.2's page (no assertion changed);
- the OpenAPI success-response test tightened back to F1 strength for AC-CTX-01;
- a repeatable rehearsal script (`scripts/identity/upgrade_rehearsal.py`) on disposable containers, its result committed;
- the JDK build image, PostgreSQL, Redis, Trivy and the gate were not changed; no 26.8.1 step.

**Independent security review — final scope** (after the owner's decision on KC-SP-12):
1. **Provider source** (`identity/keycloak/provider`, 1.1.1): the policy table, lock and transaction handling, `getAuthnCredentials`, `ACTION_TOKEN_USER` and the start note, the overridden factories; the 26.8.2 review per extension point.
2. **Realm flows and clients** (`realm-template.json`, `realm_lint.py`), including `kc-admin-api` on `at-admin-svc`.
3. **Application security actions and the switch-off**, plus the admin client and its token scope.
4. **Concurrency** with Keycloak's production cache stack and a database failover.
5. **Supply chain**: Dockerfile, `build.sh`, pins and provenance of 26.8.2, the broker rules, the scan job and its gate; the six remaining findings and the owner's decision on them.
6. **Upgrade and rollback**: UPGRADE-26.8.2.md, the rehearsal, the prepared production file; restore-only rollback.
7. **Keycloak 26.8 features on by default but unused** (JWT authorization grant, workflows, SCIM per realm, Kubernetes service accounts, federated client authentication): confirm they stay unreachable in the realms.
8. **Abuse paths not covered by tests**: the application's service account, the switch-off page template, event and log content on errors, and the administrator race noted in §2.1.

CP09 is **not** accepted; its owner acceptance additionally needs the decision on KC-SP-12 above and the production blockers of §10 acknowledged. AC-SES-10 is deferred to T11 by the owner; AC-CTX-01 is reworded and evidenced (§7.1).

### Files changed by F2-CP09-REC
`tests/identity/test_recovery_codes_keycloak.py`, `tests/identity/accounts.py`, `tests/identity/test_scan_gate.py`; `identity/keycloak/vulnerability-review-26.8.2.json` (IR-04 note only), `identity/keycloak/provider/README.md`, `identity/README.md`; `docs/design/F2-{DECISION-REGISTER,EXECUTION-ORDER,ACCEPTANCE-CRITERIA,CP09-RECONCILIATION-REPORT}.md`. No application, provider, realm, workflow or `scan_gate.py` change.

### Files changed by the Keycloak Security Upgrade
`identity/keycloak/Dockerfile`, `identity/keycloak/provider/**` (two sources, factory version, VERSION 1.1.1, `build.sh` manifest, README), `identity/keycloak/realm-{template,dev,prod,test}.json`, `identity/docker-compose.keycloak-test.yml`, `identity/docker-compose.keycloak-production.yml` (new, prepared), `identity/keycloak/UPGRADE-26.8.2.md` (new), `identity/keycloak/upgrade-rehearsal-26.8.2.json` (new), `identity/keycloak/vulnerability-review-26.8.2.json` (new), `identity/README.md`; `.github/workflows/ci.yml` (pins, job name, provider version); `scripts/identity/upgrade_rehearsal.py` (new); tests: `tests/identity/{realm_lint,test_realm_lint,test_identity_environment,test_security_provider_keycloak,webauthn}.py`, docstrings of the Keycloak test modules, `tests/test_openapi_contract.py`; documents: ADR-008, decision register (D45), execution order, acceptance criteria, AT-02, T09 policy notes, MASTER-BLUEPRINT pointer, this report. Not changed: `docker-compose*.yml` of the stack, `scan_gate.py`, `vulnerability-acceptances.json`, Local CI.

### Files changed by the Final Completion Order
`identity/keycloak/provider/**` (policy, VERSION 1.1.0, decision table, README), `identity/keycloak/realm-{template,dev,prod,test}.json`, `identity/keycloak/vulnerability-acceptances.json` (new), `identity/keycloak/vulnerability-review-26.4.7.json` (new), `identity/README.md`; `.github/workflows/ci.yml` (job `image-scan`, provider version), `scripts/ci/lib/{broker,runner,profiles}.py`, `scripts/ci/selftest.py`, `scripts/identity/scan_gate.py` (new), `scripts/identity/reconcile_mfa_obligation.py`; tests: `tests/identity/test_scan_gate.py` (new), `tests/identity/{realm_lint,test_realm_lint,test_recovery_codes_keycloak,test_second_factor_keycloak,test_reconciliation_keycloak,test_security_provider_keycloak}.py`, `tests/test_ci_workflow.py`; documents: ADR-008, decision register, execution order, AT-02, LOCAL-CI.md, this report. Files of the previous revision: see Git history.

`scripts/ci/**` is outside the D35 path list: the broker gained exactly one build rule (the AutoTramita Keycloak image, from its directory, from pinned images, without network), as the order asked for the integration into Local CI; listed for the owner's review. **D40 / T13:** `tests/test_f2_scope.py`, which D40 names as the scope check of every diff, does not exist; T13 lists the final one. Recorded as a discrepancy, not implemented here (T13 not authorized).
