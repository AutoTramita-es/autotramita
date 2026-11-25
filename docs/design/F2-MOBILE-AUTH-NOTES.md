# F2 — Mobile authentication: notes for the Flutter client (F2-T07)

Status: implementation notes for AC-MOB-08; the Flutter app itself is outside F2 (AT-18).
Contract: [OpenAPI](../../openapi/openapi.json) · [AT-02 §6.5](../specifications/AT-02-identity-security.md) · decision D04 (model A).

## 1. How sign-in works
1. **Sign in with Keycloak** (realm `autotramita-<env>`, client `at-mobile`, public client) using authorization code with
   **PKCE S256 in the system browser** (Custom Tab / ASWebAuthenticationSession). No embedded WebView, no password
   handling in the app, no direct-access grant.
2. **Redirect URI:** a claimed https link (Android App Links / iOS Universal Links), registered exactly in the realm
   (`https://<origin>/app/auth/callback`). A custom URL scheme is a fallback only; wildcards are never registered.
3. **Open the application session:** call `POST /api/v1/auth/mobile/session` with `Authorization: Bearer <access token>`
   and a body such as `{"device": {"label": "Ana's phone", "platform": "android", "app_version": "1.4.2"}}`.
   `201` = created, `200` = the live session of this Keycloak session (safe to repeat). Unknown fields are refused with
   `422`: never send a refresh token or any other token in the body.
4. **Call the API** with the bearer token. Every request is checked against the application session (`sid` of the token),
   so a revoked session fails immediately even though the token is still valid for a few minutes.

## 2. Tokens on the device
- Access token lifetime is 5 minutes; refresh tokens rotate and a reused refresh token ends the whole Keycloak session
  (verified in the Keycloak spike). Refresh **directly with Keycloak**; the application never sees a refresh token.
- Store tokens only in **Android Keystore-backed storage / iOS Keychain** (e.g. `flutter_secure_storage` with
  `encryptedSharedPreferences` / `first_unlock_this_device`). Never in SharedPreferences/UserDefaults, logs, crash
  reports, analytics or backups (set `android:allowBackup="false"` or exclude the secure store).
- Do not copy tokens into Dart `print`/`debugPrint` or HTTP-logging interceptors.

## 3. Errors the client must handle (all `application/problem+json`)
| Status / `code` | Meaning | What the app does |
|---|---|---|
| 401 `AUTH_TOKEN_INVALID` | token invalid or expired | refresh with Keycloak, retry once; if that fails, sign in again |
| 401 `SESSION_REQUIRED` | valid token, no application session | call `POST /auth/mobile/session` |
| 401 `SESSION_REVOKED` | the session was ended (here or elsewhere), or this Keycloak sign-in is older than a password or e-mail change | **sign in again with `prompt=login`** (a silent single sign-on is refused again); do not retry `POST /auth/mobile/session` with the same token |
| 401 `SESSION_EXPIRED` | idle (7 days) or absolute (30 days) limit | call `POST /auth/mobile/session` (works while the Keycloak session lives) |
| 401 `STEP_UP_REQUIRED` | a sensitive action needs a fresh authentication; the challenge names `acr_values` (`loa2` whenever the person has a second factor, F-3) | re-authenticate with Keycloak with `prompt=login` and the named `acr_values`, then retry with the new token. A refresh does not help: the window (10 min) counts from the authentication, for `loa2` from the `loa_map` claim (F-2) |
| 403 `ACCOUNT_DISABLED` | account blocked or deactivated | show the generic message; no retry |
| 403 `EMAIL_NOT_VERIFIED` (later routes) | e-mail not verified | send the person to verify |
| 429 / 503 | limits / dependency down | back off using `Retry-After` |

## 4. Session management for the person
`GET /sessions` lists their sessions (at most ten), `DELETE /sessions/{id}` ends one, `POST /sessions/revoke-others` ends all
but the current one, `POST /sessions/revoke-all` ends everything and needs a token whose `auth_time` is within ten minutes.

## 5. Known limits (deliberate in F2)
- Revoking a session in the application does not yet end the Keycloak session (the outbox that does so arrives with F2-T11);
  the revoked session stays refused, so the device has to sign in again.
- Keycloak back-channel logout is wired for the web and mobile clients; the signed mobile logout token
  revokes the application session by subject and session ID (isolated Keycloak CI test).
- User-agent changes are **not** treated as theft for mobile sessions (app updates change the agent); refresh-token reuse
  detection in Keycloak is the signal there.
- Refresh-token reuse ends the token family in Keycloak but the application is not told (no back-channel logout): the
  `REFRESH_REUSE` reason arrives with the T11 event ingestion.
- Dart/Flutter compilation of the generated client is still deferred (finding R10).
