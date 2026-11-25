# identity/ — Keycloak configuration as code (F2-T01)

Nothing here is deployed. The shared Keycloak, Compose and Traefik are untouched (D43 and the
realm import are live prerequisites needing separate authorization).

| File | Purpose |
|---|---|
| `keycloak/realm-template.json` | Single source of the realm (clients, brute force, token lifetimes, step-up flow) |
| `keycloak/realm-{dev,prod,test}.json` | **Generated** by `scripts/identity/render_realms.py`; never edit by hand; tests fail on drift |
| `keycloak/blacklists/at-common-passwords.txt` | Tiny **test-only** list. Production needs a vetted common-password list (live prerequisite) |
| `docker-compose.keycloak-test.yml` | Disposable Keycloak for developer machines: builds the same image as CI |
| `keycloak/Dockerfile` | The AutoTramita Keycloak image: pinned Keycloak 26.8.2 plus the security provider, built from source |
| `docker-compose.keycloak-production.yml` | **Prepared, not applied**: the future production Keycloak (AutoTramita image, same pins). The live `docker-compose.yml` still names upstream 26.4.7 |
| `keycloak/UPGRADE-26.8.2.md` | Upgrade from 26.4.7: changes that concern AutoTramita, rehearsal results, production steps and rollback |
| `keycloak/upgrade-rehearsal-26.8.2.json` | Result of `scripts/identity/upgrade_rehearsal.py` (disposable containers only) |
| `keycloak/provider/` | The security provider ([its README](keycloak/provider/README.md): invariants, concurrency, upgrade, rollback, image scan) |
| `keycloak/vulnerability-acceptances.json` | Owner acceptances of CRITICAL/HIGH image findings (time-limited, owner only; six since 2026-11-25, tested against the authorized list) |
| `keycloak/vulnerability-review-26.8.2.json` | Reviewed findings of the current image, one by one, with a recommendation for the owner (nothing accepted) |
| `keycloak/vulnerability-review-26.4.7.json` | Findings of the image before the upgrade, kept for comparison |

## Workflow
1. Change `realm-template.json`, then `python scripts/identity/render_realms.py`.
2. `uv run pytest tests/identity` runs the policy linter (`tests/identity/realm_lint.py`) and drift check; no Keycloak needed.
3. Keycloak tests (`-m keycloak`) run in the CI job `identity`; locally only against the disposable compose file on a developer machine, never against shared services or real data.

## Required actions
The realm file lists every required action. Passkey registration (`webauthn-register`, `webauthn-register-passwordless`) is **off** (decision F-1 b); a passkey an account already has is still proven. `delete_credential` is **off**: nobody removes a credential on Keycloak's pages, people remove factors through the application, which keeps the last permanent one. Every credential action (`CONFIGURE_TOTP`, `CONFIGURE_RECOVERY_AUTHN_CODES`, `UPDATE_PASSWORD`, both passkey registrations) and `at-disable-mfa` have `max_auth_age` 0: they always follow a fresh sign-in. The security provider replaces the built-in credential actions and decides when the form is submitted.

## Sign-in and levels (F-1R, F-2, final MFA decision and security provider of 2026-11-25)
- `browser-loa-forms` starts with `at-security-guard` (the provider): it records when the sign-in started. Without the provider nobody signs in.
- **Level one** (`browser-loa-1`): the password and, for whoever has one, a second factor (one-time code, passkey, passwordless passkey or recovery code). People who never set up a factor see only the password.
- Silent probes (`browser-probe-*`) find out which credentials a person has without asking anything; the deny sub-flows refuse an account that holds recovery codes only (before any code is asked, so none is spent) and a marked account without any factor. Both wait for the controlled recovery (T10/T11): a recovery code is no proof of a permanent factor (owner decision of 2026-11-25).
- Spending the **last** code also needs the permanent factor and ends every other session of the person (`user-session-limits`, one session).
- **Level three** (internal): a permanent factor proven in this authentication. **Level four** holds the recovery codes, so new codes need level three first. The order of the levels in `browser-loa-forms` (1, 3, 2, 4) is what assigns them; Keycloak refuses two conditions for the same level.
- **Level two** (`browser-loa-2`): a step-up of an existing session asks for a permanent factor (never a recovery code); a factor proven in the same sign-in counts. Only a person without any factor and without the marker is offered a one-time code set-up.
- `directGrantFlow` is `direct-grant-denied`: no client can exchange a password for a token, including the built-in `admin-cli` of the application realm.
- Clients `at-web` and `at-mobile` map the session note `loa-map` into the claim `loa_map`. **Without the mapper the application never accepts level two** (fail closed).
- The linter (`tests/identity/realm_lint.py`) fixes the exact flows with their configuration, the action configurations and the profile attributes.

## `at_mfa_required` and `at_mfa_mandatory`
User-profile attributes visible and changeable by **administrators only**.
- `at_mfa_required=true`: the account must never fall back to the password alone. The provider sets it with the first permanent factor, in the same transaction; the controlled switch-off lifts it, only together with every factor. A marked account without any usable factor, and any account holding recovery codes only, is locked until a controlled recovery (T10/T11).
- `at_mfa_mandatory=true`: the second factor may not be switched off (platform grants). The platform-grant module (T10) sets it, together with `at_mfa_required`, before a grant takes effect, through `at-admin-svc`; it never lifts it (that is the T11 operator interface). The application and the provider both refuse the switch-off when it is set.

## Switching the second factor off
The application's `POST /me/security/mfa-disable-requests` (explicit confirmation, fresh second factor) sends the person to `kc_action=at-disable-mfa`: a fresh sign-in with a one-time code or passkey, then a confirmation page. The provider removes every permanent factor and recovery code and the obligation in one transaction and ends every other session; the application then ends every application session.

## A realm that already exists
The realm file applies only when a realm is **first imported**. Nothing in this repository changes an existing realm, and no existing credential is removed. Before real users, with a separate authorization, apply by hand and verify (admin console or admin API), then run the checks of the CI step "Import DEV and PROD realms" against it:
1. Run Keycloak from the AutoTramita image (`keycloak/Dockerfile`): the provider must be present before the flows reference it.
2. User profile: add `at_mfa_required` and `at_mfa_mandatory`, view and edit for `admin` only.
3. `uv run python scripts/identity/reconcile_mfa_obligation.py --base-url … --realm …` (report), review it, then with `--apply`: it marks every account with a permanent factor or recovery codes and withdraws pending credential set-ups. It deletes nothing. Accounts it lists as `never` or `locked` are reviewed by hand: Keycloak keeps no history, so "never had MFA" cannot be proven.
4. Authentication flows and their configurations: create every flow of the realm file exactly (`browser-loa-forms` with `at-security-guard` first and the levels in the order 1, 3, 2, 4; the probe, deny, level-three and level-four sub-flows; `direct-grant-denied`); bind the direct grant flow to `direct-grant-denied`.
5. Required actions: `delete_credential` off, both passkey registrations off, `at-disable-mfa` on, and the `max_auth_age` configurations of the realm file. Event type `CUSTOM_REQUIRED_ACTION_ERROR` stored.
6. Add the `at-loa-times` mapper to `at-web` and `at-mobile`.
7. Add the client scope `kc-admin-api` to `at-admin-svc` as a default scope (Keycloak 26.8 accepts admin API tokens only with it; its migration adds it to `admin-cli` and `admin-console` only).
8. Sign out all sessions of the realm, so no session authenticated under the old flow survives.

Rollback without re-opening the gap: [provider README](keycloak/provider/README.md#rollback-without-re-opening-the-gap).

## Secrets
Realm files contain no secret. Confidential clients use `${AT_WEB_CLIENT_SECRET}` and `${AT_ADMIN_SVC_CLIENT_SECRET}`, resolved by Keycloak from its environment at import (verified in spike S7). Per environment, secrets differ and live outside the repository.

## Signing key rotation (D06, exercised by test `test_kc05_*`)
1. Add an RS256 key provider with a higher priority (`rsa-generated`, active). New tokens use it at once; the old key stays published.
2. Keep the old key as passive for at least 14 days (longer than any token or session lifetime).
3. Remove the old key. Do this every 90 days, or immediately on suspected compromise (then also revoke sessions).
The application caches JWKS for 10 minutes and refetches at most once a minute on an unknown `kid` (D05).

## Not covered here
Compose import mount, hiding the admin console and `/realms/master` (D43), SMTP settings for dev/prod, production password blacklist. The Keycloak upgrade, its backup and rollback: [keycloak/UPGRADE-26.8.2.md](keycloak/UPGRADE-26.8.2.md).

## First platform grant administrator (DEV/CI only, F2-T10, D30)

`uv run python scripts/identity/bootstrap_platform_admin.py --email <person> [--days 90]` with the database **owner** credentials (`APP_DB_OWNER_USER`/`APP_DB_OWNER_PASSWORD` and the `POSTGRES_*` settings) and the `AUTH_*` settings of `at-admin-svc` in the environment. `ENVIRONMENT=prod` is refused. The person must already exist in the application (signed in once), be active and hold a one-time code or passkey; the command marks the account `at_mfa_mandatory`, gives one `PLATFORM_GRANT_ADMIN` grant for at most 90 days and records it (`actor_type=SYSTEM`). Four-eyes approvals need two grant administrators, so bootstrap two people. A production bootstrap needs its own owner approval.
