# F2 — Plan implementacije (AT-02 + minimalni AT-17)

Datum: 2026-11-24 | Status: **CP00 prihvaćen 2026-11-24; D01–D41, D43 ACCEPTED; autoriziran samo F2-T01**
[Specifikacija AT-02](../specifications/AT-02-identity-security.md) · [Registar odluka](F2-DECISION-REGISTER.md) · [Execution order](F2-EXECUTION-ORDER.md) · [Kriteriji](F2-ACCEPTANCE-CRITERIA.md)

## 1. Sažetak
F2 isporučuje: Keycloak realm kao kod i test okruženje, validaciju tokena, `users`, `user_sessions`, `platform_grants`, `audit_events` (+ pomoćni `identity_outbox`), web BFF i mobilni tok, trenutačni opoziv, sigurnosne politike, API ugovore i testove. **13 implementacijskih paketa (F2-T01–T13)**, **14 checkpointova (F2-CP00–CP13)**. Svaki paket je zaseban, s vlastitom autorizacijom i STOP-om. Nema poslovnih modula, deploymenta ni pristupa zajedničkoj infrastrukturi.

## 2. Rezultat analize stanja (grana `dev`, HEAD 0c11559)
### 2.1 Pročitano
MASTER-BLUEPRINT, G6, DESIGN-ROADMAP (§3, §5 F2, R07/R11), FOUNDATION-G5-REVIEW, F1-RECONCILIATION-PLAN, F1-FINAL-ACCEPTANCE-EVIDENCE, AT-01 v1.1 (§5–7, §10, §10a), AT-03 potvrđene odluke i završni prijedlog, tenant-membership, AT-04, ADR-001…ADR-011 (posebno 001, 002, 003, 004, 008, 009, 010), `app/**`, `migrations/`, `scripts/db/harden.sql`, `docker-compose*.yml`, `tests/` (nazivi), `docs/DEVELOPMENT.md` (naslovi).

### 2.2 Što F1 već daje (ponovno se koristi, ne reimplementira)
| F1 komponenta | Datoteka | Uloga u F2 |
|---|---|---|
| `RequestContext`, `apply_context`, `session_scope` (autobegin=False, tx-lokalni `set_config`) | `app/core/db.py` | Jedini put do baze; auth pipeline ga ponovno koristi (D17: aditivno proširenje) |
| SQL `app_user_id()`, `app_tenant_id()`, `app_branch_ids()` | `migrations/versions/0001_baseline.py` | RLS politike F2 tablica |
| Četiri DB role, owner-only migracije, `harden.sql`, `dbroles`, mandatory `expected_owner` | `app/core/dbroles.py`, `scripts/db/harden.sql`, `migrations/env.py` | Role i privilegije novih tablica |
| RLS test harness (probna tablica, non-owner role, forged context, pool reuse) | `tests/rls_probe.py`, `tests/test_rls*.py` | Cross-tenant i bootstrap testovi F2 |
| RFC 9457 greške + kodovi | `app/core/errors.py`, `app/api/errors.py` | Katalog grešaka F2 (spec §10.4) |
| Idempotencija, cursor paginacija, ETag/If-Match | `app/core/idempotency.py`, `pagination.py`, `versioning.py` | Mutacije i liste F2 |
| Redis limiter (sliding window, Lua, fail-closed 503, trusted proxy IP) i `by_principal`/`by_tenant` | `app/core/ratelimit.py` | Limiti ruta prijave; **zahtijeva da auth postavi `request.state.principal_id/tenant_id`** (do sada nitko ne postavlja) |
| Rezervirani ključevi `RATE_LIMIT_KEYCLOAK_MAX_FAILED_LOGINS`, `…FAILURE_WINDOW_MINUTES`, `RATE_LIMIT_PASSWORD_RECOVERY_PER_HOUR` | `app/core/config.py` | Izvor vrijednosti za realm linter i test; semantika recovery limita mijenja se (D20) |
| OpenAPI izvoz, drift, validator, TS/Dart generiranje u CI | `app/api/openapi.py`, `openapi/` | Ugovor F2 |
| CI (PG16/Redis7 service containeri, `-W error`, nula preskočenih, gitleaks, pip-audit) | `.github/workflows/ci.yml` | Proširuje se Keycloak containerom |
| Zapisnici s redakcijom, request ID, health | `app/core/logging.py`, `request_context.py` | Zabrana tajni u logovima |
| Compose `keycloak` servis (26.4.7, zasebna baza po okruženju), `worker`/`beat` definirani (modul `app.celery_app` ne postoji) | `docker-compose*.yml` | Samo se **čitaju**; ne mijenjaju se u F2 |

### 2.3 Što nedostaje (F2 gradi)
`app/auth`, `app/audit`, `app/platform` su prazni (`.gitkeep`); nema tablica osim funkcija iz 0001; nema JWT validacije, Keycloak realma, sesija, kolačića/CSRF-a, platformskih ovlasti, audit zapisa, Celery aplikacije, Keycloak testnog okruženja, migracija za F2. Nema bootstrap konteksta za lookup sesije prije poznatog `app.user_id` (D17).

### 2.4 Provjera novijih dokumenata koji zamjenjuju starije zapise
- Pointer na vrhu G6/Blueprinta („F2: READY FOR PLANNING", release opcija 3) **zamjenjuje** ranije „F1 not authorized/pending" zapise; vrijedi samo za planiranje.
- ADR-010 (2026-11-24) **zamjenjuje** ADR-001 „OIDC provider to be selected"; ADR-011 zamjenjuje S3 klauzulu. ADR-010 ostavlja otvorene: realm/klijenti, oporavak, MFA centralnih/profesionalnih, trajanja → ovdje PROPOSED.
- AT-03 završni prijedlog je i dalje **PROPOSED** (nije Approved): njegovih 30 min/12 h, 30 min reset i 24 h podrška **nisu** potvrđeni; potvrđeno je 27 odluka (#12, #18, #19, #20, #21, #24 relevantne). Konačno usklađivanje je prije F3a (G6 pravilo 4).
- Nema zapisa koji bi opozvao I01–I20.

### 2.5 Neusklađenosti i praznine nađene u izvorima (rješavaju se u registru)
| # | Nalaz | Rješenje |
|---|---|---|
| 1 | G6 6a: „oporavak lozinke 3/h konfigurira se u Keycloaku". Keycloak nema nativni limit po računu (nepotvrđeno do spika S2) | D20 — aplikacijski mehanizam; **odstupa od formulacije G6**, traži potvrdu |
| 2 | G5-02 zabranjuje SECURITY DEFINER prečac, a lookup sesije/korisnika zbiva se prije `app.user_id` | D17 — dva dodatna bootstrap konteksta (F1 aditivni amandman) |
| 3 | G5-05 spominje `app.actor_id`; F1 ima samo `app.user_id` | Aktor = `app.user_id`; bez novog konteksta |
| 4 | ADR-010: web = HttpOnly kolačić; G5-07/AT-01: `api.` zaseban host → host-only kolačić ne stiže do `api.`; `Domain=` kolačić teče prema `dev.` poddomeni | D12, D13 (isti origin za preglednik) |
| 5 | `RateLimitSettings` komentar: Keycloak vrijednosti „provodi Keycloak, ne aplikacija" | Ažurirati komentar i semantiku u T09 (aplikacija provodi recovery limit) |
| 6 | Compose `worker`/`beat` pokazuju na nepostojeći `app.celery_app` | D33 — T11 uvodi modul |
| 7 | Keycloak `auth.` router javno izlaže cijeli Keycloak (admin konzola) | D43 — live preduvjet, izvan F2 koda |
| 8 | AT-01 §4: DNS dokument navodi `/v1/`, ostalo `/api/v1/` | Poznato; F2 koristi `/api/v1/` |
| 9 | `partners.`/`clientes.` DNS zapisi vs. jedan origin | Nema utjecaja na F2 (I18) |
| 10 | `ADR-003 users.status` bez nabrojanih vrijednosti | D10 |

## 3. Strategija isporuke
**Redoslijed i razlozi.** T01 prvo dokazuje Keycloak pretpostavke (spike) jer D19/D20/D23 ovise o njima; T02 token validacija i lažni IdP; T03 audit *prije* ostalih tablica (svi kasniji paketi pišu audit i nema FK ovisnosti); T04 `users`; T05 `user_sessions`; T06 web tok; T07 mobilni tok; T08 kontekst/workspace/port; T09 sigurnosne politike; T10 `platform_grants`; T11 platformska administracija korisnika + outbox + obavijesti + KC događaji; T12 zamrzavanje API ugovora; T13 završna validacija bez novih funkcionalnosti.
**Granice i dopuštene putanje:** D35. **Nova ovisnost:** `PyJWT[crypto]` (D34), eventualno `celery` (već u stacku, D33); svaka prolazi `uv lock --check` i pip-audit.
**Migracije (sekvencijalno, svaka reverzibilna, owner rola):** `0002_auth_bootstrap_context` (D17: funkcije `app_auth_subject()`, `app_session_hash()`; samo ako D17 bude prihvaćen), `0003_audit_events` (T03), `0004_users` (T04), `0005_user_sessions` (T05), `0006_platform_grants` (T10), `0007_identity_outbox` (T11). Redoslijed ovisnosti je normativan; ako D17 bude odbijen, numeracija se pomiče, a T03–T05 se prilagođavaju alternativi (SECURITY DEFINER lookup) uz novi pregled. Migracije se izvode samo na jednokratnoj/CI bazi; **nijedna se ne primjenjuje na trajnu DEV/PROD bazu** (R05).
**Što F2 ne dira:** Compose, Traefik, `.secrets/`, shared PostgreSQL, Nextcloud, mail server, frontend, Flutter.

## 4. Plan testiranja (F2.08)
Načela iz F1: stvarni PostgreSQL 16 i Redis 7 (ne SQLite), CI-only integracija, nula preskočenih testova (junit gate), `-W error` uz postojeći jedini dopušteni izuzetak, ponavljanje nestabilnih (rate-limit) testova, neovisna validacija OpenAPI-ja.

| Sloj | Što pokriva | Paketi |
|---|---|---|
| **Unit** | validacija claimova (svaki negativni slučaj zasebno), normalizacija e-maila, matrica prijelaza statusa, izračun isteka sesije, CSRF usporedba, hash vjerodajnice, allowlist/validator audita, izračun roka granta, parsiranje `return_to`, HMAC ključ limitera | T02–T11 |
| **Integracijski (PG16+Redis7)** | repozitoriji, `session_scope` + bootstrap kontekst, outbox obrada, limiteri, cijeli auth pipeline s lažnim IdP-om | T03–T11 |
| **Keycloak/OIDC** (KC 26.4.7 container) | web code+PKCE i callback; mobilni tok; ID/access token claimovi; JWKS i rotacija ključa; backchannel logout; refresh rotacija i reuse; brute-force (5/15 min); `kc_action`; step-up LoA2; admin API (onemogući, odjavi, execute-actions-email, events); uvoz realma | T01, T02, T06, T07, T09, T11 |
| **PostgreSQL + RLS** | FORCE RLS na svim novim tablicama, 0 redaka bez konteksta, tuđi redak nevidljiv/needitabilan, WITH CHECK, bootstrap politike ne otkrivaju druge retke, platform rola bez granta = 0 redaka, app rola nije owner/BYPASSRLS, `SET ROLE` odbijen, column GRANT na `status`, append-only audit (UPDATE/DELETE/TRUNCATE odbijeni za sve role), triggeri statusa/granta | T03–T05, T10, T11 |
| **Negativni sigurnosni** | none-algoritam, HS256 s javnim ključem, krivi `iss`/`aud`/`azp`, istekao/`nbf`, krivi `kid`, ID token kao access token, manipuliran kolačić, ponovljen `state`/`nonce`/`logout_token`, CSRF bez/pogrešnog tokena i krivi `Origin`, open redirect `return_to`, kolačić+bearer istodobno, fiksacija sesije (nova vjerodajnica pri prijavi), UA promjena, enumeracija (usporedba odgovora postojeći/nepostojeći račun: status, tijelo, zaglavlja, vrijeme unutar tolerancije), samododjela granta, eskalacija tipa, last grant admin, tajne u logovima/auditu, SQL injection u filtere | T02, T06–T11 |
| **Cross-tenant** | uz `MembershipAuthorizer` dvojnik i probne tenant tablice: klijentski `tenant_id` ignoriran, tuđi tenant → 404 `WORKSPACE_NOT_FOUND`, cross-tenant read/write/join odbijeni na API **i** DB razini, kontekst jedne sesije ne curi u drugu, worker ne vjeruje poruci, platformski grant ne otvara tenant podatke, pool reuse ne prenosi bootstrap kontekst | T05, T08, T10 |
| **Opoziv sesija i ovlasti** | odjava, opoziv pojedine/ostalih/svih, deaktivacija i blokada (sljedeći zahtjev 401/403), promjena lozinke opoziva ostale, backchannel logout, opoziv članstva (dvojnik) odmah, opoziv granta odmah, istek granta, istek idle/apsolutni, KC ispad ne vraća opozvanu sesiju | T05–T11 |
| **Konkurentni zahtjevi** | opoziv vs. zahtjev u tijeku (`FOR SHARE/UPDATE` redoslijed), paralelni prvi login istog `sub`, paralelna promjena konteksta (`context_version` → 412), paralelno odobrenje granta (jedan pobjednik), deaktivacija vs. login, 11. sesija (evikcija najstarije), paralelni recovery zahtjevi (limit točan), duplicirana ingestija KC događaja | T04–T11 |
| **Istek i neispravni tokeni** | `exp` granica ±30 s, `nbf`, istekla sesija, istekao step-up, istekao grant, istekao recovery link (KC), `logout_token` bez `events`, prazni/pogrešni zaglavlje, preveliki token | T02, T05–T09 |
| **Migracije i rollback** | upgrade head → downgrade base → upgrade (kao F1 korak), role SQL dvaput, odbijanje ne-owner rola, F2 migracije ne dodjeljuju privilegije izvan harden.sql modela, downgrade ne ostavlja funkcije/trigger-e, ispravno `REVOKE` na `audit_events` | T03–T05, T10, T11, T13 |
| **OpenAPI contract** | odgovori = ugovor (postojeći contract test), sigurnosne sheme prisutne na svakoj operaciji, svaka operacija ima `x-authorization`, kodovi grešaka iz kataloga, drift check, validator, TS i Dart generiranje (Dart bez analize, R10) | T06–T12 |
| **CI sigurnost** | gitleaks cijela povijest, pip-audit, realm linter, pripijeni digest KC image-a, provjera da nijedan CI job nema deploy/secret, scope guard (D40), skeniranje logova i audit zapisa na tajne, opcionalno (ne blokira, dokumentirano) skeniranje KC image-a | T01, T13 |

**Ciljevi pokrivenosti:** svaki AC iz [F2-ACCEPTANCE-CRITERIA](F2-ACCEPTANCE-CRITERIA.md) ima barem jedan imenovani test i barem jedan negativni test; matrica AC→test generira se i provjerava u T13 (test koji ne postoji = pad). Brojke testova se ne obećavaju unaprijed.

## 5. CI proširenja (T01 i T13, unutar `.github/workflows/**`)
1. Job `identity-integration`: Keycloak service container (digest), uvoz `identity/keycloak/realm-test.json`, health čekanje, pytest marker `keycloak` (bez skip-a: u CI-u obvezan).
2. Realm linter i scope guard kao obični testovi (rade i bez Keycloaka).
3. Postojeći korak „owner-migration" proširen na F2 migracije.
4. Bez novih tajni i bez deploy koraka; `permissions: read` ostaje (guard `tests/test_ci_workflow.py` se proširuje).

## 6. Rizici i blokeri
| ID | Rizik / bloker | Učinak | Ublažavanje | Vrsta |
|---|---|---|---|---|
| RF2-01 | Keycloak nema nativni limit oporavka po računu | G6 formulacija neizvediva kako piše | D20 (aplikacijski), spike S2 | Odluka (potvrda) |
| RF2-02 | D17 mijenja F1 kontekst (aditivno) | Bez odobrenja T03–T05 ne mogu | Alternativa SECURITY DEFINER | **Bloker T03–T05** |
| RF2-03 | Kolačići preko `api.`/poddomena (DEV pod PROD domenom) | Curenje/prepisivanje kolačića | `__Host-`, isti origin (D12/D13) | Infrastruktura (live) |
| RF2-04 | Značajke Keycloaka (LoA, recovery kodovi, `kc_action`, reuse detection) nepotvrđene na 26.4.7 | Dizajn se mijenja | Spike S1–S10 u T01 s STOP-om | Bloker T06+ do CP01 |
| RF2-05 | Nema transakcijskog e-mail providera (O15), mail server nije produkcijski | Verifikacija/oporavak/obavijesti rade samo DEV (Mailpit) | F2 samo DEV/CI; PROD blokiran | Live preduvjet |
| RF2-06 | Keycloak admin konzola javno izložena preko `auth.` | Površina napada | D43, izvan F2 koda | Live preduvjet |
| RF2-07 | Keycloak baza/rola nisu provisionirane; provisioning skripta ≠ harden.sql (R11); PUBLIC grantovi (O06) | Nema live Keycloaka | F2 samo lokalno/CI; R05/R11/R12 ostaju | Live preduvjet |
| RF2-08 | Preostala enumeracija pri Keycloak registraciji | Otkriva postojanje e-maila | D26 prihvaćanje rizika / kasnije API registracija | Odluka |
| RF2-09 | Bootstrap prvog administratora | Kokoš-jaje ili backdoor | D30 CLI + audit, DEV only | Odluka |
| RF2-10 | AT-03 nije usklađen; nema tenanta/članstva | Workspace testiran samo dvojnicima; bez FK | Port (D18), FK u F3a | Granica |
| RF2-11 | Ispad Keycloaka | Blokira prijavu i mobilni refresh nakon ≤ 5 min; web sesije traju | ADR-010 posljedica; `IDENTITY_PROVIDER_UNAVAILABLE`; monitoring O11 | Prihvaćeno u ADR-010 |
| RF2-12 | Service account `at-admin-svc` visokovrijedna tajna | Kompromitacija = upravljanje korisnicima | Minimalne uloge, rotacija, samo worker ga koristi | Tehnički |
| RF2-13 | Kašnjenje ingestije KC događaja (≤ 2 min) | Neuspješne prijave nisu odmah u auditu | Dokumentirano; ne utječe na autorizaciju | Prihvaćeno |
| RF2-14 | Dart analiza odgođena (R10) | Mobilni ugovor nije kompajliran | Nasljeđeni rezidual; zasebna odluka | Nasljeđeno |
| RF2-15 | GDPR/retencija (IP prefiks, uređaji, audit) | Pravna osnova nepotvrđena | Minimizacija; D42 OPEN → AT-20 | Pravno |
| RF2-16 | Opseg F2 raste prema AT-03 (npr. „samo malo članstva") | Ponovno miješanje faza | Port + STOP uvjeti; scope guard | Governance |
| RF2-17 | Keycloak CVE/nadogradnje | Sigurnosni dug | Pin + upit za nadogradnju; ne mijenja se bez odobrenja | Operativno |
**Blokeri za početak implementacije:** (1) izričita autorizacija vlasnika za F2-T01; (2) odobrenje D17 prije T03; (3) potvrda D20; (4) potvrda D15/D22 (trajanja, MFA) prije T05/T09 — mogu ići kao konfiguracijske zadane vrijednosti s PROPOSED oznakom ako vlasnik tako odluči.

## 7. Governance iz iskustva F1 (D40)
| Što je F1 trebalo reconciliation | F2 pravilo |
|---|---|
| Povijesna „široka autorizacija" bez izvornog zapisa (UNVERIFIED) | Autorizacija svakog paketa zapisuje se u repo **prije** koda (`docs/design/F2-EXECUTION-ORDER.md` „Zapis autorizacije"), s tekstom vlasnika i datumom |
| CP02–CP09 nikad pojedinačno prihvaćeni, prihvaćeni kolektivno | Svaki CP prihvaća vlasnik zasebno; sljedeći paket ne počinje bez zapisa |
| Radno stanje na zasebnoj grani, kasnije spajanje | Samo `dev`; mali commitovi po koraku; CI run na točnom SHA |
| Dokumentirani status razišao se s kodom | Pointer statusa ažurira se uz svaki CP; docs-only commit odvojen od koda |
| Opseg nejasan (maintenance, DNS, AT-05 u istom diffu) | `tests/test_f2_scope.py` (dopuštene putanje, D35) + izričiti pregled diffa na CP-u |
| Sigurnosni nalazi tek na kraju (R01–R15) | Negativni sigurnosni testovi uz svaki paket; T13 samo potvrđuje i ne uvodi nove funkcije; nalaz P0 zaustavlja paket |
| Shema migracije osporena (0002) | Migracije samo uz pregled prije primjene; nikad na trajnu bazu bez R05 dokaza |
| Test brojevi kao dokaz | Dokaz = CI run + SHA + junit (0 skipped) + matrica AC→test |

## 8. Preduvjeti za bilo što izvan dev/CI (nije dio F2, nasljeđeno)
R05 (stanje migracija trajne baze), R11 (provisioning skripta vs `harden.sql`, uključujući Keycloak bazu), R12/O20 (readiness), `TRUSTED_PROXY_CIDRS`, O06–O17, D13 i D43 (Traefik/Compose), O15 (mail), AT-20 pravni okvir. Svaka traži zasebnu autorizaciju.

## 9. Pregled paketa
| Paket | Naziv | CP | Migracije | Ovisi o |
|---|---|---|---|---|
| F2-T01 | Keycloak realm kao kod, test okruženje, spike S1–S10 | CP01 | — | CP00 |
| F2-T02 | Konfiguracija auth modula, validacija tokena, lažni IdP | CP02 | — | CP01 |
| F2-T03 | `audit_events` + bootstrap kontekst (D17) | CP03 | audit, bootstrap | CP02 |
| F2-T04 | `users`, povezivanje, životni ciklus | CP04 | users | CP03 |
| F2-T05 | `user_sessions` i servis sesija | CP05 | user_sessions | CP04 |
| F2-T06 | Web tok: login/callback/logout, kolačić, CSRF, backchannel, step-up | CP06 | — | CP05 |
| F2-T07 | Mobilni tok: bearer, otvaranje sesije, uređaji | CP07 | — | CP05 (paralelno moguće s T06 uz odobrenje) |
| F2-T08 | Pipeline konteksta, workspace, `MembershipAuthorizer` port | CP08 | — | CP06, CP07 |
| F2-T09 | Sigurnosne politike: oporavak, promjena lozinke/e-maila, MFA, enumeracija, obavijesti (port) | CP09 | — | CP08 |
| F2-T10 | `platform_grants`, autorizacija, bootstrap | CP10 | platform_grants | CP08 |
| F2-T11 | Platformska administracija korisnika, outbox, Celery, KC događaji, notifikacije | CP11 | identity_outbox | CP09, CP10 |
| F2-T12 | Zamrzavanje API ugovora, OpenAPI, klijenti, dokumentacija grešaka | CP12 | — | CP11 |
| F2-T13 | Završna validacija i dokaz prihvaćanja | CP13 (završni) | — | CP12 |
