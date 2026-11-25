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
The realm file lists every required action. Passkey registration (`webauthn-register`, `webauthn-register-passwordless`) is **off** (decision F-1 b). Level two proves a passkey an account already has (F-1R), but registration stays off until the owner decides separately to switch it on.

## Level two (F-1R, F-2)
- `browser-loa-2` first asks for **any** second factor the person has (one-time code, passkey, passwordless passkey or recovery code). Only a person without any is offered to set up a one-time code.
- `directGrantFlow` is `direct-grant-denied`: no client can exchange a password for a token, including the built-in `admin-cli` of the application realm.
- Clients `at-web` and `at-mobile` map the session note `loa-map` into the claim `loa_map`. The application counts a step-up from the level-two time in it. **Without the mapper the application never accepts level two** (fail closed).
- The linter (`tests/identity/realm_lint.py`) fixes the exact flows; a change to them needs a change there and Keycloak tests.

## A realm that already exists
The realm file applies only when a realm is **first imported**. Nothing in this repository changes an existing realm, and no existing credential is removed. Before real users, apply by hand and verify (admin console or admin API), then run the checks of the CI step "Import DEV and PROD realms" against it:
1. Authentication flows: create `browser-loa-2-factor`, `browser-loa-2-enrol` and `direct-grant-denied` exactly as in the realm file, replace the one-time code step of `browser-loa-2` with the two sub-flows, bind the direct grant flow to `direct-grant-denied`.
2. Add the `at-loa-times` mapper to `at-web` and `at-mobile`.
3. Switch off both passkey registration actions.
4. Check accounts that already hold a passkey or only recovery codes: they are asked for that factor at level two from then on.
5. Sign out all sessions of the realm, so no session authenticated under the old flow survives.

## Open items (owner decision, see the CP09 report)
- Keycloak 26.4.7 does not require the second factor on its password form.
- After the last recovery code, an abandoned regeneration is served after a password-only sign-in.

## Secrets
Realm files contain no secret. Confidential clients use `${AT_WEB_CLIENT_SECRET}` and `${AT_ADMIN_SVC_CLIENT_SECRET}`, resolved by Keycloak from its environment at import (verified in spike S7). Per environment, secrets differ and live outside the repository.

## Signing key rotation (D06, exercised by test `test_kc05_*`)
1. Add an RS256 key provider with a higher priority (`rsa-generated`, active). New tokens use it at once; the old key stays published.
2. Keep the old key as passive for at least 14 days (longer than any token or session lifetime).
3. Remove the old key. Do this every 90 days, or immediately on suspected compromise (then also revoke sessions).
The application caches JWKS for 10 minutes and refetches at most once a minute on an unknown `kid` (D05).

## Not covered here
Compose import mount, hiding the admin console and `/realms/master` (D43), SMTP settings for dev/prod, production password blacklist, realm backup, Keycloak upgrade procedure.
