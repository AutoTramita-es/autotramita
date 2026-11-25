# Keycloak 26.4.7 → 26.8.2: upgrade, rehearsal and rollback

F2-T09-REC Keycloak Security Upgrade (owner authorization of 2026-11-25, D45). **Development, tests and CI run 26.8.2. Nothing was deployed**: the live definition `docker-compose.yml` still names the upstream 26.4.7 image, and no existing realm or persistent database was touched. Applying the steps below is a production deployment and needs its own owner authorization.

## Version and image

| Item | Value |
|---|---|
| Release | Keycloak 26.8.2, GitHub release dated 2026-11-05, tag commit `e514445f9dcdabc5bdcf67cab56c1e49655de067` |
| Image | `quay.io/keycloak/keycloak:26.8.2@sha256:7e66a96e4739239070aeaf72e4c5decf0f7f682cfc725b9f7ea2b336eaba38b3` (multi-arch index; amd64 manifest `sha256:75b5c435…`), published 2026-11-19 |
| Earlier images of the same tag | `sha256:723b1d6e…` (2026-11-09), `sha256:c68e286c…` (2026-11-12): the tag is rebuilt when the base image changes, so only the digest identifies the image |
| Authenticity | official repository; SLSA provenance of the amd64 manifest names `https://github.com/keycloak/keycloak` at the tag commit; the Keycloak jars are byte-identical (SHA-1) to the Maven Central artifacts of 26.8.2. The project does not sign its images (no cosign signature) |
| Runtime | Red Hat Enterprise Linux 9.9 (ubi9-micro), OpenJDK 21.0.13.1 (was 9.7 and 21.0.9) |
| Build image | `eclipse-temurin:21-jdk@sha256:8ad118b1…`, unchanged: the provider is still compiled with `--release 21` |
| 14-day rule | one-time exception by the owner, development, tests and CI only (ADR-008, D45). The pinned image is younger than 14 days; a production deployment is not covered by the exception |

## What changed between 26.4.7 and 26.8.2 that concerns AutoTramita

| Change | Effect here | Done |
|---|---|---|
| Admin REST API requires the `kc-admin-api` scope (its audience) in the token, `admin.audienceCheckEnabled` on by default (`AdminRoot`) | the application's service account `at-admin-svc` got **401**: F-0 check, account actions and the MFA reads would fail | `at-admin-svc` has `kc-admin-api` as a default scope in the realm file (with its earlier default scopes, the same set as Keycloak's own `admin-cli`); the realm linter requires it. **Existing realms need the manual step below** (the migration adds the scope only to `admin-cli` and `admin-console`) |
| `Time.currentTime()` deprecated; `JpaEntityProvider.getEntities()` marked for removal | the provider did not compile (`-Werror`) | `Time.currentTimeSeconds()` (same clock, `long`), `@SuppressWarnings("removal")` on the still abstract method; provider 1.1.1 |
| `RequiredActionFactory.isOneTimeAction()` now defaults to `true` | execute-actions e-mail links for passkey registration are single-use now (stricter); the built-in TOTP, password and recovery-code actions were already single-use | nothing |
| WebAuthn registration consumes its challenge atomically across nodes; duplicate credentials end in an error page | stricter; a refused or repeated submit never reaches the provider's success path | nothing |
| Login theme passes WebAuthn values as FreeMarker `?c` literals and reads `authenticatorAttachment` | the tests' software authenticator could not read the page | test helper reads both forms and reports `platform` like a browser (no assertion changed) |
| `logoutOtherSessions` also removes the person's other authentication sessions and offline sessions; `ResetCredentialEmail` requires the action-token user; `AuthenticationProcessor` checks that an execution belongs to the flow and that the session user did not change | stricter | nothing |
| New default features: JWT authorization grant, workflows, Kubernetes service accounts, federated client authentication, persistent login failures | each needs explicit configuration (identity provider, client attribute, workflow definition) that the realms do not have; the password grant stays refused | nothing; noted for the independent review |
| Realm migrations 26.6.1–26.8.2 | add the organization browser step to the built-in `browser` flow (not used by the realms), admin-permission scopes, the `kc-admin-api` scope and client-registration policies | rehearsal below |
| `sid` and `session_state` are 24 characters of base64url instead of a UUID | inside the application's `kc_session_id` check (`^[A-Za-z0-9._:-]{1,128}$`, migration 0005); the application treats them as strings | nothing; real sign-in, mobile and back-channel logout tests pass |
| Admin API, SCIM and brute force: SCIM API is a default feature but off per realm (`scimApiEnabled` false, not set by the realms); `maxSecondaryAuthFailures` (secondary-factor lockout) defaults to 0 and is not set; login failures are stored in the database | no change of the realm's behaviour (AC-POL-01 tests pass) | nothing |
| PostgreSQL driver 42.7.13, Hibernate 7.4.9, Infinispan 16.0.15 | the provider's row lock (`PESSIMISTIC_WRITE`, 10 s timeout) and table changelog work unchanged; two-node tests pass | nothing |

The provider's SPI review per extension point is in the [provider README](provider/README.md#extension-points-keycloak-2682).

## Rehearsal on disposable containers (2026-11-25)

`scripts/identity/upgrade_rehearsal.py` (its docstring has the commands). PostgreSQL 16 (pinned) in tmpfs, loopback only, throwaway credentials; images built without network from `ad693c5` (26.4.7, provider 1.1.0) and from this revision (26.8.2, provider 1.1.1). Result: [`upgrade-rehearsal-26.8.2.json`](upgrade-rehearsal-26.8.2.json).

| Check | Result |
|---|---|
| Clean installation of 26.8.2 and import of the realms | CI: test realm on one node and on two nodes sharing PostgreSQL, DEV and PROD realms in isolated instances (job `identity`) |
| Old realm imported into 26.4.7, accounts with a password only, a one-time code, a one-time code with recovery codes, a passkey, and a mandatory one-time code; one web session with tokens | done on 26.4.7 |
| Backup before the upgrade (`pg_dump -Fc`) | 237,026 bytes |
| 26.8.2 started on that database | migrated in 16.8 s through 26.6.1, 26.6.2, 26.7.0, 26.8.0, 26.8.2; `MIGRATION_MODEL` 26.4.7 → 26.8.2 |
| Users, credentials (id, type, hashes of the stored secret and data), `at_mfa_required`, `at_mfa_mandatory`, required actions, `AT_MFA_GUARD` rows | **identical** before and after |
| Sign-in after the upgrade | password only, one-time code, passkey, recovery code, mandatory account: all succeed |
| Session from before the upgrade | single sign-on continues; the refresh token is accepted (persistent user sessions) |
| Provider after the upgrade | 1.1.1 loaded, `at-security-guard` still in `browser-loa`; a first factor set up after the upgrade sets `at_mfa_required` and writes its guard row |
| `at-admin-svc` on the migrated realm | **401** until the `kc-admin-api` default scope is added, **200** after |
| Rollback by restore: the backup restored into a new database under 26.4.7 | starts; state equal to before the upgrade; a one-time-code sign-in succeeds (changes made after the upgrade are lost, as expected) |
| Downgrade: 26.4.7 on the migrated database | **starts** with only a warning (`Possibly incorrect state of migration … already migrated to newer version '26.8.2'`). Keycloak does not stop it, so the procedure forbids it |

## Production upgrade (prepared, not applied)

Prerequisites: a separate owner authorization for the deployment; the remaining HIGH findings decided by the owner (KC-SP-12); the 14-day rule met or a new exception; D43 production options decided. Prepared configuration: [`identity/docker-compose.keycloak-production.yml`](../docker-compose.keycloak-production.yml) (AutoTramita image, both pins).

1. Announce a maintenance window; a Keycloak minor upgrade is not a rolling update (all nodes stop; `ROLLING_UPDATES_V2` covers patch releases only).
2. Stop every Keycloak node (`docker compose … stop keycloak`).
3. Back up the Keycloak database with `pg_dump -Fc` and verify the dump by restoring it into a scratch database; keep it until the upgrade is accepted. Record its SHA-256.
4. Build the image from the prepared file (`… -f identity/docker-compose.keycloak-production.yml build keycloak`) and compare the provider jar hash with the provider README.
5. Start **one** node with the new image and wait for the migration log lines up to `migrated realm … to 26.8.2`; then the other nodes.
6. Add the default client scope `kc-admin-api` to `at-admin-svc` in every AutoTramita realm (admin console: Clients → at-admin-svc → Client scopes → Add → Default; or `PUT /admin/realms/{realm}/clients/{id}/default-client-scopes/{scope id}`), then verify that a token of `at-admin-svc` reaches `GET /admin/realms/{realm}/users?max=1`.
7. If the realm predates the security provider: the steps of [identity/README](../README.md#a-realm-that-already-exists) (provider image first, then the reconciliation script and the flows).
8. Verify: the checks of the CI step "Import DEV and PROD realms" against the live realm; provider version 1.1.1 in the server information; one sign-in per factor kind with a test account; the application's F-0 check and security overview answer.

## Rollback

- **Before step 5 finished** (migration failed or interrupted): stop, restore the backup into the database, start the 26.4.7 image.
- **After the migration**: the only rollback is **restore** of the step-3 backup with the 26.4.7 image. Changes made after the upgrade (new users, factors, passwords) are lost and must be reconciled by hand; sessions issued by 26.8.2 end.
- **Never** start 26.4.7 on a database migrated to 26.8.2: Keycloak allows it with a warning, but a downgrade of the schema and model is not supported.
- The provider's own rollback rules still apply ([provider README](provider/README.md#rollback-without-re-opening-the-gap)): never the upstream image while the realm references `at-security-guard`, never the built-in credential actions while accounts with MFA exist.
