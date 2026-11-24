# AT-02 — Identitet, autentifikacija i sigurnost (F2) + minimalni AT-17

Verzija 0.1 | 2026-11-24 | Status: **PROPOSED — za pregled vlasnika (F2-CP00)**. Nije autorizacija implementacije, migracija, infrastrukture ni deploymenta.
Odluke: [F2 registar odluka](../design/F2-DECISION-REGISTER.md) (ID-evi I01–I20 naslijeđeni ACCEPTED, D01–D43 PROPOSED). Plan: [F2-IMPLEMENTATION-PLAN](../design/F2-IMPLEMENTATION-PLAN.md) · [Execution order](../design/F2-EXECUTION-ORDER.md) · [Kriteriji](../design/F2-ACCEPTANCE-CRITERIA.md).

## 1. Izvori i prvenstvo
Obvezujući (prvenstvo redom): ADR-010, ADR-003, ADR-002, ADR-004, ADR-009, ADR-008, ADR-001; [AT-01 v1.1 §5–7, §10a](AT-01-foundation-infrastructure.md); [G6](../G6-EXECUTION-ORDER.md) (F2 okvir, 6a); [AT-03 potvrđene odluke](AT-03-decisions.md) (#12, #18–#21, #24); [FOUNDATION-G5-REVIEW](../design/FOUNDATION-G5-REVIEW.md) (G5-02, 04, 05, 06; H1–H6 odobreni); [F1 završni dokazi](../design/F1-FINAL-ACCEPTANCE-EVIDENCE.md). Informativno (PROPOSED, ne obvezuje): [AT-03 završni prijedlog](AT-03-final-design.md), [AT-04](AT-04-customers-vehicle-owners.md).
Ova specifikacija ne mijenja prihvaćene ADR-ove. Gdje se razlikuje od formulacije prihvaćenog dokumenta, razlika je izričito označena (D17 F1-amandman, D20 oporavak lozinke) i čeka odobrenje.

## 2. Svrha, akteri, granice
**Svrha:** dokazivo ispravna autentifikacija (Keycloak), globalni identitet, aplikacijski upravljane sesije s trenutačnim opozivom, minimalne platformske ovlasti, audit sigurnosnih događaja, API ugovori i testovi za sve navedeno — bez ijednog poslovnog modula.
**Akteri:** posjetitelj (neautenticiran), korisnik (verificirani globalni identitet), korisnik s platformskim grantom (centralni administrator/verifikator), sustav (worker, Keycloak događaji), infrastrukturni administrator (bootstrap, izvan aplikacije).
**Izvan F2** (ostaje u kasnijim fazama): AT-03 (članstva, tenanti, poslovnice, pozivnice, verifikacija autokuća), CRM/klijenti, vozila, predmeti, financije, produkcijski Nextcloud i mail server, korisničko sučelje, deployment. F2 samo priprema granice (§6.8, §9.5).

## 3. Arhitektura u cjelini
```
Preglednik (Next.js)        Mobilni (Flutter)
 kolačić __Host-at_session   Authorization: Bearer <KC access token>
 + X-CSRF-Token (nesigurne)  (code + PKCE, sustavni preglednik)
        │ isti origin /api/v1        │ api.autotramita.es/api/v1
        ▼                             ▼
  ┌──────────── FastAPI: auth pipeline ─────────────┐   OIDC    ┌──────────┐
  │ rate limit(IP) → vjerodajnica → CSRF → JWT (mob)│◄─────────►│ Keycloak │ realm po okruženju
  │ → bootstrap kontekst → user_sessions + users     │ admin API │ (auth.)  │ vlastita baza
  │ → MembershipAuthorizer (port) → RequestContext   │──────────►└──────────┘
  │ → route autorizacija (user / workspace / grant / │             ▲ events (poll)
  │   step-up) → session_scope (F1, RLS, FORCE)      │             │
  └───────────────┬──────────────────────────────────┘      identity_outbox ─► Celery worker
                  ▼
        PostgreSQL 16: users · user_sessions · platform_grants · audit_events · identity_outbox
        (app / worker / platform role; owner samo migracije)        Redis: limiteri, state/nonce, jti
```
Načela: Keycloak dokazuje **tko je osoba**; aplikacija odlučuje **što smije** i **je li sesija još živa**. Nijedna autorizacijska činjenica (tenant, poslovnica, uloga, platformski grant, status računa) ne dolazi iz tokena ni kolačića; svaka se čita iz baze na svakom zahtjevu (I02, I04, I17).

## 4. F2.01 — Keycloak

### 4.1 Okruženja
| | DEV | PROD |
|---|---|---|
| Realm | `autotramita-dev` | `autotramita-prod` |
| Host | `auth.dev.autotramita.es` | `auth.autotramita.es` |
| Baza | `autotramita_keycloak_dev` | `autotramita_keycloak_prod` |
| Kod konfiguracije | `identity/keycloak/realm-dev.json` | `identity/keycloak/realm-prod.json` |
Isti izvor (zajednički predložak realma + preklapanje po okruženju). Nema dijeljenja realma, tajni, klijenata ni baze (I01). Image `quay.io/keycloak/keycloak:26.4.7` kako je pripijen u Composeu. Compose/Traefik se u F2 **ne mijenjaju** (uvoz realma, skrivanje admin konzole — D43 — su live preduvjet uz zasebnu autorizaciju).

### 4.2 Klijenti (D02)
| Klijent | Tip | Tok | Napomene |
|---|---|---|---|
| `at-web` | confidential | Authorization Code + PKCE S256 (BFF) | točni redirect URI (`https://<origin>/api/v1/auth/callback`), bez wildcarda; post-logout URI točni; backchannel logout URL; tajna iz okoline |
| `at-mobile` | public | Authorization Code + PKCE S256, sustavni preglednik | claimed https redirect (App Links/Universal Links) ili registrirana shema; nema embedded WebView; refresh rotacija |
| `at-admin-svc` | confidential, service account | client credentials | uloge samo: `manage-users` (omogući/onemogući, execute-actions-email), `view-users`, `view-events`, `manage-events` isključeno; nikad izložen klijentima |
Za sve: implicit isključen, direct access grants isključen, audience mapper `at-api`, `sid` u tokenima, bez prilagođenih claimova za tenant/ulogu.

### 4.3 Validacija tokena (D05)
Obavezno: potpis prema JWKS-u realma (cache 10 min, refetch na nepoznat `kid` ≤ 1×/min); algoritam ∈ {RS256, ES256}; `iss` = točan issuer okruženja; `aud` ∋ `at-api`; `azp` ∈ {`at-mobile`}; `typ=Bearer`; `exp`, `nbf` (tolerancija 30 s); `sub` i `sid` prisutni. Neuspjeh → 401 `AUTH_TOKEN_INVALID` (generička poruka), audit bez tokena. Token valjan, ali bez sesije → 401 `SESSION_REQUIRED` (klijent poziva `POST /auth/mobile/session`).
Web nikad ne prima Keycloak tokene u preglednik; ID token se validira jednom u callbacku (potpis, `iss`, `aud`=`at-web`, `nonce`, `exp`, `auth_time`, `acr`/`amr`).

### 4.4 Ključevi i rotacija (D06)
Realm ključ RS256 s prioritetom; rotacija svakih 90 dana ili odmah pri kompromitaciji: dodati novi ključ višeg prioriteta → stari pasivan ≥ 14 dana → ukloniti. Aplikacija ne drži privatne ključeve Keycloaka. Runbook je dio F2-T01 dokumentacije; izvedba rotacije se vježba u CI okruženju (test: token potpisan starim, zatim novim ključem prolazi; nepoznat `kid` ne ruši servis).

### 4.5 Lokalno i CI okruženje (D07)
1. **Jedinično:** lažni IdP (lokalni RSA par, JWKS, generator tokena s kontroliranim claimovima) — brz, bez mreže.
2. **Integracijsko:** Keycloak 26.4.7 service container (digest pin) s uvezenim `realm-test.json` u CI-u; lokalno jednokratni `identity/docker-compose.keycloak-test.yml` s izbacivim volumenom. Nikad zajednički Keycloak, nikad stvarni podaci.
3. Realm linter test (bez Keycloaka): zabranjeni wildcard redirect, direct grants, implicit, javni klijent s tajnom, tajna u JSON-u, `registrationEmailAsUsername` nedosljedan, brute-force parametri, `resetPasswordAllowed=false`, `verifyEmail=true`.

## 5. F2.02 — Globalni korisnički identitet

### 5.1 Model `users` (D10, D36)
| Stupac | Tip / pravilo |
|---|---|
| `id` | uuid PK (`gen_random_uuid()`) |
| `auth_subject` | text NOT NULL **UNIQUE**, nepromjenjiv (trigger) — Keycloak `sub` |
| `email`, `email_normalized` | text NOT NULL; normalizacija NFKC + trim + lower; **UNIQUE** na `email_normalized` |
| `email_verified_at` | timestamptz NULL |
| `status` | `PENDING_VERIFICATION` · `ACTIVE` · `DEACTIVATED` · `BLOCKED` (CHECK) |
| `status_reason`, `status_changed_at`, `status_changed_by` | kod razloga (enum), vrijeme, uuid aktera (bez FK) |
| `display_name`, `preferred_language` | opcionalno; default `es` |
| `last_login_at`, `created_at`, `updated_at`, `version` | `version` za If-Match (F1 versioning) |
Ograničenja: `status='ACTIVE'` ⇒ `email_verified_at IS NOT NULL`; nema `tenant_id`, `customer_id`, uloga ni članstava. Rezervirano za AT-20: `ANONYMISED`.
**Matrica prijelaza** (trigger, ostalo odbijeno): PENDING→ACTIVE (verifikacija), PENDING→BLOCKED, ACTIVE→DEACTIVATED, ACTIVE→BLOCKED, DEACTIVATED→ACTIVE, DEACTIVATED→BLOCKED, BLOCKED→ACTIVE (samo platformska ovlast `PLATFORM_USER_ADMIN`), BLOCKED→DEACTIVATED.
**RLS** (ENABLE + FORCE): app rola vidi/ažurira redak `id = app_user_id()` ili `auth_subject = app_auth_subject()` (bootstrap, D17); INSERT samo uz `auth_subject = app_auth_subject()` i status ∈ {PENDING, ACTIVE}; promjena `status` i polja `status_*` dopuštena samo platform roli s grantom ili sustavnom (worker) kontekstu; platform rola čita po grantu `PLATFORM_USER_ADMIN`. Column-level GRANT: app rola ne može `UPDATE status`.

### 5.2 Povezivanje s Keycloakom i sprječavanje duplikata (D09)
Callback: ID token → `sub`. (a) postoji redak po `sub` → koristi ga; (b) ne postoji, a `email_normalized` već pripada **drugom** `sub` → odbij prijavu (`ACCOUNT_CONFLICT`, generička poruka), audit `identity.link.conflict`, upozorenje administratorima; nikad automatsko spajanje; (c) ne postoji → INSERT (status ACTIVE ako je `email_verified=true` u tokenu, inače PENDING_VERIFICATION). Paralelni prvi login istog `sub` → UNIQUE + `ON CONFLICT DO NOTHING` + ponovno čitanje (idempotentno). Promjena e-maila u Keycloaku sinkronizira se kroz callback/event i ponovno prolazi provjeru jedinstvenosti.

### 5.3 Registracija i verifikacija e-maila (D08)
Keycloak hostira registraciju i verifikaciju (`verifyEmail`, jednokratni link, rok 24 h — predloženo). Do verifikacije status je `PENDING_VERIFICATION` i API vraća 403 `EMAIL_NOT_VERIFIED` za sve osim `GET /me`, `POST /me/email-verification`, `POST /auth/logout`. Ponovno slanje: generički 202, 3/h/račun. Verificirani e-mail iz tokena (`email_verified=true`) prelazi status u ACTIVE i upisuje `email_verified_at` (audit).

### 5.4 Životni ciklus računa (D10, D11)
Aktivacija: verifikacija e-maila. **Deaktivacija** i **blokiranje** (platformska radnja uz `PLATFORM_USER_ADMIN`, step-up, razlog obvezan): u **jednoj transakciji** (1) `FOR UPDATE` na `users` redak, (2) promjena statusa, (3) opoziv svih `user_sessions` (razlog `ACCOUNT_DEACTIVATED`/`ACCOUNT_BLOCKED`), (4) `audit_events`, (5) `identity_outbox` (onemogući u Keycloaku + odjavi KC sesije + obavijest). Pristup prestaje odmah; Keycloak sinkronizacija je naknadna i ponovljiva. Prijava korisnika sa statusom ≠ ACTIVE ne stvara sesiju (403 `ACCOUNT_DISABLED` tek nakon uspješne autentifikacije u Keycloaku). Reaktivacija: ACTIVE + Keycloak `enabled=true` kroz outbox. Samostalno brisanje/anonimizacija računa: AT-20.

### 5.5 Odvajanje identiteta (matrica)
| Pojam | Gdje živi | Veza s `users` |
|---|---|---|
| Globalni login | `users` (F2) | — |
| Klijent (Customer) | tenant CRM, AT-04 | `customers.user_id` opcionalan FK **na** `users`; `users` ne zna za klijente |
| Vlasnik vozila | AT-05 | Nema; vlasništvo je činjenica o vozilu, ne o računu |
| Članstvo / uloga u tenantu | `tenant_memberships`, AT-03 | `tenant_memberships.user_id` FK **na** `users`; `users` ne nosi ulogu |
| Platformska ovlast | `platform_grants`, F2 | `platform_grants.user_id`; ne nasljeđuje se iz tenant uloga |
Isti `users` redak može biti istodobno klijent jedne autokuće, zaposlenik druge i imati platformski grant, bez dijeljenja ovlasti (ADR-003).

## 6. F2.03 — Upravljanje sesijama

### 6.1 Model `user_sessions` (D12, D15)
| Stupac | Opis |
|---|---|
| `id` | uuid PK (javni identifikator za popis/opoziv; **nije** tajna) |
| `user_id` | FK `users`, NOT NULL |
| `client_type` | `WEB` · `ADMIN_WEB` · `MOBILE` |
| `credential_hash` | bytea UNIQUE, SHA-256 tajne kolačića (samo WEB/ADMIN_WEB); tajna nikad u bazi |
| `kc_session_id` | text — `sid` iz Keycloaka; UNIQUE (`kc_session_id`, `client_type`) |
| `active_tenant_id`, `active_branch_id`, `active_membership_id` | uuid NULL; **bez FK u F2** (tablice ne postoje), FK dodaje F3a |
| `context_version` | int — raste pri svakoj promjeni konteksta |
| `auth_time`, `auth_level` (`LOA1`/`LOA2`), `step_up_at` | stanje autentifikacije |
| `csrf_secret_hash` | bytea (WEB) |
| `device_label`, `platform`, `app_version`, `ua_family`, `ip_prefix`, `country_code` | uređaj i gruba lokacija (bez punog IP-a) |
| `created_at`, `last_activity_at`, `idle_expires_at`, `absolute_expires_at` | UTC |
| `revoked_at`, `revoked_reason`, `revoked_by` | razlozi: `LOGOUT`, `USER_REVOKED`, `IDLE_TIMEOUT`, `ABSOLUTE_TIMEOUT`, `PASSWORD_CHANGED`, `ACCOUNT_DEACTIVATED`, `ACCOUNT_BLOCKED`, `ADMIN_REVOKED`, `IDP_LOGOUT`, `MEMBERSHIP_REVOKED`, `SECURITY_POLICY`, `REPLAY_DETECTED`, `REFRESH_REUSE` |
| `version` | optimistic lock |
Sesija je **živa** kad `revoked_at IS NULL AND now() < idle_expires_at AND now() < absolute_expires_at`. Istek se računa pri čitanju (nema ovisnosti o cron-u za sigurnost); čišćenje starih redaka je zasebno i povlači retenciju (D42).
**RLS:** SELECT/UPDATE/INSERT vlastitih redaka (`user_id = app_user_id()`); bootstrap čitanje retka čiji je `credential_hash = app_session_hash()` (D17); platform rola po grantu `PLATFORM_USER_ADMIN` (SELECT, opoziv). Korisnik ne može izmijeniti `user_id`, `credential_hash` ni `absolute_expires_at` (column GRANT + trigger).

### 6.2 Validacija pri svakom zahtjevu (D16)
1. Rate limit (IP) → izvuci vjerodajnicu (kolačić **ili** bearer; oboje istodobno → 400 `AMBIGUOUS_CREDENTIALS`).
2. Kolačić + nesigurna metoda → CSRF provjera (§6.4). Bearer → validacija JWT (§4.3).
3. Transakcija: bootstrap kontekst (`app.session_hash` ili `app.auth_subject`) → pročitaj sesiju (`FOR SHARE` na mutirajućim zahtjevima) i `users` redak.
4. Odbij ako: sesija nepostojeća/opozvana/istekla (401 `SESSION_EXPIRED`/`SESSION_REVOKED`), korisnik ≠ ACTIVE (403 `ACCOUNT_DISABLED`), `ua_family` ≠ zabilježenoj (opoziv `SECURITY_POLICY` + 401), `kc_session_id` ne odgovara `sid` tokena.
5. `last_activity_at`/`idle_expires_at` produži najviše 1×/60 s.
6. Ako sesija ima `active_tenant_id`: `MembershipAuthorizer.resolve(...)` **svaki put** (§6.8); `None` → kontekst se čisti (sesija bez tenant konteksta), ne gradi se `RequestContext` s tenantom.
7. Postavi `RequestContext(user_id, tenant_id, branch_ids)` ponovnim `apply_context` u **istoj** transakciji; postavi `request.state.principal_id`/`tenant_id` (samo iz validiranog konteksta; limiter po korisniku i tenantu iz F1 koristi te vrijednosti).
8. Route razina: `require_user` · `require_workspace` · `require_platform_grant(tip, opseg)` · `require_step_up(max_age, level)`; zadano **deny**.
Nema cachea odluka. Opoziv se vidi na sljedećem zahtjevu; zahtjev u tijeku dovršava se najviše do kraja vlastite transakcije (opoziv `FOR UPDATE` čeka `FOR SHARE` mutirajućeg zahtjeva).

### 6.3 Web tok (BFF, D03, D12)
`GET /auth/login` generira `state`, `nonce`, PKCE verifier (Redis, ≤ 10 min, jednokratno; vezano uz privremeni potpisani kolačić) → 302 na Keycloak. `GET /auth/callback`: provjeri `state`, izmijeni code (back-channel, `at-web` tajna), validiraj ID token, odbaci tokene, nađi/izradi korisnika (§5.2), provjeri status, izradi `user_sessions` (nova vjerodajnica), `Set-Cookie`, 302 na `return_to` (**samo relativna putanja s allowlistom**, inače `/`). Kolačić: `__Host-at_session=<tajna>; Secure; HttpOnly; SameSite=Lax; Path=/` (bez `Domain`, bez `Max-Age` dulje od apsolutnog roka). Odjava: `POST /auth/logout` (CSRF) opoziva sesiju i vraća `end_session_url` za RP-initiated logout.
**Backchannel logout:** `POST /auth/oidc/backchannel-logout` (`logout_token`: potpis, `iss`, `aud`, `events`, bez `nonce`, `jti` jednokratan u Redisu) opoziva sve sesije s tim `sid`/korisnikom (razlog `IDP_LOGOUT`). Bez kolačića i CSRF-a, ali s validacijom tokena; odgovor uvijek 204/400 bez detalja.

### 6.4 CSRF (D14)
Sesija nosi `csrf_secret`; `GET /auth/session` vraća izvedeni token. Svaka nesigurna metoda s kolačićem zahtijeva `X-CSRF-Token` (usporedba konstantnog vremena) **i** `Origin` ∈ dopušteni originali (ili `Sec-Fetch-Site: same-origin`). Neuspjeh: 403 `CSRF_INVALID`, audit (`access.denied`). Bearer zahtjevi nisu podložni CSRF-u, ali **ne smiju** istodobno nositi kolačić sesije.

### 6.5 Mobilni tok (D04)
Flutter: Authorization Code + PKCE (S256) kroz sustavni preglednik prema `at-mobile`; tokeni se pohranjuju isključivo u Android Keystore / iOS Keychain (nikad SharedPreferences/UserDefaults, logovi, backup). API prima `Authorization: Bearer <access token>` (život 5 min). Prvi poziv `POST /auth/mobile/session` (idempotentan po (`sid`, klijent), Idempotency-Key): tijelo `device {label, platform, app_version}` → stvara/vraća `user_sessions`. Refresh tokene klijent koristi izravno prema Keycloaku; rotacija + reuse detection u Keycloaku (S6); **ponovna uporaba refresh tokena** → Keycloak poništava obitelj, API vidi nevaljan token, aplikacija opoziva sesiju (`REFRESH_REUSE`). Opoziv sesije (aplikacijski) + `identity_outbox` odjava KC sesije; i bez KC-a svaki sljedeći API poziv je odbijen jer `user_sessions` kaže `revoked`.

### 6.6 Aktivni tenant/poslovnica i promjena konteksta
`POST /sessions/workspace` `{tenant_id, branch_id}` (If-Match po `context_version`, Idempotency-Key): `MembershipAuthorizer.resolve(user_id, tenant_id, branch_id)` odlučuje; samo pri uspjehu upisuje `active_*` i povećava `context_version`; audit `session.context.changed` (staro→novo). Klijentski `tenant_id` je **zahtjev**, nikad autoritet. Nepoznat/nedopušten tenant → 404 `WORKSPACE_NOT_FOUND` (ne otkriva postojanje; I18/AT-03 #5). Svaka sesija ima vlastiti kontekst; promjena u jednoj ne dira druge (I09). U F2 produkcijska implementacija porta uvijek odbija (nema članstava); testni dvojnik omogućuje cjelovite testove.

### 6.7 Opoziv i istek
| Radnja | Endpoint | Autorizacija | Učinak |
|---|---|---|---|
| Vlastita sesija (odjava) | `POST /auth/logout` | sesija + CSRF | opoziva tekuću |
| Pojedinačna vlastita | `DELETE /sessions/{id}` | vlasnik | opoziva; 404 ako nije vlastita |
| Sve ostale vlastite | `POST /sessions/revoke-others` | vlasnik | opoziva sve osim tekuće |
| Sve vlastite | `POST /sessions/revoke-all` | vlasnik + step-up | uključuje tekuću |
| Pojedinačna/sve tuđe | `POST /platform/users/{id}/sessions/revoke` | grant `PLATFORM_USER_ADMIN`, LoA2 | razlog `ADMIN_REVOKED` |
| Promjena lozinke | KC `UPDATE_PASSWORD` završen | — | ostale sesije opozvane (I09 „može"; F2 provodi) |
| Deaktivacija/blokada | §5.4 | — | sve sesije, odmah |
| Opoziv članstva (AT-03) | događaj iz F3a | — | sesije s tim `active_membership_id` gube kontekst (`MEMBERSHIP_REVOKED`); ostale tenant sesije netaknute |
Opoziv članstva ili uloge djeluje bez događaja jer se članstvo čita na svakom zahtjevu; događaj služi samo za audit i obavijest.

### 6.8 Granica prema AT-03
```python
class Workspace(frozen dataclass): tenant_id: UUID; branch_id: UUID | None; membership_id: UUID; branch_ids: tuple[UUID, ...]
class MembershipAuthorizer(Protocol):
    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]: ...
    def resolve(self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None) -> Workspace | None: ...
```
Port se poziva u istoj transakciji s kontekstom `app.user_id` (korak 1 dvokoračnog konteksta iz G5-02; politika „vlastito članstvo SELECT" je odgovornost F3a). Pravila: `None` = nema pristupa; izuzeci se ne gutaju (greška porta → 503, fail closed). F2 testira: nepostojeći tenant, tuđi tenant, istek članstva usred sesije, promjena uloge, uklonjena poslovnica — preko dvojnika i probne tablice u testovima (F1 obrazac).

## 7. F2.04 — Sigurnosne politike

### 7.1 Matrica izvedivosti pravila
| Pravilo | Status | Gdje se provodi | Dokaz |
|---|---|---|---|
| 5 neuspjelih prijava / 15 min (I06) | Keycloak nativno (brute-force detection, po korisniku) | `failureFactor=5`, `maxDeltaTime=15 min`, privremeno zaključavanje | S1 + KC integracijski test (6. pokušaj odbijen, 5 nije) |
| Zaštita po IP-u | **Nije** nativno po IP-u u Keycloaku | Redis limiter na rute prijave + Traefik (live) | F1 limiter test + 429 |
| 3 oporavka lozinke / h / račun (I06) | **Nije** nativno (D20) | Aplikacijski `POST /auth/password-recovery` + Redis (HMAC e-maila) + `resetPasswordAllowed=false` | S2 + test: 4. zahtjev u 1 h ne šalje poruku, odgovor identičan |
| MFA autokuće opcionalan (I07) | Keycloak dobrovoljni TOTP/WebAuthn | bez globalne obvezne akcije; enrol kroz `kc_action=CONFIGURE_TOTP` | realm linter + test prijave bez MFA |
| MFA platformski korisnici (D22) | Keycloak LoA2 + aplikacija | step-up/ACR; aplikacija zahtijeva `auth_level=LOA2` | S3 + testovi |
| Redis limiter (I08) | F1 | svi API pozivi | postojeći testovi + nove rute |

### 7.2 Oporavak i promjena lozinke, oporavak računa (D20, D21, D37, D41)
- **Zaborav:** `POST /auth/password-recovery {email}` → uvijek 202 `{status:"accepted"}` (isti oblik i približno isto vrijeme, bez obzira postoji li račun). Interno: limiter(HMAC(email)) 3/h → ako račun postoji i ACTIVE/PENDING → `identity_outbox` zahtjev → admin API `execute-actions-email` `UPDATE_PASSWORD`, `lifespan=1800 s`, jednokratan. Nakon uspješnog reseta: opozovi **sve** sesije (razlog `PASSWORD_CHANGED`), obavijest korisniku. DEACTIVATED/BLOCKED računi ne dobivaju poruku (a odgovor ostaje isti).
- **Promjena lozinke (prijavljen):** `POST /me/security/password-change-requests` (step-up LoA1 svježi ≤ 10 min) → vraća `redirect_url` (`kc_action=UPDATE_PASSWORD`); po povratku `?kc_action_status=success` → ostale sesije opozvane, obavijest, audit.
- **Promjena e-maila:** analogno s `UPDATE_EMAIL` (D37).
- **MFA:** `POST /me/security/mfa-enrollment-requests` → `kc_action=CONFIGURE_TOTP`; uklanjanje MFA je osjetljiva radnja (step-up) i šalje obavijest; platformski korisnik ne može ostati bez MFA-a (grantovi se ne mogu koristiti dok MFA nije aktivan).
- **Oporavak računa:** samostalno reset lozinke i (ako S4 potvrdi) recovery kodovi. Račun s izgubljenim e-mailom/MFA-om bez kodova: ručni platformski oporavak nije u F2 (D41); korisnik ostaje bez pristupa dok se tok ne specificira u F3a/AT-17.

### 7.3 Zaštita od krađe sesije (D24)
Rotacija vjerodajnice pri prijavi i step-upu; kolačić `__Host-`/Secure/HttpOnly; tvrda veza na UA obitelj; meka na državu (audit + obavijest); max 10 sesija; mobilno reuse detection; kratki access token; odjava svega pri promjeni lozinke; svi događaji u auditu. Što se **ne** tvrdi: veza na IP nije jamstvo (mobilne mreže), UA obitelj nije autentifikator (samo detekcija).

### 7.4 Zaštita od enumeracije (D26)
Jedinstvena poruka prijave; oporavak/ponovna verifikacija uvijek 202; ujednačen oblik i redoslijed rada (bez ranog izlaza kad račun ne postoji); limiti po računu i IP-u; nevidljivi resursi 404; `ACCOUNT_DISABLED` otkriva se tek nakon uspješne autentifikacije; platformsko pretraživanje korisnika samo točnim e-mailom/ID-em i auditirano. **Preostali rizik:** Keycloak registracija otkriva da e-mail postoji (prihvaćanje odluke D26).

### 7.5 Zaštita od replay napada (D25)
`state`/`nonce`/PKCE jednokratni; ID token samo u callbacku; `jti` backchannel logouta u Redisu; Idempotency-Key (F1) za mutacije; CSRF token vezan uz sesiju; step-up dokaz vezan uz sesiju i vrijeme; refresh reuse detection. Nije u opsegu: DPoP/mTLS vezani tokeni.

### 7.6 Step-up (D23)
Aplikacija: `require_step_up(max_age_seconds, level)`; nedostaje → 401 `STEP_UP_REQUIRED` + `WWW-Authenticate: Bearer error="insufficient_user_authentication", acr_values="loa2", max_age="600"`. Klijent zove `POST /auth/step-up {purpose, return_to}` → `redirect_url` na Keycloak (`prompt=login`, `max_age`, `acr_values`); callback ažurira `step_up_at`, `auth_level` i rotira vjerodajnicu. Osjetljive radnje: lista iz D23.

### 7.7 Sigurnosne obavijesti (D27)
Događaji: promjena lozinke, promjena e-maila (stara i nova adresa), MFA dodan/uklonjen, odjava svih/drugih sesija, prijava iz nove države, račun blokiran/deaktiviran/reaktiviran, zatražen oporavak, promjena platformskog granta (primatelju). Port `SecurityNotifier` + SMTP implementacija (DEV Mailpit; PROD blokirano do O15). Sadržaj bez tajni, linkova za prijavu i punih podataka o uređaju; uključuje vrijeme, grubu lokaciju i uputu „nisi li to bio ti". Isporuka kroz outbox (ne blokira opoziv).

## 8. F2.05 — Autorizacija i minimalni AT-17

### 8.1 Načela
Deny by default; least privilege; ovlasti čitane iz baze na svaki zahtjev (opoziv trenutačan); platformske i tenant ovlasti u odvojenim tablicama/putevima koji se ne miješaju; nijedna platformska ovlast ne omogućuje pristup tenant podacima izvan izričito opisanog opsega (F3a: verifikacijski zapisi; podrška: AT-03 #20 `SupportAccessGrant`, izvan F2); zabrana arbitrarnog prebacivanja između tenanta (ADR-002).

### 8.2 Model `platform_grants` (D28, D29)
| Stupac | Pravilo |
|---|---|
| `id`, `user_id` | uuid; `user_id` FK `users` |
| `grant_type` | CHECK ∈ {`PLATFORM_GRANT_ADMIN`, `PLATFORM_USER_ADMIN`, `PLATFORM_AUDIT_VIEW`, `PLATFORM_VERIFICATION_REVIEW`, `PLATFORM_ACCOUNT_RECOVERY`} |
| `scope_kind`, `scope_tenant_ids`, `queue` | `ALL`/`TENANTS`/`QUEUE`; za F2 tipove osim verifikatora samo `ALL` |
| `status` | `PENDING_APPROVAL` · `ACTIVE` · `REVOKED` (istek se računa iz `expires_at`) |
| `expires_at` | **NOT NULL**, ≤ 365 d (verifikator ≤ 90 d) |
| `granted_by`, `approved_by`, `reason`, `created_at`, `activated_at`, `revoked_at`, `revoked_by`, `revoke_reason` | `granted_by <> user_id` i `approved_by <> user_id` i `approved_by <> granted_by` (DB CHECK) za tipove s four-eyes |
Trigger: nakon aktivacije dopuštena samo promjena `status→REVOKED` + `revoked_*`; `DELETE` zabranjen. **Four-eyes:** `PLATFORM_GRANT_ADMIN` i `PLATFORM_USER_ADMIN` zahtijevaju odobrenje druge osobe s `PLATFORM_GRANT_ADMIN`; ostali tipovi jedan `PLATFORM_GRANT_ADMIN`. Nema nasljeđivanja i nema „super" grant tipa.
**RLS:** čitanje vlastitih redaka; svi redci uz `PLATFORM_GRANT_ADMIN`; pisanje samo platform rola kroz uslužni sloj. SQL funkcija `platform_has_grant(tip, tenant_id?)` (INVOKER, `STABLE`) čita aktivne, neistekle grantove za `app_user_id()`; svaki upis koji koristi grant upisuje `audit_events` u istoj transakciji (I14).

### 8.3 Zaštita od eskalacije
1. Nema samododjele ni samoodobrenja (CHECK + servis).
2. Dodjelitelj ne može dodijeliti tip koji sam ne drži aktivnim (osim `PLATFORM_GRANT_ADMIN` uz four-eyes).
3. Dodjela/opoziv zahtijeva LoA2 ≤ 5 min.
4. Svaka dodjela, odobrenje, odbijanje, opoziv, istek i **svaka upotreba** granta auditirani; korisnik dobiva obavijest.
5. Opoziv zadnjeg aktivnog `PLATFORM_GRANT_ADMIN`-a odbijen (anti-lockout); izlaz je bootstrap CLI (D30).
6. Zaštita od TOCTOU: provjera granta unutar iste transakcije kao radnja (`FOR SHARE` na retku granta).
7. Korisnik s grantom prijavljen bez MFA-a vidi `403 STEP_UP_REQUIRED` na svakoj platformskoj ruti.

### 8.4 Platform rola i cross-tenant
Platformske rute koriste `platform` DB rolu (F1 `create_db_engine(role="platform")`); RLS politike na `users`, `user_sessions`, `audit_events`, `platform_grants` imaju zasebne politike `TO <platform rola>` (kreirane petljom kao grantovi u migraciji 0001) čiji uvjet uključuje `platform_has_grant(...)`. Bez granta platform rola vidi **0 redaka** (test). Pristup tenant tablicama platform rola dobiva tek u F3a, po tablici, uz opseg iz granta.

### 8.5 Bootstrap (D30)
`scripts/identity/bootstrap_platform_admin.py --email … ` (owner vjerodajnice iz okoline, izvan aplikacije): traži postojećeg ACTIVE korisnika, izdaje `PLATFORM_GRANT_ADMIN` s `expires_at` ≤ 90 d, audit `actor_type=SYSTEM`, `reason=bootstrap`. Samo DEV/CI u F2.

## 9. F2.06 — Audit i sigurnosni događaji

### 9.1 Model `audit_events` (D31)
`id` uuid PK · `occurred_at` timestamptz · `scope` (`TENANT`/`PLATFORM`) · `category` (`AUTHN`, `SESSION`, `SECURITY_SETTING`, `AUTHZ`, `ADMIN`, `ACCESS_DENIED`, `IDENTITY`) · `action` (stabilan kod, npr. `auth.login.succeeded`) · `outcome` (`SUCCESS`/`FAILURE`/`DENIED`) · `actor_type` (`USER`/`SYSTEM`/`IDP`/`ANONYMOUS`) · `actor_user_id` · `actor_session_id` · `subject_user_id` · `tenant_id`/`branch_id` (NULL) · `target_type`/`target_id` · `request_id` · `ip_prefix` · `ua_family` · `reason_code` · `details` jsonb · `schema_version` · `source` (`APP`/`KEYCLOAK`) · `source_event_id` (dedup, UNIQUE gdje nije NULL).
CHECK: `scope='TENANT'` ⇒ `tenant_id IS NOT NULL`. Bez FK na `users` (zapis nadživljava korisnika, AT-20 retencija).

### 9.2 Katalog događaja (F2)
`auth.login.succeeded|failed` (KC), `auth.logout`, `auth.callback.rejected` (state/nonce/token), `auth.token.invalid`, `identity.user.provisioned`, `identity.link.conflict`, `identity.email.verified`, `identity.email.changed`, `identity.user.deactivated|blocked|reactivated`, `session.created|revoked|expired_detected|context.changed|theft_suspected`, `security.password.changed`, `security.password.recovery.requested|limited`, `security.mfa.enrolled|removed`, `security.step_up.succeeded|failed`, `security.settings.changed` (KC admin događaji), `authz.platform_grant.requested|approved|activated|revoked|used|expired`, `authz.denied` (neautorizirani pokušaj: cross-tenant, grant nedostaje, CSRF), `admin.audit.viewed`, `admin.user.searched`.

### 9.3 Zaštita zapisa
`REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM` app/worker/platform; samo INSERT (i SELECT po politici); trigger `BEFORE UPDATE OR DELETE` baca iznimku (obrana u dubini; owner nije runtime rola); `default privileges` iz `harden.sql` zato eksplicitno povlačenje u migraciji. RLS: INSERT app/worker uz `scope`/`tenant_id` CHECK; SELECT platform uz `PLATFORM_AUDIT_VIEW`; korisnik čita **vlastite** `AUTHN|SESSION|SECURITY_SETTING` događaje (`GET /me/security-events`); tenant korisnici ne čitaju audit u F2 (tenant pregled dolazi s AT-03 #21). Lančani hash: odgođen, shema ostavlja prostor (`schema_version`).

### 9.4 Zabrana osjetljivih podataka
`app.audit.record(...)` prima tipiziran `details` po akciji (allowlist ključeva); validator odbija ključeve/vrijednosti koji odgovaraju `password|secret|token|authorization|cookie|code_verifier|refresh|id_token|client_secret` ili JWT/Bearer uzorcima; e-mail se **ne** zapisuje (koristi `subject_user_id`); IP samo prefiks (/24, /48); korisnički agent samo obitelj. Test: fuzz po svim akcijama; sken zapisa i logova (F1 redakcija) na zabranjene uzorke; `.gitleaks` neizmijenjen.

### 9.5 Keycloak događaji (D32)
Worker svake minute zove `GET /admin/realms/{realm}/events` i `/admin-events` (service account `at-admin-svc`, `view-events`), kursor u `identity_outbox`, dedup po `source_event_id`; mapira `LOGIN`, `LOGIN_ERROR`, `LOGOUT`, `UPDATE_PASSWORD`, `UPDATE_TOTP`, `REMOVE_TOTP`, `UPDATE_EMAIL`, `RESET_PASSWORD`, `REFRESH_TOKEN_ERROR` i admin promjene na katalog. Realm: spremanje događaja uključeno, admin-events bez reprezentacije, istek 7 dana. Kašnjenje ingestije ≤ 2 min je poznata granica (neuspješne prijave nisu u realnom vremenu); opoziv i autorizacija ne ovise o njoj.

## 10. F2.07 — API ugovori
Konvencije F1 (I16): `/api/v1`, snake_case, `application/problem+json` s `code` i `request_id`, `Idempotency-Key` na mutacijama, `If-Match`/ETag na izmjenama, cursor paginacija (25/1/100), UUID, UTC. Svi odgovori `Cache-Control: no-store` za auth/sesije.

### 10.1 Sigurnosne sheme (D39)
`cookieSession` (apiKey, cookie `__Host-at_session`) + `csrfToken` (apiKey, header `X-CSRF-Token`) za web; `bearerAuth` (http bearer JWT) za mobilno. Svaka operacija deklarira sheme i potrebnu autorizaciju (`x-authorization`: user / workspace / platform grant / step-up).

### 10.2 Endpointi
| Metoda i putanja | Svrha | Auth | Odgovor / napomena |
|---|---|---|---|
| `GET /auth/login` | početak OIDC toka (web) | javno, limit IP | 302 Keycloak; `x-internal` |
| `GET /auth/callback` | završetak toka | javno, state | 302 + Set-Cookie; `x-internal` |
| `POST /auth/logout` | odjava | sesija+CSRF | 200 `{end_session_url}` |
| `POST /auth/oidc/backchannel-logout` | KC odjava | `logout_token` | 204 |
| `POST /auth/mobile/session` | otvori sesiju (mobilno) | bearer | 201/200 `Session` |
| `GET /auth/session` | stanje sesije + CSRF token | sesija/bearer | `SessionInfo` |
| `POST /auth/step-up` | step-up | sesija/bearer | `{redirect_url}` |
| `POST /auth/password-recovery` | zaboravljena lozinka | javno, limiti | 202 generički |
| `GET /me` · `PATCH /me` | profil (`display_name`, `preferred_language`) | korisnik; PATCH If-Match | `User` |
| `POST /me/email-verification` | ponovno slanje | korisnik | 202 |
| `GET /me/security` | stanje: `mfa_enrolled`, `password_changed_at` | korisnik | `SecurityState` |
| `POST /me/security/password-change-requests` | promjena lozinke | step-up | `{redirect_url}` |
| `POST /me/security/mfa-enrollment-requests` | MFA enrol | korisnik | `{redirect_url}` |
| `POST /me/security/email-change-requests` | promjena e-maila | step-up | `{redirect_url}` |
| `GET /me/security-events` | vlastiti sigurnosni događaji | korisnik | cursor lista |
| `GET /me/workspaces` | dostupni tenanti/poslovnice | korisnik | lista (u F2 prazno) |
| `GET /sessions` | vlastite sesije | korisnik | cursor lista `SessionSummary` |
| `DELETE /sessions/{id}` | opozovi vlastitu | korisnik | 204; tuđa → 404 |
| `POST /sessions/revoke-others` | opozovi ostale | korisnik | 200 `{revoked: n}` |
| `POST /sessions/revoke-all` | opozovi sve | korisnik+step-up | 200 |
| `POST /sessions/workspace` | promijeni kontekst | korisnik; If-Match | `SessionInfo` |
| `GET /platform/users` · `GET /platform/users/{id}` | pretraga/pregled | `PLATFORM_USER_ADMIN`, LoA2 | filter: točan `email`/`id`/`status`; audit |
| `POST /platform/users/{id}/deactivate\|reactivate\|block\|unblock` | status računa | `PLATFORM_USER_ADMIN`, LoA2 ≤ 10 min; `{reason_code, note}` | `User`; Idempotency-Key |
| `GET /platform/users/{id}/sessions` · `POST …/sessions/revoke` | tuđe sesije | `PLATFORM_USER_ADMIN` | lista / 200 |
| `GET /platform/grant-types` | katalog | `PLATFORM_GRANT_ADMIN` | lista |
| `GET /platform/grants` · `POST /platform/grants` | popis / zahtjev | `PLATFORM_GRANT_ADMIN`, LoA2 ≤ 5 min | `PlatformGrant` (PENDING_APPROVAL ako four-eyes) |
| `POST /platform/grants/{id}/approve\|reject\|revoke` | odobri / odbij / opozovi | `PLATFORM_GRANT_ADMIN` (≠ podnositelj), LoA2 | `PlatformGrant` |
| `GET /platform/audit-events` | pregled audita | `PLATFORM_AUDIT_VIEW`, LoA2 | cursor, filteri kategorija/akcija/aktor/subjekt/vrijeme; audit pregleda |
`GET /health` ostaje neizmijenjen (nema detalja).

### 10.3 Modeli (sažetak, snake_case)
`User{id, email, email_verified, status, display_name, preferred_language, created_at, version}` (e-mail samo vlastiti i administratorski) · `SessionSummary{id, client_type, device_label, platform, country_code, created_at, last_activity_at, expires_at, current}` · `SessionInfo{session_id, user, auth_level, step_up_expires_at, expires_at, idle_expires_at, workspace?{tenant_id, branch_id, context_version}, csrf_token?}` · `PlatformGrant{id, user_id, grant_type, scope_kind, scope_tenant_ids?, queue?, status, expires_at, granted_by, approved_by?, created_at}` · `AuditEvent{id, occurred_at, category, action, outcome, actor_user_id?, subject_user_id?, tenant_id?, request_id, details}` (`details` allowlistirano) · `SecurityState{mfa_enrolled, password_changed_at?}` · `ProblemDetails` (F1). Točne sheme su u OpenAPI-ju (T12).

### 10.4 Katalog grešaka (D39, dopuna F1 kodova)
| HTTP | `code` | Značenje |
|---|---|---|
| 400 | `AMBIGUOUS_CREDENTIALS` | kolačić i bearer istodobno |
| 401 | `AUTH_REQUIRED` · `AUTH_TOKEN_INVALID` · `SESSION_REQUIRED` · `SESSION_EXPIRED` · `SESSION_REVOKED` | neautentificiran; neispravan token; nema aplikacijske sesije; istekla; opozvana |
| 401 | `STEP_UP_REQUIRED` | potrebna svježa/jača autentifikacija (RFC 9470) |
| 403 | `CSRF_INVALID` · `EMAIL_NOT_VERIFIED` · `ACCOUNT_DISABLED` · `FORBIDDEN` | CSRF; e-mail nepotvrđen; račun deaktiviran/blokiran; nema ovlasti (bez detalja o granu) |
| 404 | `NOT_FOUND` · `WORKSPACE_NOT_FOUND` | nepostojeći ili nevidljiv resurs (ne otkriva tenant) |
| 409 | `GRANT_CONFLICT` · `INVALID_STATUS_TRANSITION` · `ACCOUNT_CONFLICT` · `LAST_GRANT_ADMIN` | sukobi stanja |
| 412/428 | F1 | `If-Match` |
| 429/503 | `RATE_LIMIT_EXCEEDED` · `RATE_LIMIT_UNAVAILABLE` · `IDENTITY_PROVIDER_UNAVAILABLE` | limiti; Keycloak/Redis nedostupni (fail closed) |
`type` prema F1 (`https://docs.autotramita.es/errors/<kebab-code>`).

### 10.5 Kompatibilnost klijenata
Next.js: isti origin, kolačić + CSRF token iz `GET /auth/session`, bez CORS-a; generirani TS klijent šalje `credentials` i zaglavlje. Flutter: bearer + `POST /auth/mobile/session`; Dart klijent iz istog OpenAPI-ja; kompajliranje/analiza Dart koda ostaje odgođeni F1 rezidual (R10) i F2 ga ne zatvara. Preglednička preusmjerenja (`/auth/login`, `/auth/callback`) nisu u generiranom klijentu. Promjene ugovora nakon T12 su verzionirane (ADR-004).

## 11. F2.08 — Testiranje
Detaljni plan, slojevi, CI provjere i matrica AC→test: [F2-IMPLEMENTATION-PLAN §4–5](../design/F2-IMPLEMENTATION-PLAN.md). Kriteriji: [F2-ACCEPTANCE-CRITERIA](../design/F2-ACCEPTANCE-CRITERIA.md). Pravilo F1 vrijedi: CI-only integracija (izolirani servisi, nula preskočenih testova, `-W error`).

## 12. Sigurnosni i pravni pregled (kratko)
Osobni podaci: e-mail, ime (opcionalno), gruba lokacija i uređaj (sesije), prefiks IP-a (audit). Pravna osnova, retencija i obavijesti korisniku → AT-20 (GDPR/LOPDGDD); do tada ništa se automatski ne briše (D42) i ne uvode se dodatni podaci. Financijski utjecaj: nema novih plaćenih servisa u F2; PROD e-mail ovisi o O15; Keycloak dodaje održavanje (nadogradnje, rotacija ključeva).

## 13. Otvorena pitanja za vlasnika
Sve su u [registru odluka](../design/F2-DECISION-REGISTER.md); posebno **D15** (trajanja sesija/MFA), **D17** (F1 amandman), **D20** (oporavak lozinke aplikacijski), **D22** (MFA profesionalnih uloga) i **D26** (preostali rizik enumeracije pri registraciji).
