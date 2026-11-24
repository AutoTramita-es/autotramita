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

## Secrets
Realm files contain no secret. Confidential clients use `${AT_WEB_CLIENT_SECRET}` and `${AT_ADMIN_SVC_CLIENT_SECRET}`, resolved by Keycloak from its environment at import (verified in spike S7). Per environment, secrets differ and live outside the repository.

## Signing key rotation (D06, exercised by test `test_kc05_*`)
1. Add an RS256 key provider with a higher priority (`rsa-generated`, active). New tokens use it at once; the old key stays published.
2. Keep the old key as passive for at least 14 days (longer than any token or session lifetime).
3. Remove the old key. Do this every 90 days, or immediately on suspected compromise (then also revoke sessions).
The application caches JWKS for 10 minutes and refetches at most once a minute on an unknown `kid` (D05).

## Not covered here
Compose import mount, hiding the admin console and `/realms/master` (D43), SMTP settings for dev/prod, production password blacklist, realm backup, Keycloak upgrade procedure.
