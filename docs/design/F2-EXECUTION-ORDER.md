# F2 — Redoslijed izvršavanja (execution order)

Datum: 2026-11-24 | Status: **CP00–CP08 prihvaćeni 2026-11-24; autoriziran samo F2-T09** | T10–T13 nisu autorizirani
[Plan](F2-IMPLEMENTATION-PLAN.md) · [Specifikacija AT-02](../specifications/AT-02-identity-security.md) · [Registar odluka](F2-DECISION-REGISTER.md) · [Kriteriji](F2-ACCEPTANCE-CRITERIA.md) · [G6 (F1 obrazac)](../G6-EXECUTION-ORDER.md)

**Sažetak:** 13 paketa (F2-T01…T13), 14 checkpointova (F2-CP00 planiranje, CP01…CP12 po paketu, CP13 završno prihvaćanje).

## 0. Opća pravila (vrijede za svaki paket)
1. Rad samo na `dev`; bez novih grana, merge-a u `main`, deploymenta, pristupa zajedničkoj infrastrukturi (I19).
2. **Paket počinje tek nakon zapisa autorizacije** (§3) koji sadrži izvorni tekst vlasnika i datum. Prihvaćanje CP-a ne autorizira sljedeći paket.
3. Redoslijed unutar paketa: pregled postojećeg koda → zapis autorizacije → testovi/kod u malim commitovima → CI run na točnom SHA → izvještaj → **STOP**.
4. Odluke koje paket zahtijeva moraju biti ACCEPTED (u registru) prije početka; PROPOSED odluka ne smije se implementirati (D40). Ako ovisna odluka nije prihvaćena → STOP, ne pretpostavljati.
5. Dopuštene putanje su D35; izvan njih zahtijeva zasebno odobrenje (scope guard test).
6. Dokaz prihvaćanja = CI run (sva tri joba + nova `identity-integration`), točan SHA, 0 skipped, Ruff/mypy čisti, OpenAPI drift OK, gitleaks bez nalaza, pip-audit čist. Izvještaj ne smije tvrditi što nije izvedeno.
7. Svaki paket uključuje negativne sigurnosne testove za vlastite površine (ne odgađaju se na T13).
8. Nikad: stvarne vjerodajnice, produkcijski podaci, pristup zajedničkom Keycloaku/PostgreSQL-u, `provision-postgres.py` nad zajedničkim PostgreSQL-om, primjena migracija na trajnu bazu.
9. **Univerzalni STOP uvjeti:** neriješena/neprihvaćena ovisna odluka; pao sigurnosni test; neočekivana promjena sheme; potreba za stvarnom vjerodajnicom ili zajedničkom infrastrukturom; proširenje opsega (osobito prema AT-03); spike opovrgne pretpostavku dizajna; promjena prihvaćene F1 arhitekture izvan odobrenog D17; nalaz P0.
10. Rollback (opće): kod `git revert` na `dev` (bez prepisivanja povijesti); baza `alembic downgrade` na jednokratnoj/CI bazi + idempotentni `harden.sql`; OpenAPI se regenerira nakon reverta. Nema deploymenta pa nema produkcijskog rollbacka.

## 1. Zajednički dopušteni put i izvan opsega
Dopušteno (D35): `app/auth/**`, `app/audit/**`, `app/platform/**`, `app/celery_app.py`, `app/api/v1/**`, aditivne izmjene `app/core/{db,config,errors}.py`, `migrations/versions/**`, `tests/**`, `identity/**`, `scripts/identity/**`, `scripts/db/**`, `openapi/**`, `.github/workflows/**`, `pyproject.toml`, `uv.lock`, `docs/**`.
Zabranjeno: `docker-compose*.yml`, `.secrets/`, Traefik/Cloudflare, `scripts/provision-postgres.py` (izvođenje), tenant/customer/case/billing/credit/documents moduli, frontend, Flutter, Nextcloud/mail konfiguracija, deployment.

## 2. Paketi

### F2-T01 — Keycloak realm kao kod, test okruženje i spike
- **Cilj:** dokazati izvedivost svih Keycloak pretpostavki (S1–S10) na 26.4.7 i isporučiti reproducibilno okruženje.
- **Ovisnosti:** CP00 prihvaćen; D01, D02, D07 prihvaćeni.
- **Dopuštene promjene:** `identity/**`, `.github/workflows/**` (novi job), `tests/**`, `docs/**`, `pyproject.toml/uv.lock` (samo dev ovisnosti ako treba).
- **Datoteke/komponente:** `identity/keycloak/realm-template.json`, `realm-dev.json`, `realm-test.json`, `identity/docker-compose.keycloak-test.yml` (jednokratni, izbacivi volumen), `identity/README.md` (runbook: uvoz, rotacija ključeva D06), `docs/design/F2-KEYCLOAK-SPIKE-REPORT.md`, `tests/identity/test_realm_lint.py`, `tests/identity/test_keycloak_spike.py` (marker `keycloak`), CI job `identity-integration`.
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** realm bez tajni (placeholderi iz okoline); bez wildcard redirect URI, implicit i direct grants; javni klijent bez tajne; `resetPasswordAllowed=false`; `verifyEmail=true`; brute-force 5/15 min; admin-events bez reprezentacije; digest pin image-a; ne dira se zajednički Keycloak.
- **Testovi:** linter realma (negativni slučajevi namjerno pokvarenog JSON-a); spike testovi S1–S10 s dokazom po tvrdnji (prolazi/ne prolazi, s točnim parametrima); uvoz realma u svježi container; test rotacije ključa.
- **Kriteriji prihvaćanja:** AC-KC-01…06; spike izvještaj navodi za svaki S rezultat (POTVRĐENO / OPOVRGNUTO + posljedica na odluku); CI job zelen, 0 skipped.
- **Checkpoint:** **F2-CP01** — vlasnik pregledava izvještaj spika i odlučuje o ishodima (osobito S2, S3, S4, S6).
- **STOP:** bilo koji S opovrgnut tako da mijenja prihvaćenu odluku (npr. nema LoA step-upa, nema reuse detectiona) → prijaviti alternativu, ne improvizirati; potrebna vjerodajnica izvan CI-a; potreba za izmjenom Compose-a.
- **Rollback:** revert commitova; nema stanja izvan repoa/CI-a (jednokratni container).

### F2-T02 — Konfiguracija auth modula, validacija tokena, lažni IdP
- **Cilj:** sigurna validacija Keycloak tokena i testna infrastruktura IdP-a.
- **Ovisnosti:** CP01; D05, D06, D34 prihvaćeni.
- **Dopuštene promjene:** `app/auth/**`, `app/core/config.py` (aditivno), `app/core/errors.py` (kodovi), `tests/**`, `pyproject.toml/uv.lock` (`PyJWT[crypto]`).
- **Datoteke/komponente:** `app/auth/settings.py` (issuer, JWKS URL, klijenti, trajanja D15 kao konfiguracija s PROPOSED zadanim vrijednostima, ključevi limita), `app/auth/tokens.py` (validator + JWKS cache), `app/auth/idp.py` (port `IdentityProvider`, admin klijent sučelje), `tests/auth/fake_idp.py`, `tests/auth/test_tokens.py`, `tests/auth/test_tokens_keycloak.py`.
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** allowlist algoritama; potpis prije bilo kakvog povjerenja u claimove; `none`/HS* odbijeni; granice `exp`/`nbf` ±30 s; JWKS cache s limitom osvježavanja; nikakvi tokeni u logovima/iznimkama (redakcija); fail closed pri nedostupnom JWKS-u (503 `IDENTITY_PROVIDER_UNAVAILABLE` samo bez valjanog cachea).
- **Testovi:** jedinični negativni skup (§4 plana: none, HS256 s javnim ključem, krivi iss/aud/azp/typ, exp/nbf granice, nepoznat kid + rate limit osvježavanja, ID token kao access, preveliki token, nevaljan base64); Keycloak: valjan token prolazi, rotacija ključa; mutation test (svaka provjera uklonjena → test pada).
- **Kriteriji prihvaćanja:** AC-TOK-01…08.
- **Checkpoint:** **F2-CP02**.
- **STOP:** potreba za drugačijom bibliotekom od D34; potreba za pohranom tokena; proširenje na autorizaciju.
- **Rollback:** revert; `uv lock` povratak.

### F2-T03 — `audit_events` i bootstrap kontekst
- **Cilj:** nepromjenjivi audit sloj i aditivno proširenje F1 konteksta potrebno za autentifikaciju.
- **Ovisnosti:** CP02; **D17 izričito prihvaćen** (ili odobrena alternativa), D31, D42 (privremeno).
- **Dopuštene promjene:** `app/audit/**`, `app/core/db.py` (samo D17: nova opcionalna polja `RequestContext`, `apply_context`), `migrations/versions/**`, `scripts/db/harden.sql` (samo ako potrebno za REVOKE obrazac, uz obrazloženje), `tests/**`.
- **Datoteke/komponente:** `0002_auth_bootstrap_context` (funkcije `app_auth_subject()`, `app_session_hash()` + GRANT EXECUTE kao u 0001), `0003_audit_events`, `app/audit/models.py`, `app/audit/record.py` (tipizirani `details` po akciji, validator), `app/audit/catalog.py`, `tests/audit/*`, `tests/test_context_bootstrap.py`.
- **Migracije:** 0002, 0003 (obje reverzibilne; downgrade briše funkcije/trigger-e/tablicu).
- **Sigurnosni zahtjevi:** FORCE RLS; `REVOKE UPDATE, DELETE, TRUNCATE` svim runtime rolama + trigger; INSERT politika; CHECK `scope/tenant_id`; bez FK na users; validator odbija tajne/e-mail/pune IP-ove; aditivnost D17 (stari testovi nepromijenjeni i zeleni); bootstrap kontekst postavlja samo `app.auth` modul (test statičke provjere uvoza).
- **Testovi:** UPDATE/DELETE/TRUNCATE odbijeni za app, worker, platform (i trigger pri direktnom pokušaju); RLS čitanje (bez konteksta 0 redaka; platform bez granta 0); validator fuzz po katalogu; dedup `source_event_id`; kontekst ne curi iz poola (nova polja); downgrade/upgrade ciklus; regresija svih F1 testova.
- **Kriteriji prihvaćanja:** AC-AUD-01…07, AC-CTX-01…03.
- **Checkpoint:** **F2-CP03** — pregled migracija **prije** bilo kakve primjene (čak i na CI bazu iz trajnog okruženja nije dopušteno).
- **STOP:** D17 neodobren; potreba za izmjenom F1 ponašanja (ne samo dodatka); owner/role model ne dopušta REVOKE obrazac; test pokazuje da audit zapis može mijenjati bilo koja runtime rola.
- **Rollback:** `alembic downgrade` na jednokratnoj bazi; revert; D17 revert vraća `RequestContext` na F1 oblik.

### F2-T04 — `users`, povezivanje, životni ciklus
- **Cilj:** globalni identitet, JIT provisioning po `sub`, status model s trenutačnim posljedicama.
- **Ovisnosti:** CP03; D08–D11, D36 prihvaćeni.
- **Dopuštene promjene:** `app/auth/**`, `migrations/versions/**`, `tests/**`.
- **Datoteke/komponente:** `0004_users`, `app/auth/users/models.py`, `repository.py`, `service.py` (provision/link, matrica prijelaza, deactivate/block/reactivate — bez HTTP-a), `app/auth/email.py` (normalizacija), `tests/auth/users/*`.
- **Migracije:** 0004 (tablica, UNIQUE `auth_subject` i `email_normalized`, CHECK `ACTIVE ⇒ email_verified_at`, trigger prijelaza i nepromjenjivosti `auth_subject`, RLS politike, column GRANT).
- **Sigurnosni zahtjevi:** povezivanje samo po `sub`; sukob e-maila → odbijanje + audit; app rola ne može `UPDATE status`; tuđi redak nevidljiv; bez PII izvan D36; promjena statusa i opoziv sesija u istoj transakciji (sučelje za T05 — u T04 kroz port koji T05 implementira).
- **Testovi:** paralelni prvi login istog `sub` (jedan redak); dva `sub` istog e-maila (odbijeno, audit); normalizacija (unicode, velika slova; plus-adresa ostaje različita); matrica prijelaza (dopušteni i svi nedopušteni parovi); `auth_subject` nepromjenjiv; RLS (vlastiti redak, bootstrap ne otkriva druge, INSERT s tuđim `sub` odbijen); column GRANT; deaktivacija vs. paralelni provisioning.
- **Kriteriji prihvaćanja:** AC-USR-01…10.
- **Checkpoint:** **F2-CP04**.
- **STOP:** potreba za poljima koja nisu u D36; veza s customers/memberships; neslaganje s ADR-003 stupcima.
- **Rollback:** downgrade 0004 (briše tablicu — samo jednokratna baza); revert.

### F2-T05 — `user_sessions` i servis sesija
- **Cilj:** aplikacijske sesije s validacijom, istekom, opozivom i trenutačnim učinkom.
- **Ovisnosti:** CP04; D12, D15, D16, D24 prihvaćeni.
- **Dopuštene promjene:** `app/auth/**`, `migrations/versions/**`, `tests/**`.
- **Datoteke/komponente:** `0005_user_sessions`, `app/auth/sessions/{models,repository,service}.py` (create, resolve, touch, revoke*, evikcija 11. sesije, rotacija vjerodajnice, izračun isteka), `app/auth/credentials.py` (CSPRNG, SHA-256, usporedba konstantnog vremena), implementacija porta iz T04 (opoziv pri promjeni statusa), `tests/auth/sessions/*`.
- **Migracije:** 0005 (tablica, UNIQUE `credential_hash`, UNIQUE `(kc_session_id, client_type)`, indeksi `user_id`, `idle_expires_at`; RLS; column GRANT/trigger nepromjenjivih polja; bez FK na tenant tablice).
- **Sigurnosni zahtjevi:** u bazi samo hash; istek se računa pri čitanju; `FOR SHARE` na mutirajućim putovima, opoziv `FOR UPDATE`; touch ≤ 1×/60 s; max 10 sesija; opoziv sa razlogom i aktorom + audit; bootstrap čitanje samo po poznatom hashu.
- **Testovi:** živa/istekla (idle, apsolutna) granice; opoziv svih vrsta (§6.7); deaktivacija opoziva sve u istoj transakciji; **konkurentnost** opoziv vs. zahtjev u tijeku (redoslijed), paralelna evikcija, paralelna rotacija; RLS (tuđa sesija nevidljiva/neopoziva, `SET ROLE` odbijen); pool reuse ne prenosi `app.session_hash`; hash nije moguće vratiti u tajnu (nema tajne u bazi, redakcija); migracijski ciklus.
- **Kriteriji prihvaćanja:** AC-SES-01…12.
- **Checkpoint:** **F2-CP05**.
- **STOP:** nepotvrđena trajanja (D15) koja blokiraju zadane vrijednosti → koristiti konfiguraciju PROPOSED i izričito označiti; potreba za FK prema tenant tablicama; trkački prozor koji `FOR SHARE/UPDATE` ne zatvara.
- **Rollback:** downgrade 0005; revert.

### F2-T06 — Web tok (BFF)
- **Cilj:** prijava, odjava, backchannel logout, kolačić, CSRF, step-up za preglednik.
- **Ovisnosti:** CP05; D03, D12–D14, D23, D25, D38, D39 prihvaćeni.
- **Dopuštene promjene:** `app/auth/web/**`, `app/api/v1/auth.py`, `app/api/v1/router.py`, `app/core/config.py` (aditivno), `openapi/openapi.json`, `tests/**`.
- **Datoteke/komponente:** `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `POST /auth/oidc/backchannel-logout`, `GET /auth/session`, `POST /auth/step-up`; `app/auth/web/{oidc_flow,cookies,csrf,redirects,backchannel}.py`; limiti D38.
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** `state`/`nonce`/PKCE jednokratni (Redis, ≤ 10 min); tokeni odbačeni nakon callbacka; kolačić `__Host-`/Secure/HttpOnly/SameSite=Lax; nova vjerodajnica pri prijavi i step-upu (nema fiksacije); `return_to` samo relativna allowlist putanja; CSRF token + Origin/Sec-Fetch-Site na nesigurnim metodama; `Cache-Control: no-store`; backchannel logout validira token i `jti` jednokratno; greške bez detalja.
- **Testovi:** puni tok protiv Keycloaka (login → sesija → zahtjev → odjava → zahtjev 401); replay callbacka/`state`; krivi nonce; fiksacija sesije; open redirect (`//evil`, `https://…`, `\\`, kodirani); CSRF skup (nema tokena, tuđi, krivi Origin, GET sigurna); kolačić + bearer istodobno 400; backchannel (valjan, replay `jti`, krivi `iss`, bez `events`); step-up (`STEP_UP_REQUIRED`, uspjeh, istek); atributi kolačića; rate limit ruta; deaktivirani/nepotvrđeni korisnik.
- **Kriteriji prihvaćanja:** AC-WEB-01…12.
- **Checkpoint:** **F2-CP06**.
- **STOP:** potreba za tokenima u pregledniku; potreba za `Domain=` kolačićem; ruta izvan D39; zahtjev za promjenom Traefika/Compose-a (D13 je live stavka).
- **Rollback:** revert; ažurirati OpenAPI.

### F2-T07 — Mobilni tok
- **Cilj:** bearer autentifikacija, otvaranje i upravljanje sesijama uređaja.
- **Ovisnosti:** CP05; D04, D24 prihvaćeni (paralelno s T06 samo uz izričito odobrenje; inače nakon CP06).
- **Dopuštene promjene:** `app/auth/mobile/**`, `app/api/v1/{auth,sessions}.py`, `openapi/openapi.json`, `tests/**`.
- **Datoteke/komponente:** `POST /auth/mobile/session`; `GET /sessions`, `DELETE /sessions/{id}`, `POST /sessions/revoke-others`, `POST /sessions/revoke-all` (zajedničko s webom); bearer dependency; `docs/design/F2-MOBILE-AUTH-NOTES.md` (upute klijentu: PKCE, pohrana u Keystore/Keychain, refresh, redirect URI).
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** validacija JWT (T02) pa tek sesija; `sid` mora odgovarati sesiji; idempotentno otvaranje (Idempotency-Key + UNIQUE); detekcija ponovne uporabe refresh tokena → opoziv `REFRESH_REUSE`; popis sesija samo vlastitih, tuđa → 404; gruba lokacija i uređaj bez punog IP-a; bez refresh tokena na serveru.
- **Testovi:** token valjan bez sesije → `SESSION_REQUIRED`; otvaranje sesije (idempotentno, paralelno); krivi `azp`/`aud`; opozvana sesija odbija još valjani access token (≤ 5 min prozor zatvoren); refresh reuse protiv Keycloaka; popis/opoziv, 404 za tuđu, limiti 10 sesija; token jednog korisnika ne otvara sesiju drugog.
- **Kriteriji prihvaćanja:** AC-MOB-01…08.
- **Checkpoint:** **F2-CP07**.
- **STOP:** zahtjev za vlastitim izdavanjem tokena (model B) → nova odluka; potreba za Flutter kodom.
- **Rollback:** revert; OpenAPI.

### F2-T08 — Pipeline konteksta, workspace i granica prema AT-03
- **Cilj:** jedinstven zahtjevni pipeline (autentifikacija → kontekst) i promjena konteksta; port prema budućem AT-03.
- **Ovisnosti:** CP06, CP07; D16, D18 prihvaćeni.
- **Dopuštene promjene:** `app/auth/context/**`, `app/api/v1/{sessions,me}.py`, `app/core/ratelimit.py` (samo postavljanje `principal_id/tenant_id` ako treba u `app/auth`, ne u limiteru), `openapi/**`, `tests/**`.
- **Datoteke/komponente:** FastAPI dependencies `require_user`, `require_workspace`, `require_step_up`; `app/auth/membership.py` (`MembershipAuthorizer` port, `DenyAllAuthorizer`), `tests/auth/fake_membership.py`; `POST /sessions/workspace`, `GET /me/workspaces`, `GET /me`, `PATCH /me`.
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** kontekst gradi samo server iz validirane sesije i porta; klijentski `tenant_id`/`branch_id` nikad autoritet; `None` iz porta = nema konteksta; greška porta = 503 fail closed; nepostojeći i tuđi tenant nerazlučivi (404); `request.state.principal_id/tenant_id` postavljeni samo iz validiranog konteksta; svaka promjena konteksta audit (staro→novo); route zadano deny (test: ruta bez deklarirane zaštite ne prolazi u OpenAPI/registar test).
- **Testovi:** cross-tenant skup (dvojnik + probne tablice): manipulirani header/body/path tenant, tuđi tenant, uklonjeno članstvo usred sesije, promjena uloge, uklonjena poslovnica, neaktivan tenant; dvije sesije istog korisnika s različitim kontekstom (nema curenja); `context_version` 412 pri paralelnoj promjeni; limiter po korisniku i tenantu koristi validirane vrijednosti (nema spoofinga); `DenyAllAuthorizer` u produkcijskom wiringu; test „sve rute imaju deklariranu autorizaciju".
- **Kriteriji prihvaćanja:** AC-CTX-04…12, AC-AUTHZ-01…03.
- **Checkpoint:** **F2-CP08**.
- **STOP:** potreba za stvarnim tenant/membership tablicama ili FK; implementacija članskih pravila (AT-03) → ne.
- **Rollback:** revert.

### F2-T09 — Sigurnosne politike
- **Cilj:** oporavak i promjena lozinke, e-mail verifikacija, MFA enrol, step-up politika, anti-enumeracija, obavijesti (port + DEV SMTP).
- **Ovisnosti:** CP08; D19–D27, D37, D38, D41 prihvaćeni (osobito **D20**, **D22**).
- **Dopuštene promjene:** `app/auth/security/**`, `app/api/v1/{auth,me}.py`, `app/core/config.py` (ažuriranje komentara/semantike `RateLimitSettings`), `identity/keycloak/**`, `tests/**`, `openapi/**`.
- **Datoteke/komponente:** `POST /auth/password-recovery`, `POST /me/email-verification`, `GET /me/security`, `POST /me/security/{password-change,mfa-enrollment,email-change}-requests`; `app/auth/security/{recovery,limits,notify}.py` (`SecurityNotifier` port, SMTP implementacija, predlošci es), `app/auth/idp_admin.py` (admin REST klijent: `execute-actions-email`, `enabled`, `logout`, credentials upit).
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** recovery uvijek 202 identičnog oblika i istog redoslijeda rada; Redis limit (HMAC e-maila) + IP; link 30 min jednokratan (KC); reset opoziva sve sesije; neaktivni računi ne primaju poruku; politika lozinke u realmu; MFA za autokuće se ne forsira; admin klijent koristi minimalne uloge i nikad ne logira tajne; obavijesti bez tajni; Redis nedostupan → fail closed.
- **Testovi:** brute-force 5/15 min protiv Keycloaka (6. odbijen); recovery limit (4. u satu ne šalje, odgovor isti); **enumeracija** (postojeći vs nepostojeći vs deaktiviran: status, tijelo, zaglavlja, raspon vremena); reset → sesije opozvane + obavijest; promjena lozinke/e-maila (`kc_action` povratni status); MFA enrol/uklanjanje (step-up, obavijest); prijava bez MFA-a autokuće prolazi; platformski korisnik bez MFA-a odbijen; obavijesti u Mailpit/fake (sadržaj bez tajni); limiter nedostupan → 503.
- **Kriteriji prihvaćanja:** AC-POL-01…14.
- **Checkpoint:** **F2-CP09**.
- **STOP:** S2/S3/S4 ishod ne podržava D20/D23/D41; zahtjev za prisilnim MFA-om autokuća (protivno I07); slanje stvarne e-pošte izvan DEV/CI.
- **Rollback:** revert; realm JSON revert.

### F2-T10 — `platform_grants` i autorizacija
- **Cilj:** platformske ovlasti s opsegom, istekom, four-eyes, trenutačnim opozivom i bootstrapom.
- **Ovisnosti:** CP08; D28–D30 prihvaćeni.
- **Dopuštene promjene:** `app/platform/**`, `app/api/v1/platform_grants.py`, `migrations/versions/**`, `scripts/identity/**`, `tests/**`, `openapi/**`.
- **Datoteke/komponente:** `0006_platform_grants`; `app/platform/{models,repository,service,authz}.py` (`require_platform_grant(tip, opseg)`), `GET /platform/grant-types`, `GET/POST /platform/grants`, `POST /platform/grants/{id}/{approve,reject,revoke}`, `scripts/identity/bootstrap_platform_admin.py`; SQL `platform_has_grant()`; politike `TO <platform rola>`.
- **Migracije:** 0006 (CHECK tipova/rokova/`granted_by <> user_id`, trigger „samo revoke", zabrana DELETE, RLS, funkcija, politike na `users/user_sessions/audit_events` za platform rolu uz grant).
- **Sigurnosni zahtjevi:** deny by default; ovlast iz baze na svaki zahtjev; LoA2 ≤ 5 min za dodjelu/opoziv; four-eyes; nema samododjele/samoodobrenja; nema dodjele tipa koji dodjeljivač ne drži; anti-lockout; svaka upotreba audit u istoj transakciji; platform rola bez granta = 0 redaka; grant ne otvara tenant podatke.
- **Testovi:** puni životni ciklus; istek (granica), opoziv (sljedeći zahtjev 403), eskalacije (self-grant, preskakanje four-eyes, tip izvan vlastitih, izmjena nakon aktivacije, DELETE), last-admin, paralelno odobrenje (jedan pobjednik), TOCTOU (opoziv usred radnje), platform rola vs. app rola (`SET ROLE`), RLS bez granta, verifikator bez user/grant ovlasti, bootstrap CLI (samo ACTIVE korisnik, audit `SYSTEM`, odbijen bez owner vjerodajnica), MFA obvezan, audit upotrebe.
- **Kriteriji prihvaćanja:** AC-PLT-01…12.
- **Checkpoint:** **F2-CP10**.
- **STOP:** zahtjev za dodatnim tipovima/ulogama izvan D29; pristup tenant tablicama; PROD bootstrap.
- **Rollback:** downgrade 0006; revert; bootstrap skripta se uklanja revertom.

### F2-T11 — Platformska administracija korisnika, outbox, Celery, KC događaji
- **Cilj:** administrativne radnje nad računima i sesijama, pouzdana sinkronizacija s Keycloakom, ingestija sigurnosnih događaja, obavijesti.
- **Ovisnosti:** CP09, CP10; D11, D27, D31–D33 prihvaćeni.
- **Dopuštene promjene:** `app/platform/**`, `app/auth/outbox/**`, `app/celery_app.py`, `app/api/v1/{platform_users,audit}.py`, `migrations/versions/**`, `tests/**`, `openapi/**`, `pyproject.toml/uv.lock`.
- **Datoteke/komponente:** `0007_identity_outbox`; `GET /platform/users`, `GET /platform/users/{id}`, `POST …/{deactivate,reactivate,block,unblock}`, `GET …/sessions`, `POST …/sessions/revoke`, `GET /platform/audit-events`, `GET /me/security-events`; `app/celery_app.py` (konfiguracija, beat raspored), taskovi obrade outboxa i ingestije KC događaja; `app/auth/outbox/handlers.py`.
- **Migracije:** 0007 (tablica, indeksi `status,next_attempt_at`, RLS, worker grantovi).
- **Sigurnosni zahtjevi:** platformske rute: grant + LoA2 ≤ 10 min + rate limit + audit pregleda/pretrage; pretraga samo točnim e-mailom/ID-em; razlog obvezan; outbox idempotentan s backoffom; sinkronizacija ne blokira opoziv; ingestija: allowlist polja, IP prefiks, dedup; worker koristi svoju rolu i ne vjeruje poruci za tenant/korisnika bez provjere; KC admin-events bez reprezentacije; ne logira se tajne.
- **Testovi:** deaktivacija/blokada (sesije odmah, KC `enabled=false` kroz outbox, ispad KC-a → ponavlja se, pristup i dalje odbijen); reaktivacija; 403 bez granta; pretraga auditirana; outbox obrada (idempotencija, duplikat, crash usred, backoff); ingestija (duplikati, redoslijed, kursor, nepoznat tip, pad KC-a); korisnikov `GET /me/security-events` ne vidi tuđe; audit pregled filteri/paginacija; obavijesti u outboxu; konkurentna deaktivacija + login.
- **Kriteriji prihvaćanja:** AC-ADM-01…10, AC-AUD-08…11.
- **Checkpoint:** **F2-CP11**.
- **STOP:** potreba za izmjenom Compose-a radi workera (ostaje live stavka); Celery nije prihvaćen (D33) → CLI alternativa uz odobrenje; podrška/impersonacija (izvan opsega).
- **Rollback:** downgrade 0007; revert; `app/celery_app.py` uklonjen revertom.

### F2-T12 — Zamrzavanje API ugovora
- **Cilj:** konačni OpenAPI, katalog grešaka, kompatibilnost klijenata.
- **Ovisnosti:** CP11; D39 prihvaćen.
- **Dopuštene promjene:** `openapi/**`, `app/api/**`, `tests/**`, `docs/**`.
- **Datoteke/komponente:** `openapi/openapi.json` (sheme `cookieSession`/`csrfToken`/`bearerAuth`, `x-authorization`, `x-internal`), contract testovi, `docs/design/F2-API-ERROR-CATALOG.md` (generira se/provjerava testom), generiranje TS i Dart.
- **Migracije:** nema.
- **Sigurnosni zahtjevi:** svaka operacija deklarira shemu i autorizaciju; nijedna ruta bez zaštite osim eksplicitno javnih (allowlist); odgovori nemaju PII izvan modela; `no-store` na auth rutama; CORS prazan.
- **Testovi:** odgovori = ugovor za sve F2 rute (uspjeh i svaka greška iz kataloga); test pokrivenosti (svaka operacija ima `x-authorization` i barem jedan negativni test); kodovi grešaka = katalog; TS/Dart generiranje (Dart bez analize, R10); drift; validator.
- **Kriteriji prihvaćanja:** AC-API-01…08.
- **Checkpoint:** **F2-CP12**.
- **STOP:** potreba za breaking promjenom već prihvaćenog F1 ugovora; rute koje nisu u D39.
- **Rollback:** revert + regeneriraj OpenAPI.

### F2-T13 — Završna validacija i dokaz prihvaćanja
- **Cilj:** dokazati sve AC-ove, bez novih funkcionalnosti.
- **Ovisnosti:** CP12.
- **Dopuštene promjene:** `tests/**`, `.github/workflows/**`, `docs/**` (ispravci samo uz poseban nalaz); funkcionalni ispravci samo za nalaze P0/P1 uz izvještaj.
- **Datoteke/komponente:** `docs/design/F2-FINAL-ACCEPTANCE-EVIDENCE.md`, `tests/test_f2_scope.py` (konačni), `tests/test_f2_traceability.py` (matrica AC→test), `docs/DEVELOPMENT.md` (F2 dio: lokalno pokretanje Keycloak testova, rollback), revidirani CI.
- **Migracije:** nema novih; ciklus up/down/up nad svim migracijama; role SQL dvaput; ne-owner odbijen.
- **Sigurnosni zahtjevi:** ponovljivost na čistom klonu; sken povijesti (gitleaks), pip-audit, linter realma, provjera da nijedan test/log/audit ne sadrži tajne; pregled točnog diffa `main..dev` za F2 (putanje, D35).
- **Testovi:** cijeli paket; ponavljanje nestabilnih (rate-limit, konkurentni) 3×; dodatni nasumični/fuzz skup nad auth rutama; neovisna lokalna provjera na čistom klonu (kao F1, kao dopuna, ne dokaz).
- **Kriteriji prihvaćanja:** svi AC iz [F2-ACCEPTANCE-CRITERIA](F2-ACCEPTANCE-CRITERIA.md) PASS ili izričito BOUNDED uz odobrenje; zero skipped; nema otvorenih P0/P1.
- **Checkpoint:** **F2-CP13 — završni acceptance checkpoint.**
- **STOP:** otvoren P0/P1; AC bez testa; neodobreno odstupanje od odluke; dokaz ovisi o zajedničkoj infrastrukturi.
- **Rollback:** revert dokumenata/testova; F2 kao cjelina povlači se revertom paketa unatrag (T12→T01) i downgradeom migracija 0007→0002 na jednokratnoj bazi.

## 3. Zapis autorizacije (predložak, popunjava vlasnik/agent po paketu)
```
Paket: F2-Txx | Datum: ____ | Tekst autorizacije vlasnika (doslovno): "____"
Prihvaćene odluke (ID): ____ | Preduvjeti ispunjeni: CP(xx-1) prihvaćen (datum, SHA) 
Zabranjeno izričito: merge u main, deployment, zajednička infrastruktura, sljedeći paket
```
Zapis ide u docs commit **prije** prvog commita koda paketa.

### Zapisi autorizacije
```
Paket: F2-T01 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam D01–D43 kako su predloženi; autoriziram samo F2-T01"
Prihvaćene odluke: D01–D41, D43 (D42 OPEN, AT-20) | Preduvjet: F2-CP00 prihvaćen 2026-11-24 (plan commit 0e5a2d1)
Zabranjeno izričito: T02–T13, merge u main, deployment, zajednička infrastruktura, izmjena Compose/Traefik, pokretanje Keycloaka izvan CI-a i jednokratnog lokalnog composea
```

```
Paket: F2-T02 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP01 s predloženim izmjenama D37; autoriziram samo F2-T02"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP01 prihvaćen 2026-11-24 (kod 8599382, CI run 45454710907, izvještaj 3ff9837)
Zabranjeno izričito: T03–T13, merge u main, deployment, zajednička infrastruktura, promjena Compose/Traefik
```

```
Paket: F2-T03 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP02; autoriziram samo F2-T03"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D17 (F1 amandman) i D31 uključeni; D42 OPEN | Preduvjet: F2-CP02 prihvaćen 2026-11-24 (kod 6431679, CI run 45456078051)
Zabranjeno izričito: T04–T13, merge u main, deployment, zajednička infrastruktura, primjena migracija na trajnu bazu
```

```
Paket: F2-T04 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP03; autoriziram samo F2-T04"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP03 prihvaćen 2026-11-24 (kod 8fb61e5, CI run 45458303174)
Zabranjeno izričito: T05–T13, merge u main, deployment, zajednička infrastruktura, primjena migracija na trajnu bazu
```

```
Paket: F2-T05 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP04; autoriziram samo F2-T05"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP04 prihvaćen 2026-11-24 (kod bfbda04, CI run 45460844674)
Zabranjeno izričito: T06–T13, merge u main, deployment, zajednička infrastruktura, primjena migracija na trajnu bazu
```

```
Paket: F2-T06 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP05; autoriziram samo F2-T06"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP05 prihvaćen 2026-11-24 (kod 3f64cfd, CI run 45463940778)
Napomena prihvaćena uz CP05 (potvrda odstupanja): rotacija credential_hash dopuštena; CSRF token se izvodi iz vjerodajnice (bez stupca); razlog SESSION_LIMIT dodan
Zabranjeno izričito: T07–T13, merge u main, deployment, zajednička infrastruktura, izmjena Compose/Traefik (D13 ostaje live stavka)
```

```
Paket: F2-T07 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP06; autoriziram samo F2-T07" (potvrđeno: "Nastavi s F2-T07 čim CI za T06 prođe")
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP06 prihvaćen 2026-11-24 (kod e2736d6, CI run 45467370715 zelen; prihvaćanje je dano prije izvještaja, CI je potvrđen tek nakon)
Zabranjeno izričito: T08–T13, merge u main, deployment, zajednička infrastruktura, izmjena Compose/Traefik
```

```
Paket: F2-T08 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP07; autoriziram samo F2-T08"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP07 prihvaćen 2026-11-24 (kod 850316b, CI run 45469542994)
Prihvaćena odstupanja uz CP07: bez Idempotency-Key (jedinstveni indeks), GET /sessions bez cursora (max 10), mobilne sesije bez UA veze, migracija 0006
Zabranjeno izričito: T09–T13, merge u main, deployment, zajednička infrastruktura, implementacija AT-03 (članstva, tenanti, poslovnice)
```

```
Paket: F2-T09 | Datum: 2026-11-24
Tekst autorizacije vlasnika (doslovno): "Prihvaćam CP08; autoriziram samo F2-T09"
Prihvaćene odluke: D01–D41 (D37 izmijenjen), D43; D42 OPEN | Preduvjet: F2-CP08 prihvaćen 2026-11-24 (kod dd7f492, CI run 45472663659)
Prihvaćena odstupanja uz CP08: bez Idempotency-Key na promjeni workspacea, dvostruka autentikacija guard + request_scope, USER guard ne zove port, branch_ids = samo odabrana poslovnica
Ograničenje (D37): tok promjene e-maila se NE implementira dok vlasnik ne potvrdi predloženi detalj prijavnog imena (prijedlog ide u izvještaj CP09)
Zabranjeno izričito: T10–T13, merge u main, deployment, zajednička infrastruktura, izmjena Compose/Traefik
```

## 4. Checkpointovi
| CP | Nakon | Što vlasnik prihvaća | Dokaz |
|---|---|---|---|
| **F2-CP00** | Planiranje (ova dokumentacija) | **PRIHVAĆEN 2026-11-24**: opseg, paketi, D01–D41 i D43; autorizacija samo T01 | Docs commit 0e5a2d1 |
| F2-CP01 | T01 | **PRIHVAĆEN 2026-11-24** (D37 izmijenjen): ishodi spika S1–S10, realm, CI Keycloak | CI run 45454710907 + `F2-KEYCLOAK-SPIKE-REPORT.md` |
| F2-CP02 | T02 | **PRIHVAĆEN 2026-11-24**: validacija tokena, lažni IdP | CI run 45456078051 (kod 6431679) |
| F2-CP03 | T03 | **PRIHVAĆEN 2026-11-24**: audit shema + D17 | CI run 45458303174 (kod 8fb61e5) |
| F2-CP04 | T04 | **PRIHVAĆEN 2026-11-24**: `users` i životni ciklus | CI run 45460844674 (kod bfbda04) |
| F2-CP05 | T05 | **PRIHVAĆEN 2026-11-24**: `user_sessions`, opoziv, konkurentnost | CI run 45463940778 (kod 3f64cfd) |
| F2-CP06 | T06 | **PRIHVAĆEN 2026-11-24**: web tok, kolačić, CSRF | CI run 45467370715 (kod e2736d6) |
| F2-CP07 | T07 | **PRIHVAĆEN 2026-11-24**: mobilni tok | CI run 45469542994 (kod 850316b) |
| F2-CP08 | T08 | **PRIHVAĆEN 2026-11-24**: pipeline konteksta, port AT-03, cross-tenant | CI run 45472663659 (kod dd7f492) |
| F2-CP09 | T09 | Sigurnosne politike i anti-enumeracija | CI run, [bilješke T09](F2-T09-SECURITY-POLICY-NOTES.md) (rezultati spika naspram implementacije, prijedlog za D37) |
| F2-CP10 | T10 | `platform_grants`, eskalacije, bootstrap | CI run, pregled migracije 0006 |
| F2-CP11 | T11 | Admin korisnika, outbox, KC događaji | CI run, pregled migracije 0007 |
| F2-CP12 | T12 | Zamrznuti API ugovor | CI run, OpenAPI diff, klijenti |
| **F2-CP13** | T13 | **Završno prihvaćanje F2** (AC matrica, rizici, preostale odluke) | `F2-FINAL-ACCEPTANCE-EVIDENCE.md`, CI run na točnom SHA |
Prihvaćanje je **zasebno** od merge-a u `main`, release-a i deploymenta; svaki traži vlastitu autorizaciju. Nakon CP13: F3a ostaje blokiran do usklađivanja AT-03 (G6 pravilo 4).
