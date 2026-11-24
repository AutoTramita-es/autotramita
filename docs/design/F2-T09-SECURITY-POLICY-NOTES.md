# F2-T09 — Security policies: notes for CP09

Date: 2026-11-24 | Package: F2-T09 (only) | Status: implemented, awaiting owner acceptance of CP09

> **REC update (2026-11-24):** D37, token minimisation and session-revocation notices have since been implemented; the older proposal, status and deviation rows below are historical. Reset detection changed: the marker keeps the earliest request and the handled password change, a sign-in older than the new password is refused (web asks for the password again, mobile answers `SESSION_REVOKED`), and mobile sign-in performs the same check. The 60 s worker also checks pending resets and ends older sessions without a sign-in (F-0 a). Passkey registration is disabled in the realm (F-1 b). Current evidence and limitations: [CP09 reconciliation](F2-CP09-RECONCILIATION-REPORT.md). CP09 has not been accepted.

## 1. What exists

| Area | Where | Behaviour |
|---|---|---|
| Admin client | `app/auth/idp_admin.py` (port in `app/auth/idp.py`) | Service account `at-admin-svc` (client credentials, token cached until 20 s before expiry); find user by exact e-mail, enable/disable, end sessions, `execute-actions-email`, list/delete credentials. One error type, never a response body or secret in messages or logs. |
| Recovery (D20) | `POST /auth/password-recovery`, `app/auth/security/recovery.py` | Always `202 {"status":"accepted"}`. Before answering: only the Redis checks (10/h per IP → `429`; 3/h per account by HMAC of the normalised e-mail, silent when exceeded; Redis down → `503`). After answering (background): Keycloak look-up, mail (`UPDATE_PASSWORD`, link 30 min, single use), audit. Disabled/deactivated/blocked/unknown accounts get nothing. |
| Reset detection | `app/auth/security/markers.py`, `recovery.after_sign_in` | A Redis marker (24 h) records when the mail was sent. At the next sign-in the password credential's creation time is compared with it; if the password really changed, all other sessions are ended (`PASSWORD_CHANGED`), audit + notice. Provider outage: sign-in is not blocked, the marker stays and the check repeats. |
| Verification resend | `POST /me/email-verification` | Always `202`; sends `VERIFY_EMAIL` only to unverified accounts, 3/h per account. |
| Password change / MFA enrolment (D23, D37) | `POST /me/security/{password-change,mfa-enrollment}-requests` → Keycloak `kc_action` → callback | Needs a fresh authentication (≤ 10 min). The callback does not trust `kc_action_status`: it asks Keycloak for a credential created after the flow started. Only then: other sessions ended and credential rotated (password), audit, notice. |
| Second factors | `GET /me/security`, `DELETE /me/security/second-factors/{id}` | Overview without secrets. Removal needs LoA2 within 10 min, only the caller's own non-password credentials, audit + notice. |
| Notices (D27) | `app/auth/security/notify.py` | Port + Spanish templates (kind and UTC time only: no address, link, token or identifier) + SMTP sender. Default `AUTH_NOTIFY_MODE=disabled`: nothing is sent in production until O15. |
| Realm | `identity/keycloak/realm-template.json` | `at-web` also accepts `<web origin>/` as redirect target (where Keycloak's "back to application" link of a recovery mail leads). Regenerated `realm-{dev,prod,test}.json`. |
| Config | `app/core/config.py`, `app/auth/settings.py` | `RateLimitSettings` now says the application enforces the recovery limit (AC-POL-14). New: `AUTH_ADMIN_CLIENT_SECRET`, `AUTH_SECURITY_HMAC_KEY`, `AUTH_RECOVERY_LINK_MINUTES`, `AUTH_NOTIFY_MODE`, `AUTH_SMTP_*`. |

## 2. Spike outcomes against the implementation

| Spike | Outcome in T09 |
|---|---|
| S2 / D20 | Confirmed and used: recovery is app-owned; `resetPasswordAllowed=false` stays. The reset link was shown single-use and 30 min (test `test_the_recovery_link_works_once`). |
| S3 / D23 | Step-up and "no MFA forced" re-confirmed through the application (enrolment, LoA2 step-up, removal). |
| S4 / D41 | **Recovery codes work end to end on Keycloak 26.4.7** (`test_recovery_codes_can_be_enrolled_through_keycloak_d41`), enrolled through `kc_action=CONFIGURE_RECOVERY_AUTHN_CODES`. Keycloak's feature status (preview/supported) is not asserted; the test would fail if a Keycloak upgrade removed it. |
| S9 | `UPDATE_PASSWORD` and `CONFIGURE_TOTP` through `kc_action` work with the application's callback. `UPDATE_EMAIL` stays unavailable (see §4). |

## 3. Acceptance criteria

| ID | Status | Evidence |
|---|---|---|
| AC-POL-01, 02 | PASS (T01) | `test_s01_…` (5 failures lock, identical message) |
| AC-POL-03 | PASS | fake-IdP and Keycloak tests: 3 mails per hour, fourth silent and identical; per-IP limit |
| AC-POL-04 | PASS (state/body/headers); timing by construction | identical answers for active, unknown, disabled, deactivated; a test proves no account-dependent call happens before the answer (look-ups run after the response) |
| AC-POL-05 | PASS | single-use link; reset ends other sessions at the next sign-in + notice |
| AC-POL-06 | PASS for password and second factors; **e-mail change not implemented (D37 gate, §4)** | `kc_action` tests, step-up tests |
| AC-POL-07 | PASS (T01) | `test_s10_…` |
| AC-POL-08 | PASS | `test_s03_…`; enrolment through the application needs no MFA beforehand |
| AC-POL-09 | **Cannot be proven before T10** (no platform grants yet). The guard `require_step_up(LOA2)` exists and is proven; T10 must apply it to every platform route. |
| AC-POL-10 | PASS for the T09 actions | fresh (LoA1, 10 min) for password/MFA enrolment; LoA2 for factor removal |
| AC-POL-11 | PASS | content test (no address, link, identifier); SMTP delivery to a sink; production default sends nothing |
| AC-POL-12 | PASS (T06/T07 tests: state/nonce/`jti`); Idempotency-Key not used (accepted deviation since CP07) |
| AC-POL-13 | by reference | SES/MOB tests |
| AC-POL-14 | PASS | `RateLimitSettings` docstring test |

## 4. D37 — e-mail change: proposal that needs your confirmation (not implemented)

Problem (from the T01 report): with `registrationEmailAsUsername`, changing the address in Keycloak also changes the login name *before* the new address is verified, so a typo or an attacker-controlled address would lock the person out or take the name.

**Proposal (app-owned, no unverified login name ever exists):**
1. `POST /me/security/email-change-requests {new_email}` — needs a fresh authentication (≤ 10 min); limit 3/h per person. Always `202`. If the new address is free in Keycloak and not used by another account, the application stores a pending change in Redis (HMAC of the new address, subject, 30 min) and sends **its own** confirmation mail with a one-time signed token to the **new** address; otherwise nothing is sent (no enumeration).
2. `POST /auth/email-change-confirmations {token}` (public, one-time, 30 min) — on success the admin API sets the new e-mail **and** username with `emailVerified=true`, the application updates `users.email`, all other sessions are ended, the old address gets a notice (`EMAIL_CHANGED`), audit `identity.email.changed`.
3. Until confirmation nothing changes in Keycloak: the old address keeps working; an abandoned request simply expires.

Alternative considered: keep Keycloak's own `VERIFY_EMAIL` after setting the new address with `emailVerified=false` (original D37 text). Rejected because the login name changes before verification.

Needs: your confirmation of this detail, then it can be implemented inside T09 (or you may move it to a later package). Until then `identity.email.changed` is only produced by the existing sync-at-login path (T04).

## 5. Deviations and limits (for CP09)

1. **E-mail change not implemented** pending §4 (as required by D37).
2. **Reset detection happens at the next sign-in**, not at the moment of the reset: between the reset and that sign-in a stolen session stays valid. The Keycloak event consumer (T11) closes this gap; until then it is bounded by session lifetimes.
3. **Recovery request notice**: Keycloak's own mail is the notice of a requested recovery; no second mail is sent (D27 lists it, redundant).
4. **New-sign-in-from-new-country notice** (D24/D27 soft binding) is not implemented: it needs a geo source that has not been decided. Account-blocked/deactivated notices belong to T11 (administrative actions).
5. **Token minimisation** (remove `profile`/`roles` scopes) and first/last-name handling stay PROPOSED: not applied (no owner decision; the login path does not depend on them).
6. Notices for "other/all sessions signed out" (D27) are not wired to the session endpoints yet; the template exists (`SESSIONS_REVOKED`).
7. A revoked-session audit record carries the reason code `CREDENTIAL_CHANGED` where the session row says `PASSWORD_CHANGED`: the audit guard rejects the word "password" in any detail.
8. The background work uses FastAPI background tasks (in-process): a crash between answer and mail loses that mail; the person simply asks again. The durable outbox arrives with T11.
