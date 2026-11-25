# autotramita-keycloak-security-provider

A minimal Keycloak provider that enforces the AutoTramita MFA policy **at the moment a credential changes**. Authorized by the owner on 2026-11-25 (F2-T09-REC, Keycloak Security Provider Authorization). Version `1.0.0`, built against Keycloak **26.4.7** only.

## Why it exists

Realm configuration alone could not close three findings, all with the same cause: Keycloak decides whether a person may set up or change a credential when the **form is shown**, not when it is **submitted**, and a form kept open (reloading keeps it alive) is accepted later whatever happened to the account meanwhile:

| Finding | Before | With the provider |
|---|---|---|
| F-1R-C (P1) | a one-time code page opened with the password while the account had no factor added the intruder's device after the person turned MFA on | refused at submit: the account now has a permanent factor and this sign-in proved none |
| F-3K, rest (P2) | the same with the new-password form | refused at submit |
| Held sign-in with a code | password + unused recovery code, held open while the last code is spent elsewhere, received new codes | refused: a recovery code never authorizes new codes |

Signing the user out, disabling the user, a new password, `notBefore` or shorter lifetimes do not end such a form (tried on 26.4.7).

## Security invariants

Checked for every combination by `PolicyCheck` (2,048 cases) on every build, and on a real Keycloak by the tests below.

1. An account that holds a one-time code or passkey changes a credential only with a one-time code or passkey **proven in this sign-in**, at most 10 minutes after the sign-in started. Exceptions: a password reset through the person's e-mail link (D20; every factor stays), and new recovery codes right after setting up the first permanent factor in the same sign-in.
2. Recovery codes never authorize a new permanent factor, new codes, a password change or the switch-off. Only an account from before (holding codes only, marked by an operator) may move to a permanent factor with one.
3. Recovery codes only ever follow a permanent factor.
4. The first permanent factor sets `at_mfa_required=true` in the same transaction as the credential. Opening or abandoning a form never sets it.
5. An account with `at_mfa_required` and no usable factor gets no factor set up: it stays closed until a controlled recovery (T10/T11).
6. An e-mail link never adds a factor and never switches it off.
7. The switch-off needs a fresh permanent factor, the explicit confirmation, and no `at_mfa_mandatory`. Every factor, the codes and the obligation go in one transaction, and every other session ends.
8. If anything is missing or fails, the change does not happen (fail closed).

## Extension points (Keycloak 26.4.7)

| SPI | Use | Keycloak's classification |
|---|---|---|
| `required-action` | `GuardedActionFactory.{Totp,Passkey,PasswordlessPasskey,RecoveryCodes,Password}` replace `CONFIGURE_TOTP`, `webauthn-register`, `webauthn-register-passwordless`, `CONFIGURE_RECOVERY_AUTHN_CODES` and `UPDATE_PASSWORD` under the same IDs; `DisableSecondFactor` adds `at-disable-mfa` | internal |
| `authenticator` | `at-security-guard`, first step of `browser-loa-forms` | internal |
| `jpa-entity-provider` | table `AT_MFA_GUARD` (Liquibase changelog in the jar) | internal |
| theme resources | `at-disable-mfa.ftl` and its messages | — |

At start-up Keycloak warns that each of these SPIs "is internal and may change without notice". These are the documented extension points of the Server Developer Guide (Authentication SPI, Required actions, JPA entity providers). However, Keycloak gives **no compatibility promise** for them between versions. That is why the provider is compiled against the exact jars of the pinned image, and the whole regression suite is mandatory for every upgrade (below).

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

- **Trusted:** the Keycloak server and its database; the admin REST API (operators, and the application's `at-admin-svc` account with `manage-users`). Admin API changes do not pass through the guard.
- **Not trusted:** the browser, every form field and parameter, single sign-on state, and the application's status parameters (the application reads the credentials back).
- **`at_mfa_required` and `at_mfa_mandatory`:** user-profile attributes that only administrators can see or change. Writers:
  - `at_mfa_required`: the provider (set) and the switch-off (lift).
  - `at_mfa_mandatory`: T10 (platform grants). Nothing sets it today.

## Fail-closed behaviour

- **Provider missing:** `browser-loa-forms` references `at-security-guard`, so no interactive sign-in completes. A CI step proves this with the upstream image.
- **Lock or table unavailable, user missing or disabled, any exception:** the request fails and rolls back.
- **Refusal:** the action ends with `access_denied` back to the client.
  - The event `CUSTOM_REQUIRED_ACTION_ERROR` is recorded with `custom_required_action` and `reason` (a fixed code).
  - The server log line carries the action, reason, realm and user id, and no secret, code, address or form value.

## Dependencies on T10 and T11

- **T10:** set and clear `at_mfa_mandatory` with platform grants; grant holders must have a factor; authority for the controlled recovery of a locked account.
- **T11:**
  - the interface for that recovery and for operators;
  - ingestion of `CUSTOM_REQUIRED_ACTION_ERROR`, `UPDATE_TOTP` and `UPDATE_CREDENTIAL` events (notices for changes made on Keycloak's pages);
  - ending Keycloak sessions from the application.

## Build, identity and reproducibility

- **Build:** `identity/keycloak/Dockerfile`, multi-stage, from two images pinned by digest:
  - `quay.io/keycloak/keycloak:26.4.7@sha256:9409c59b…`
  - `eclipse-temurin:21-jdk@sha256:8ad118b1…`
- **Build stage:** compiles the sources with `javac --release 21 -Xlint:all -Werror` against `/opt/keycloak/lib` of the pinned Keycloak image, the only classpath. It has **no third-party dependency** and downloads nothing; Local CI builds without network.
  - The jar is built twice and the two copies must be identical.
  - Its entries are checked against an allow-list.
  - `PolicyCheck` runs before packaging.
- **Runtime stage:** the pinned Keycloak image plus `providers/autotramita-keycloak-security-provider.jar` (0444, owner 1000), user 1000. No build tool and no secret.
- **Identity:** the jar's SHA-256 is printed by every build. For version 1.0.0 it is `7e9e297e58b4ed4542a933e64d3d74e3e737ff1e5108adb5909b897d54f32732`.
- **Integrity of the classpath:** the Keycloak jars in the pinned image are byte-identical to the Maven Central artifacts of 26.4.7. The SHA-1 of `keycloak-services`, `keycloak-server-spi`, `keycloak-server-spi-private` and `keycloak-model-jpa` was compared during the analysis.
- **Same build everywhere:** CI builds `autotramita-keycloak:ci` on GitHub and in Local CI from the same Dockerfile and digests. The developer compose file builds the same image. The image is not pushed to any registry.
- **Image vulnerabilities:** the runtime image differs from upstream by one jar with no dependency, so its exposure is exactly that of the pinned upstream image. **A CVE scan of the image is not part of CI**: Local CI gives steps no network for a vulnerability database. This is an open item.

## Upgrading Keycloak

1. Change both pinned references together (Dockerfile defaults, `ci.yml`, compose; a test keeps them equal).
2. Build. A compile error means the SPI changed: read the new built-in classes before adapting anything.
3. Re-check against the new sources:
   - `ProviderManager.compareFactories`;
   - every cast of a set-up factory (`grep -rn "(UpdateTotp)\|(WebAuthnRegisterFactory)\|(WebAuthnPasswordlessRegisterFactory)"`);
   - `LoginActionsService.requiredActionPOST` (the decision must still run in `processAction` inside the request transaction);
   - `AuthenticatorUtil.getAuthnCredentials`, `DefaultActionTokenKey.ACTION_TOKEN_USER_ID`, `JpaEntityProvider`.
4. Run the full Keycloak job. **Mandatory regression tests:** `test_security_provider_keycloak.py`, `test_second_factor_keycloak.py`, `test_recovery_codes_keycloak.py` (including the two-node tests), the fail-closed step and the realm import step.
5. Raise `VERSION` and record the new jar hash here.

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

## Known limitations

- The loser of a concurrent first change gets Keycloak's error page, not a friendly refusal.
- Keycloak marks the SPIs used as internal, with no compatibility promise (see Upgrading).
- A person who picks a recovery code at the fresh sign-in before adding a factor or changing the password is refused and has to start again with the authenticator.
- Changes through the admin REST API bypass the guard (trust boundary).
- Production start-up options (`kc.sh build --optimized`, database, cache stack) belong to D43 and deployment; tests use `start-dev`. The two-node test uses PostgreSQL with local caches.
