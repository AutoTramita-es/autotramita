# identity/ — Keycloak configuration as code (F2-T01)

Nothing here is deployed. The shared Keycloak, Compose and Traefik are untouched (D43 and the
realm import are live prerequisites needing separate authorization).

| File | Purpose |
|---|---|
| `keycloak/realm-template.json` | Single source of the realm (clients, brute force, token lifetimes, step-up flow) |
| `keycloak/realm-{dev,prod,test}.json` | **Generated** by `scripts/identity/render_realms.py`; never edit by hand; tests fail on drift |
| `keycloak/blacklists/at-common-passwords.txt` | Tiny **test-only** list. Production needs a vetted common-password list (live prerequisite) |
| `docker-compose.keycloak-test.yml` | Disposable Keycloak 26.4.7 (digest pinned) for developer machines; CI uses the same image |

## Workflow
1. Change `realm-template.json`, then `python scripts/identity/render_realms.py`.
2. `uv run pytest tests/identity` runs the policy linter (`tests/identity/realm_lint.py`) and drift check; no Keycloak needed.
3. Keycloak tests (`-m keycloak`) run in the CI job `identity`; locally only against the disposable compose file on a developer machine, never against shared services or real data.

## Required actions
The realm file lists every required action. Passkey registration (`webauthn-register`, `webauthn-register-passwordless`) is **off** (decision F-1 b); a passkey an account already has is still proven. `delete_credential` is **off**: nobody removes a credential on Keycloak's pages, people remove factors through the application, which keeps the last permanent one. `UPDATE_PASSWORD` has `max_auth_age` 0: the password form always follows a fresh sign-in.

## Sign-in and levels (F-1R, F-2, final MFA decision of 2026-11-25)
- **Level one** (`browser-loa-1`): the password and, for whoever has one, a second factor (one-time code, passkey, passwordless passkey or recovery code). People who never set up a factor see only the password.
- Silent probes (`browser-probe-*`) find out which credentials a person has without asking anything; the deny sub-flows refuse an account with recovery codes only unless it is marked, and a marked account without any factor.
- A recovery code without a permanent factor leads to setting up a one-time code. Spending the **last** code also needs the permanent factor and ends every other session of the person (`user-session-limits`, one session).
- **Level three** (internal, never requested by the application): a permanent factor proven in this authentication. **Level four** holds the recovery codes, so new codes need level three first. The order of the levels in `browser-loa-forms` (1, 3, 2, 4) is what assigns them; Keycloak refuses two conditions for the same level.
- **Level two** (`browser-loa-2`): a step-up of an existing session asks for a permanent factor (never a recovery code); a factor proven in the same sign-in counts. Only a person without any factor and without the marker is offered a one-time code set-up.
- `directGrantFlow` is `direct-grant-denied`: no client can exchange a password for a token, including the built-in `admin-cli` of the application realm.
- Clients `at-web` and `at-mobile` map the session note `loa-map` into the claim `loa_map`. The application counts a step-up from the level-two time in it. **Without the mapper the application never accepts level two** (fail closed).
- The linter (`tests/identity/realm_lint.py`) fixes the exact flows with their configuration; a change to them needs a change there and Keycloak tests.

## `at_mfa_required` (accounts that must keep a second factor)
A user attribute in the realm's user profile, visible and changeable by **administrators only**. Value `true` marks an account that must never fall back to the password alone. Set it for every account that holds recovery codes only (they are refused otherwise) and for any account an operator decides must keep a factor. A marked account without any usable factor is locked until a controlled recovery (T10/T11); no other way exists. Nothing sets it automatically.

## Open: a set-up page opened before the first factor (F-1R-C)
Keycloak 26.4.7 runs a credential set-up page when it is submitted, whatever the account looks like by then. A page opened with the password while an account had no factor still adds a one-time code (or changes the password) after the person turned one on. No realm setting closes this; see the CP09 report §2 for the proposed provider.

## A realm that already exists
The realm file applies only when a realm is **first imported**. Nothing in this repository changes an existing realm, and no existing credential is removed. Before real users, apply by hand and verify (admin console or admin API), then run the checks of the CI step "Import DEV and PROD realms" against it:
1. User profile: add the attribute `at_mfa_required` with view and edit for `admin` only.
2. Find accounts that hold recovery codes but no one-time code or passkey and set `at_mfa_required` to `true` on each **before** step 3 (unmarked they can no longer sign in).
3. Authentication flows and their configurations: create every flow of the realm file exactly (`browser-loa-forms` with the levels in the order 1, 3, 2, 4; the probe, deny, level-three and level-four sub-flows; `direct-grant-denied`); bind the direct grant flow to `direct-grant-denied`.
4. Required actions: `delete_credential` off, both passkey registrations off, `UPDATE_PASSWORD` configured with maximum age 0.
5. Add the `at-loa-times` mapper to `at-web` and `at-mobile`.
6. Remove pending `CONFIGURE_TOTP`, `CONFIGURE_RECOVERY_AUTHN_CODES`, `webauthn-register*` and `delete_credential` actions from users (a pending one would run for the holder of any e-mail link).
7. Sign out all sessions of the realm, so no session authenticated under the old flow survives.

## Secrets
Realm files contain no secret. Confidential clients use `${AT_WEB_CLIENT_SECRET}` and `${AT_ADMIN_SVC_CLIENT_SECRET}`, resolved by Keycloak from its environment at import (verified in spike S7). Per environment, secrets differ and live outside the repository.

## Signing key rotation (D06, exercised by test `test_kc05_*`)
1. Add an RS256 key provider with a higher priority (`rsa-generated`, active). New tokens use it at once; the old key stays published.
2. Keep the old key as passive for at least 14 days (longer than any token or session lifetime).
3. Remove the old key. Do this every 90 days, or immediately on suspected compromise (then also revoke sessions).
The application caches JWKS for 10 minutes and refetches at most once a minute on an unknown `kid` (D05).

## Not covered here
Compose import mount, hiding the admin console and `/realms/master` (D43), SMTP settings for dev/prod, production password blacklist, realm backup, Keycloak upgrade procedure.
