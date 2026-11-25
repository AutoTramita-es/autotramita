# F2-T01 — Keycloak spike report (S1–S10)

Datum: 2026-11-24 | Paket: F2-T01 | Status: **F2-CP01 PRIHVAĆEN 2026-11-24 (D37 izmijenjen)** | Kod: `identity/`, `scripts/identity/`, `tests/identity/`
**Dokaz:** commit `8599382a37f0ab42f85962f925925662b6c54c87` na `dev`, CI run [45454710907](https://github.com/AutoTramita-es/autotramita/actions/runs/45454710907): sva četiri joba uspješna. Keycloak job: **11 passed, 0 skipped, 0 failed** (Keycloak 26.4.7 po digestu `sha256:9409c59b…`, jednokratni container, `-W error`). Glavni job (PG16/Redis7) i postojeći F1 testovi nepromijenjeni i zeleni. Ništa nije pokrenuto na zajedničkoj infrastrukturi.

> **REC evidence (2026-11-24, CI run [45504609210](https://github.com/AutoTramita-es/autotramita/actions/runs/45504609210), Keycloak 26.4.7):**
> - S1: lock expiry proven with a 5 s window (the committed 15 min were not waited).
> - S2: the direct reset URL is denied while the option is off.
> - S3: `max_age=0` forces a password; LoA2 asks again after its `loa-max-age` (shortened to 5 s; committed 600 s asserted); removing OTP needs LoA2 on Keycloak's own pages and account API. **WebAuthn:** enrolment works when the action is on, but the flow does not use it for LoA2 — a passkey-only account is offered OTP setup after the password alone; both registration actions are therefore **disabled** (owner decision F-1 b, run [45509883690](https://github.com/AutoTramita-es/autotramita/actions/runs/45509883690)). A recovery-codes-only account behaves the same way (open finding F-1R).
> - S6: reuse of a refresh token is refused; Keycloak sends **no** back-channel logout and the user session remains.
> - Password reset sends a back-channel logout only if “Sign out from other devices” is ticked (not preselected). Otherwise the application's 60 s check ends the old sessions (owner decision F-0 a, same run as above).
> - The e-mail address is read-only for the person (profile page and account API).
> - Mobile back-channel logout, optional names, minimized tokens and separate DEV/PROD imports pass.
>
> **Update (2026-11-25, CI run [45527442553](https://github.com/AutoTramita-es/autotramita/actions/runs/45527442553)):** the level-two flow now proves one-time codes, passkeys and recovery codes (the WebAuthn and recovery-code findings above are superseded). `UpdatePassword` is not a credential action, so no level setting protects Keycloak's password form; a pending required action is served after a password-only sign-in ([CP09 report §2](F2-CP09-RECONCILIATION-REPORT.md#2-owner-decision-needed)). `auth_time` moves on a password sign-in; the session note `loa-map` records when each level was really proven.
>
> The table below is the historical T01 result.

## Rezultati
| ID | Tvrdnja | Ishod | Dokaz i granice |
|---|---|---|---|
| S1 | Brute-force 5 neuspjelih/15 min; ne otkriva zaključavanje | **POTVRĐENO** | 4 neuspjela pokušaja ne zaključavaju; 5. zaključava (ispravna lozinka odbijena, admin status `disabled=true`); poruka za zaključan i pogrešnu lozinku identična („invalid username or password"). Postavke pročitane iz realma (5, 900 s, bez trajnog zaključavanja). **Nije testirano:** istek prozora/zaključavanja čekanjem 15 min |
| S2 | Nema nativnog limita oporavka po računu | **POTVRĐENO** (D20 opravdan) | Uz uključen `resetPasswordAllowed` 5 zahtjeva za isti račun → 5 e-mailova. Uz `false` login stranica nema poveznicu za oporavak. Admin `execute-actions-email` (`UPDATE_PASSWORD`) radi s service accountom, rok 1799 s ≈ 30 min. **Nije testirano:** izravni poziv URL-a `reset-credentials` uz isključenu opciju (ide u T09) |
| S3 | Step-up LoA; MFA opcionalan | **POTVRĐENO** | `acr_values=loa1`: prijava samo lozinkom, token `acr=loa1`; `loa2` u istoj SSO sesiji traži postavljanje OTP-a, nakon TOTP koda `acr=loa2`. Vrijednost `acr` je **ime** iz LoA mape (`loa1/loa2`), ne broj. **Nije testirano:** ponovni zahtjev nakon `loa-max-age` (600 s), `max_age`, WebAuthn |
| S4 | Recovery kodovi dostupni | **POTVRĐENO (dostupnost)** | Authenticator `auth-recovery-authn-code-form` i required action `CONFIGURE_RECOVERY_AUTHN_CODES` uključeni na zadanoj konfiguraciji 26.4.7. **Nije testiran cijeli tok** niti status (preview/supported) → T09 |
| S5 | Backchannel logout; `sid` | **POTVRĐENO** | `sid` u ID i access tokenu (isti); `aud` ∋ `at-api`, `azp=at-web`, `typ=Bearer`; admin odjava šalje `logout_token` s `events` backchannel-logout, `jti`, bez `nonce`, ispravni `iss`/`aud`/`sid`. Jednokratnost `jti` je aplikacijska (T06) |
| S6 | Rotacija i reuse detection (javni klijent) | **POTVRĐENO** | Refresh daje novi token; ponovna uporaba starog → 400 `invalid_grant`; nakon toga i najnoviji token 400 (obitelj poništena) |
| S7 | Uvoz s `${ENV}` tajnama; najmanje ovlasti | **POTVRĐENO** | Secret iz okoline radi, krivi → 401. Service account: `users` i `events` čita; **ne može** mijenjati realm ni kreirati klijente (403). Čitanje realma je dopušteno (svaka realm-management uloga to omogućuje). PKCE S256 je **provođen**: zahtjev bez `code_challenge` odbijen |
| S8 | Događaji i admin događaji | **POTVRĐENO** | `LOGIN_ERROR` ima `ipAddress`, `userId`, `clientId`, `error`, bez lozinke; admin događaji bez `representation`; paginacija radi |
| S9 | Application-initiated actions | **DJELOMIČNO** | `UPDATE_PASSWORD`: uspjeh vraća `kc_action_status=success`. `CONFIGURE_TOTP`: stranica se prikazuje. **`UPDATE_EMAIL` je isključen** (required action `enabled=false`, nije ponuđen) |
| S10 | Politika lozinke | **POTVRĐENO** | Dostupni `length`, `notUsername`, `notEmail`, `passwordBlacklist`; kratka i blacklistana lozinka odbijene (400), dobra prolazi. Produkcijska lista je deployment artefakt |
| KC05 | Rotacija ključa | **POTVRĐENO** | Novi ključ višeg prioriteta: novi tokeni nose novi `kid`, stari ostaje u JWKS-u |

## Nalazi izvan S1–S10
1. **Korisnički profil traži ime i prezime** (zadani declarative user profile). Aplikacija ih ne treba (D36: `display_name` opcionalan). Prijedlog: ostaviti, ne pohranjivati; ili ublažiti profil u realmu.
2. **Access token nosi osobne podatke i uloge**: `email`, `name`, `given_name`, `family_name`, `preferred_username`, `realm_access`, `resource_access`. Aplikacija ih **ne koristi** za autorizaciju (I02), ali bearer token koji mobilni klijent drži sadrži PII. Prijedlog: ukloniti `profile`/`roles` scope s klijenata (minimizacija) u T02/T09.
3. Keycloak postavlja kolačiće `Secure` i na http loopbacku; samo testni harness to zaobilazi (vlastiti jar). Ne utječe na produkciju (https).
4. Ugrađeni service account vidi realm (read); to je ograničenje Keycloaka, ne konfiguracije.

## Utjecaj na odluke (za F2-CP01)
| Odluka | Posljedica | Prijedlog (PROPOSED, čeka vlasnika) |
|---|---|---|
| **D37** promjena e-maila preko `UPDATE_EMAIL` | **Ne radi na zadanoj konfiguraciji.** Uključivanje značajke (`--features`) mijenja serverske argumente i status značajke nije provjeren | Ne ovisiti o njoj. Promjena e-maila: aplikacijski tok (step-up → admin API postavlja novu adresu s `emailVerified=false` → `VERIFY_EMAIL` na novu adresu → obavijest na staru). Zahtijeva izmjenu D37 |
| D19, D20, D22 (LoA), D23, D24, D25, D32, D21 | Potvrđene uz navedene granice | Bez izmjene |
| D41 | Recovery kodovi dostupni, tok netestiran | T09 dokazuje prije oslanjanja |
| Minimizacija tokena | Nova stavka (nalaz 2) | Dodati u T02 (validator ignorira) i T09 (realm) |
Pokazano je i **ograničenje dokaza**: realmovi `dev` i `prod` nisu uvezeni u Keycloak; od test realma se razlikuju samo URL-ovima, `sslRequired` i SMTP-om, što jamče linter i drift test (41+ testova bez Keycloaka).

## Isporučeno
`identity/keycloak/realm-template.json` + generirani `realm-{dev,prod,test}.json`; renderer `scripts/identity/render_realms.py`; linter `tests/identity/realm_lint.py` (22 negativna slučaja); testovi okruženja (digest, bez trajnog stanja, samo test realm u CI); `identity/docker-compose.keycloak-test.yml`; CI job `identity`; [identity/README.md](../../identity/README.md) (rad, tajne, rotacija ključeva). Test `tests/test_ci_workflow.py` ažuriran za četvrti job (3 → 4 timeouta, 3 setup-uv).

## Odluka vlasnika (CP01)
CP01 prihvaćen; D37 izmijenjen prema prijedlogu. Minimizacija tokena i ime/prezime ostaju prijedlozi za T09 (nisu izričito prihvaćeni). Autoriziran samo F2-T02.
