# autotramita-keycloak-security-provider

A minimal Keycloak provider that enforces the AutoTramita MFA policy **at the moment a credential changes**. Authorized by the owner on 2026-11-25 (F2-T09-REC, Keycloak Security Provider Authorization). Version `1.2.0`, built against Keycloak **26.8.2** only. 1.1.0 (2026-11-25, owner decision): a recovery code never authorizes a permanent factor, also not on an account that holds codes only. 1.1.1 (2026-11-25, Keycloak Security Upgrade, D45): compatibility with Keycloak 26.8.2 only, the policy is unchanged. 1.2.0 adds locked, role-authorized platform operations for marking MFA mandatory and removing a second factor.

## Why it exists

Realm configuration alone could not close three findings, all with the same cause: Keycloak decides whether a person may set up or change a credential when the **form is shown**, not when it is **submitted**, and a form kept open (reloading keeps it alive) is accepted later whatever happened to the account meanwhile:

| Finding | Before | With the provider |
|---|---|---|
| F-1R-C (P1) | a one-time code page opened with the password while the account had no factor added the intruder's device after the person turned MFA on | refused at submit: the account now has a permanent factor and this sign-in proved none |
| F-3K, rest (P2) | the same with the new-password form | refused at submit |
| Held sign-in with a code | password + unused recovery code, held open while the last code is spent elsewhere, received new codes | refused: a recovery code never authorizes new codes |

Signing the user out, disabling the user, a new password, `notBefore` or shorter lifetimes do not end such a form (tried on 26.4.7; the provider's tests that hold such forms pass unchanged on 26.8.2).

## Security invariants

Checked for every combination by `PolicyCheck` (2,048 cases) on every build, and on a real Keycloak by the tests below.

1. An account that holds a one-time code or passkey changes a credential only with a one-time code or passkey **proven in this sign-in**, at most 10 minutes after the sign-in started. Exceptions: a password reset through the person's e-mail link (D20; every factor stays), and new recovery codes right after setting up the first permanent factor in the same sign-in.
2. Recovery codes never authorize a new permanent factor, new codes, a password change or the switch-off. An account holding recovery codes only (from before; none can be created now) is refused at sign-in and waits for the controlled recovery (T10/T11) — owner decision of 2026-11-25.
3. Recovery codes only ever follow a permanent factor.
4. The first permanent factor sets `at_mfa_required=true` in the same transaction as the credential. Opening or abandoning a form never sets it.
5. An account with `at_mfa_required` and no usable factor, and an account holding recovery codes only, gets no factor set up: it stays closed until a controlled recovery (T10/T11). The realm refuses such an account before it asks for a code, so no code is spent.
6. An e-mail link never adds a factor and never switches it off.
7. The switch-off needs a fresh permanent factor, the explicit confirmation, and no `at_mfa_mandatory`. Every factor, the codes and the obligation go in one transaction, and every other session ends.
8. If anything is missing or fails, the change does not happen (fail closed).

## Extension points (Keycloak 26.8.2)

| SPI | Use | Keycloak's classification |
|---|---|---|
| `required-action` | `GuardedActionFactory.{Totp,Passkey,PasswordlessPasskey,RecoveryCodes,Password}` replace `CONFIGURE_TOTP`, `webauthn-register`, `webauthn-register-passwordless`, `CONFIGURE_RECOVERY_AUTHN_CODES` and `UPDATE_PASSWORD` under the same IDs; `DisableSecondFactor` adds `at-disable-mfa` | internal |
| `authenticator` | `at-security-guard`, first step of `browser-loa-forms` | internal |
| `jpa-entity-provider` | table `AT_MFA_GUARD` (Liquibase changelog in the jar) | internal |
| `realm-resource` | `at-security`, locked platform operations | internal |
| theme resources | `at-disable-mfa.ftl` and its messages | — |

At start-up Keycloak warns that each of these SPIs "is internal and may change without notice". These are the documented extension points of the Server Developer Guide (Authentication SPI, Required actions, JPA entity providers). However, Keycloak gives **no compatibility promise** for them between versions. That is why the provider is compiled against the exact jars of the pinned image, and the whole regression suite is mandatory for every upgrade (below).

**Review against the sources of 26.8.2 (2026-11-25).** Sources and jars of 26.4.7 and 26.8.2 from Maven Central (the image jars are byte-identical to them), compared class by class. Regression evidence: the Keycloak job on 26.8.2, 257 tests, one node and two nodes on one database, plus the upgrade rehearsal ([UPGRADE-26.8.2.md](../UPGRADE-26.8.2.md)).

| Internal API used | Changed in 26.8.2? | Security effect | Correction | Regression evidence |
|---|---|---|---|---|
| `RequiredActionProvider`, `RequiredActionContext`, `InitiatedActionSupport`, `CredentialRegistrator` | no (imports reordered) | none | none | every `test_security_provider_keycloak` test |
| `RequiredActionFactory` | `isOneTimeAction()` defaults to `true` (was `false`); built-ins dropped their own overrides | stricter: execute-actions links with passkey registration are single-use; the guarded factories inherit the built-in value as before | none | `test_a_link_sent_past_the_application_runs_no_set_up_either`, `test_a_recovery_link_runs_no_pending_set_up` |
| `UpdateTotp`, `UpdatePassword`, `RecoveryAuthnCodesAction` (extended) | only the `isOneTimeAction()` override removed | none | none | KC-SP-02/03/04 tests |
| `WebAuthnRegisterFactory`, `WebAuthnPasswordlessRegisterFactory` (extended) | trust verifier built lazily | none | none | passkey tests (68) |
| `WebAuthnRegister` (wrapped) | challenge consumed atomically across nodes, duplicate credential becomes an error page, AAGUID policy needs attestation, attachment checked | stricter; an error leaves the status at challenge, so the provider records nothing | none | `test_first_activations_on_two_nodes_at_once_leave_exactly_one_factor`, passkey tests |
| Casts of the set-up factories (`OTPFormAuthenticator`, `WebAuthnAuthenticator`, `WebAuthnPasswordlessAuthenticator`) | same casts | the factories must still extend the built-ins | none | `test_the_provider_replaces_every_credential_action_and_guards_the_sign_in` |
| `ProviderManager.compareFactories` | no | none | none | same test (operational info 1.2.0 on every action, also the CI import step) |
| `LoginActionsService.processRequireAction` (`processAction` inside the request transaction) | no | none | none | `test_a_held_form_is_refused_and_the_refusal_is_recorded` |
| `AuthenticatorUtil.getAuthnCredentials` | no | none | none | KC-SP-02/03 tests |
| `AuthenticatorUtil.logoutOtherSessions` (switch-off) | also removes other authentication sessions and, by default, offline sessions | stricter | none | `test_a_person_switches_the_second_factor_off_with_the_factor_and_a_confirmation` |
| `DefaultActionTokenKey.ACTION_TOKEN_USER_ID` | key unchanged; nonce from `SecretGenerator`; `ResetCredentialEmail` now requires the token user | stricter | none | `test_a_forgotten_password_is_recovered_and_the_factor_stays` |
| `Time.currentTime()` | deprecated (`int`) | none | `Time.currentTimeSeconds()` (same clock, `long`); the note is parsed as `long` (an `int` note of a sign-in started before the upgrade still parses) | `test_a_second_one_time_code_needs_the_permanent_factor_in_this_sign_in`, freshness tests |
| `JpaEntityProvider` / `JpaEntityProviderFactory`, `JpaConnectionProvider` | `getEntities()` marked for removal (still abstract; Quarkus finds the entity at build time) | none | `@SuppressWarnings("removal")` on that method only | lock tests on two nodes; rehearsal: guard rows kept and written after the migration |
| `UserCache`, `UserStoragePrivateUtil.userLocalStorage` | no | none | none | `test_a_form_held_on_one_node_is_refused_after_the_factor_was_set_up_on_the_other` |
| `SubjectCredentialManager` (`getStoredCredentialsStream`, `removeStoredCredentialById`) | new default method `getFirstFactorCredentialsStream` only | none | none | switch-off and removal tests |
| `EventType.CUSTOM_REQUIRED_ACTION_ERROR`, `ServerInfoAwareProviderFactory` | no | none | none | `test_a_held_form_is_refused_and_the_refusal_is_recorded` |
| Hibernate 7.1.4 → 7.4.9, PostgreSQL driver 42.7.7 → 42.7.13 | lock hint and Liquibase changelog unchanged | none | none | two-node concurrency tests (3 rounds each) |
| Admin REST API (trusted, outside the guard) | needs the `kc-admin-api` scope in the token | the application's `at-admin-svc` was refused (fail closed, but the application's checks would fail) | `kc-admin-api` default scope on `at-admin-svc` (realm file, linter); manual step for existing realms | `test_the_application_reads_the_factor_obligation_from_the_real_provider`, rehearsal (401 → 200) |

No change needed a new mechanism, a fork or the removal of a protection.

**How the replacement works.** Keycloak prefers a custom factory to an internal one with the same ID (`ProviderManager.compareFactories`), and the order is raised as well (100). Each factory **extends** the built-in class, because Keycloak's own authenticators cast the factory of their set-up action to it (`OTPFormAuthenticator`, `WebAuthnAuthenticator`, `WebAuthnPasswordlessAuthenticator`). The subclass keeps every built-in behaviour and only wraps the provider it creates.

## Where the decision is taken, and why it holds

- **Form shown** (`requiredActionChallenge`): a refusal here spares the person a form they cannot use. It is a convenience, not the decision.
- **Form submitted** (`processAction`) — the decision:
  1. Lock the person's row in `AT_MFA_GUARD` (`PESSIMISTIC_WRITE`, timeout 10 s) through the request's own JPA transaction.
  2. Evict the person from the user cache and read the account again from the database (local storage).
  3. Evaluate the policy.
  4. Run the built-in action.
  5. Record the change and set the obligation in the **same transaction**.

  The lock is released only at commit or rollback.
- **Concurrent requests.** Two guarded changes of one person are serialized; the second sees what the first committed.
  - If the person has no guard row yet, both requests insert one. One insert fails on the primary key and its whole transaction rolls back: the loser gets Keycloak's error page and nothing is written.
- **Several instances.** The lock is a database row lock, so it holds across every Keycloak instance sharing the database. No in-memory lock is involved. Tests run on two nodes with **local** caches (the harsher case: no cache invalidation between nodes). They prove that a form held on one node is refused after a factor was set up on the other, and that concurrent first activations leave exactly one factor.
- **Cache and staleness.**
  - Credentials are read with a query each time, so they are always current.
  - User attributes are read through the transaction's entity manager: if the entity was loaded earlier in the same request, the obligation may reflect the start of that request. No decision depends on the obligation alone in a way a concurrent writer could exploit: the obligation is set together with a credential (which is read fresh), and only lifted together with every factor.
- **Proof of the factor.** Keycloak's own authentication-session note of the credential types verified in this sign-in (`AuthenticatorUtil.getAuthnCredentials`), plus the provider's own note of when the interactive sign-in started (`at-security-guard`). Neither a single sign-on session, a previously shown form, the `acr` level, nor anything the person can edit counts.
- **E-mail link.** It is recognised by Keycloak's server-side note `ACTION_TOKEN_USER`, set only after the action token has been verified.

## Trust boundaries

- **Trusted:** the Keycloak server and its database; the admin REST API (operators, and the application's `at-admin-svc` account with `manage-users`). The application's MFA marking and second-factor removal use the guarded routes below; other direct admin REST changes remain outside this guard.
- **Not trusted:** the browser, every form field and parameter, single sign-on state, and the application's status parameters (the application reads the credentials back).
- **`at_mfa_required` and `at_mfa_mandatory`:** user-profile attributes that only administrators can see or change. Writers:
  - `at_mfa_required`: the provider (set) and the switch-off (lift).
  - `at_mfa_mandatory`: T10 (platform grants), before a grant takes effect; T10 never lifts it (T11 operator interface).
- **Platform operations (`/realms/{realm}/at-security`):** only a bearer token with the realm's `realm-management/manage-users` role is accepted, before looking up the target user. `POST users/{id}/mandatory` atomically sets both attributes only if a permanent factor exists (otherwise 409). `DELETE users/{id}/credentials/{credentialId}` removes only a second factor and refuses to orphan recovery codes or leave an obliged account without a permanent factor (409); unknown users or credentials return 404. Both operations share the per-user database lock with guarded credential changes.

## Fail-closed behaviour

- **Provider missing:** `browser-loa-forms` references `at-security-guard`, so no interactive sign-in completes. A CI step proves this with the upstream image.
- **Lock or table unavailable, user missing or disabled, any exception:** the request fails and rolls back.
- **Refusal:** the action ends with `access_denied` back to the client.
  - The event `CUSTOM_REQUIRED_ACTION_ERROR` is recorded with `custom_required_action` and `reason` (a fixed code).
  - The server log line carries the action, reason, realm and user id, and no secret, code, address or form value.

## Dependencies on T10 and T11

- **T10 (implemented, [CP10 report](../../../docs/design/F2-CP10-REPORT.md)):** sets `at_mfa_mandatory` with platform grants (lifting it is T11); grant holders must have a permanent factor; authority for the controlled recovery of a locked account (interface T11).
- **T11:**
  - the interface for that recovery and for operators;
  - ingestion of `CUSTOM_REQUIRED_ACTION_ERROR`, `UPDATE_TOTP` and `UPDATE_CREDENTIAL` events (notices for changes made on Keycloak's pages);
  - ending Keycloak sessions from the application.

## Build, identity and reproducibility

- **Build:** `identity/keycloak/Dockerfile`, multi-stage, from two images pinned by digest:
  - `quay.io/keycloak/keycloak:26.8.2@sha256:7e66a96e…` (26.4.7 until 2026-11-25)
  - `eclipse-temurin:21-jdk@sha256:8ad118b1…`
- **Build stage:** compiles the sources with `javac --release 21 -Xlint:all -Werror` against `/opt/keycloak/lib` of the pinned Keycloak image, the only classpath. It has **no third-party dependency** and downloads nothing; Local CI builds without network.
  - The jar is built twice and the two copies must be identical.
  - Its entries are checked against an allow-list.
  - `PolicyCheck` runs before packaging.
- **Runtime stage:** the pinned Keycloak image plus `providers/autotramita-keycloak-security-provider.jar` (0444, owner 1000), user 1000. No build tool and no secret.
- **Identity:** the jar's SHA-256 is printed by every build. Version 1.2.0 (on 26.8.2): `3032d40d2be776393bef7a439f05be56fe5800f581e3906d2bee7ceb6849a592`; version 1.1.1 (on 26.8.2): `d61ac28e362008f530b3ab6b5642fbbb892eda5f0137669d5be96b935b7c574a` (1.1.0 on 26.4.7 was `12cfbc66…`, 1.0.0 `7e9e297e…`).
- **Integrity of the classpath:** the Keycloak jars in the pinned image are byte-identical to the Maven Central artifacts of 26.8.2. The SHA-1 of `keycloak-services`, `-server-spi`, `-server-spi-private`, `-model-jpa`, `-core`, `-common`, `-model-storage`, `-model-storage-private`, `-model-storage-services` and `-model-infinispan` was compared (and the same for 26.4.7).
- **Same build everywhere:** CI builds `autotramita-keycloak:ci` on GitHub and in Local CI from the same Dockerfile and digests. The developer compose file builds the same image. The image is not pushed to any registry.
- **Image vulnerabilities (KC-SP-12):** the CI job `image-scan` builds the image, has the pinned scanner `aquasec/trivy:0.76.2@sha256:8f6bb947…` download its vulnerability database (schema 2) and Java database (schema 1), saves the image, scans it **without network** for operating-system packages and Java components (JSON report), and runs `scripts/identity/scan_gate.py`. The gate fails on a database older than 48 hours (Java: 7 days) or missing, on a report of another scanner or without OS and Java coverage, on a report not bound to the saved image archive and its exact tag, on a missing, unknown or inconsistent severity (the authoritative package-level vendor is `redhat` for OS packages and `ghsa` for Java components), on every CRITICAL finding, and on every HIGH finding without a time-limited acceptance by the owner bound to its severity, installed and fixed version (`identity/keycloak/vulnerability-acceptances.json`; rules: [PROD-SEC-01 implementation](../../../docs/infrastructure/PROD-SEC-01-IMPLEMENTATION.md#3-gate-rules-as-implemented), D49). There is no automatic exception. **State on 2026-11-25, after the upgrade to 26.8.2:** 0 CRITICAL and 6 HIGH (Guava, the JDK's eMudhra distrust, four in `sqlite-libs`), all carried over from 26.4.7, none new. Reviewed one by one in [`vulnerability-review-26.8.2.json`](../vulnerability-review-26.8.2.json) and accepted by the owner for a limited time (commit `cfbc8f7`: Guava until 2026-12-31, the others until 2027-02-22); the gate passes. Red Hat rates CVE-2026-91403 Critical at the CVE level where its package-level rating for `java-21-openjdk-headless` and Trivy say HIGH (IR-04); under D49 the package-level rating is authoritative, the CVE-level Critical stays documented and is reassessed at every renewal and before every deployment, and the acceptance rests on the installed vendor mitigation. A test keeps the committed acceptances equal to the authorized ones. Before the upgrade, with the same databases: 9 CRITICAL and 93 HIGH (90 distinct, [`vulnerability-review-26.4.7.json`](../vulnerability-review-26.4.7.json), kept for comparison).

## Upgrading Keycloak

1. Change both pinned references together (Dockerfile defaults, `ci.yml`, the developer compose file and the prepared production file `identity/docker-compose.keycloak-production.yml`; a test keeps them equal). The live `docker-compose.yml` changes only with a production authorization.
2. Build. A compile error (also a deprecation: the build uses `-Werror`) means the SPI changed: read the new built-in classes before adapting anything.
3. Re-check against the new sources:
   - `ProviderManager.compareFactories`;
   - every cast of a set-up factory (`grep -rn "(UpdateTotp)\|(WebAuthnRegisterFactory)\|(WebAuthnPasswordlessRegisterFactory)"`);
   - `LoginActionsService.requiredActionPOST` (the decision must still run in `processAction` inside the request transaction);
   - `AuthenticatorUtil.getAuthnCredentials`, `DefaultActionTokenKey.ACTION_TOKEN_USER_ID`, `JpaEntityProvider`;
   - interfaces the guarded actions wrap (`RequiredActionProvider`, `RequiredActionFactory`): a new default method is not delegated automatically;
   - what the admin REST API requires of a token (26.8: the `kc-admin-api` scope) and the realm migrations of every version in between.
4. Run the full Keycloak job and the upgrade rehearsal (`scripts/identity/upgrade_rehearsal.py`) from the old image to the new one. **Mandatory regression tests:** `test_security_provider_keycloak.py`, `test_second_factor_keycloak.py`, `test_recovery_codes_keycloak.py` (including the two-node tests), the fail-closed step and the realm import step.
5. Raise `VERSION` and record the new jar hash here. Record the review per extension point (as above for 26.8.2) and the production steps (as in [UPGRADE-26.8.2.md](../UPGRADE-26.8.2.md)).

## Reconciling an existing realm

`scripts/identity/reconcile_mfa_obligation.py` (report by default, `--apply` to write):
- marks every account holding a permanent factor or recovery codes;
- withdraws pending credential set-ups;
- leaves `locked` and `never` accounts for review by hand (Keycloak keeps no history, so "never had MFA" cannot be proven);
- deletes nothing and lifts no obligation.

Steps, in order:
1. Install the image.
2. Run the script with `--apply`.
3. Apply the realm changes of `identity/README.md`.
4. Sign every session out.

Never run it against a realm with real users without a separate authorization.

## Rollback without re-opening the gap

- **Do not remove the jar while the realm still references `at-security-guard`.** Nobody can sign in; this is intended (fail closed).
- **Do not restore the built-in actions while accounts with MFA exist.** That re-opens F-1R-C. A rollback of the provider therefore means either:
  - (a) going back to a previous provider version, which is safe; or
  - (b) removing the provider **and** switching off every credential set-up action and `at-disable-mfa` in the realm. In that state factors cannot be added or changed until the provider is back.
- **Never lift `at_mfa_required` in bulk.**
- **The `AT_MFA_GUARD` table** may stay; it holds only user ids, realm ids and a counter.

## Database unavailable

Observed on the two-node setup (exploration, 2026-11-25): with the database stopped, a submitted set-up form answers 500 and nothing is written (the transaction cannot start or commit). With the database paused, the request waits; when the database returns, the decision is taken then, under the lock, on the state of that moment. Keycloak cannot sign anybody in without its database in either case.

## Known limitations

- The loser of a concurrent first change gets Keycloak's error page, not a friendly refusal.
- Keycloak marks the SPIs used as internal, with no compatibility promise (see Upgrading).
- A person who picks a recovery code at the fresh sign-in before adding a factor or changing the password is refused and has to start again with the authenticator.
- Changes through the admin REST API bypass the guard (trust boundary). If an administrator removes the last permanent factor while a sign-in waits at the factor question, that sign-in already passed the refusal of codes-only accounts and may finish with a recovery code (a second factor, not the password alone).
- Production start-up options (`kc.sh build --optimized`, database, cache stack) belong to D43 and deployment; tests use `start-dev`. The two-node test uses PostgreSQL with local caches.
