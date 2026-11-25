# F2 — Kriteriji prihvaćanja

Datum: 2026-11-24 | Status: **ACCEPTED uz CP00 (2026-11-24)** | Povezano: [Execution order](F2-EXECUTION-ORDER.md) · [Plan §4](F2-IMPLEMENTATION-PLAN.md) · [AT-02](../specifications/AT-02-identity-security.md) · [Registar](F2-DECISION-REGISTER.md)

> **F2-T09-REC Keycloak Security Upgrade (2026-11-25, D45):** Keycloak 26.8.2 umjesto 26.4.7; AC-CTX-01 preformuliran (očuvana F1 sigurnosna jamstva umjesto doslovno nepromijenjenih testova); izvor geolokacije za AC-SES-10 odgođen do T11.
>
> **F2-T09-REC:** [Izvještaj CP09 s dokazom po kriteriju](F2-CP09-RECONCILIATION-REPORT.md#8-acceptance-matrix-t01t13) bilježi trenutne rezultate i nedostatke. Kriteriji ostaju normativni; CP09 nije prihvaćen (stanje 2026-11-25, nakon neovisne revizije i korekcija F2-CP09-REC, D46: 80 PASS, 5 PASS s prihvaćenim odstupanjem, **7 PARTIAL** (T10/T11), 34 DEFERRED; **AC-POL-10 PASS**; KC-SP-12 PASS uz vremenski ograničeno prihvaćanje vlasnika). Odluke vlasnika F-2 i F-3 preciziraju AC-POL-06 i AC-POL-10: svježina se mjeri od stvarne provjere faktora, a osoba s MFA-om mora faktor dokazati za osjetljive radnje. Migracija 0007 pripada D37, 0008 izolaciji konteksta i audita, a 0009 razrješenju D37 (F-4): brojevi u AC-PLT-12 (0006), AC-ADM-10 (0007) i raspon u §13.2 čitaju se kao sljedeći slobodni brojevi (od 0010).

## Pravila dokazivanja
- Kriterij vrijedi samo uz **dokaz**: imenovani test u CI runu na točnom SHA-u (3+1 job zelen, 0 skipped, `-W error`), ili pregledan artefakt naveden u koloni „Dokaz". Tvrdnja bez dokaza = nije ispunjeno.
- Svaki AC ima barem jedan pozitivan i (gdje je sigurnosni) barem jedan **negativan** test. Matricu AC→test provjerava `tests/test_f2_traceability.py` (T13): AC bez testa ruši CI.
- Ishodi: **PASS**, **BOUNDED** (ispunjeno uz izričito prihvaćeno ograničenje; vlasnik odobrava), **FAIL**. BOUNDED nikad nije zadano.
- Kriteriji koji ovise o PROPOSED odluci vrijede tek kad je ta odluka ACCEPTED; inače se mjere prema konfiguracijskoj zadanoj vrijednosti označenoj PROPOSED.

## 1. Keycloak (T01) — F2.01
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-KC-01 | Realm JSON za DEV/test uvozi se u svježi KC 26.8.2 container bez ručnih koraka (do 2026-11-25: 26.4.7; D45) | CI `identity-integration` |
| AC-KC-02 | Linter realma odbija: wildcard redirect, implicit, direct grants, javni klijent s tajnom, tajnu u JSON-u, `verifyEmail=false`, `resetPasswordAllowed=true`, brute-force ≠ 5/15 min | test linter + negativni primjeri |
| AC-KC-03 | Za DEV i PROD postoje odvojeni realmovi/konfiguracija bez zajedničkih tajni i klijenata | linter + pregled |
| AC-KC-04 | Spike izvještaj daje POTVRĐENO/OPOVRGNUTO za S1–S10 s dokazom | `F2-KEYCLOAK-SPIKE-REPORT.md` |
| AC-KC-05 | Rotacija realm ključa vježbana: token starog i novog ključa prolazi, nepoznat `kid` ne ruši servis | KC test |
| AC-KC-06 | CI koristi image po digestu; nijedan test ne dira zajednički Keycloak/PostgreSQL | pregled workflowa + guard test |

## 2. Validacija tokena (T02)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-TOK-01 | Valjan KC token prolazi; sve provjere D05 provode se | KC + unit |
| AC-TOK-02 | Odbijeni: `alg=none`, HS256 potpisan javnim ključem, nepodržan alg | negativni unit |
| AC-TOK-03 | Odbijeni: krivi `iss`, `aud`, `azp`, `typ`; ID token kao access token | negativni unit |
| AC-TOK-04 | `exp`/`nbf` granice ±30 s točne s oba smjera | unit |
| AC-TOK-05 | Nepoznat `kid` pokreće najviše jedan refetch/min; JWKS nedostupan s valjanim cacheom radi, bez cachea 503 | unit |
| AC-TOK-06 | Tokeni nikad u logovima, iznimkama, audit zapisima | test redakcije |
| AC-TOK-07 | Svaka provjera je nužna: uklanjanje bilo koje dovodi do pada barem jednog testa | mutation skup |
| AC-TOK-08 | Preveliki/neispravno oblikovani token → 401 bez 500 | unit |

## 3. Audit (T03, T11)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-AUD-01 | `UPDATE`, `DELETE`, `TRUNCATE` na `audit_events` odbijeni za app, worker i platform rolu; trigger odbija i direktni pokušaj | PG test |
| AC-AUD-02 | FORCE RLS: bez konteksta 0 redaka; platform bez `PLATFORM_AUDIT_VIEW` 0 redaka; korisnik vidi samo vlastite AUTHN/SESSION/SECURITY_SETTING | PG test |
| AC-AUD-03 | CHECK: `scope=TENANT` bez `tenant_id` odbijen; bez FK na users | PG test |
| AC-AUD-04 | Validator odbija ključeve i vrijednosti nalik tajnama (lozinka, token, cookie, secret, JWT/Bearer); e-mail se ne zapisuje; IP samo prefiks | fuzz + katalog test |
| AC-AUD-05 | Svaka akcija iz kataloga ima tipizirani allowlist `details` | test kataloga |
| AC-AUD-06 | Dedup `source_event_id` | PG test |
| AC-AUD-07 | Migracija 0003 up/down/up; privilegije prema modelu rola | CI migracijski korak |
| AC-AUD-08 | Uspješna i neuspješna prijava, odjava, promjena sigurnosnih postavki, opoziv sesije, promjena konteksta, promjena ovlasti, administrativne radnje i neautorizirani pokušaji zapisuju događaj | integracijski testovi po katalogu |
| AC-AUD-09 | Radnja i njezin audit su atomarni (rollback radnje briše i audit; sigurnosni neuspjeh se zapisuje neovisno) | PG test |
| AC-AUD-10 | KC ingestija: bez duplikata, otporna na ponavljanje i pad, bez reprezentacije/tajni | integracijski |
| AC-AUD-11 | Pregled i pretraga audita su i sami auditirani; filteri i cursor paginacija ispravni | API test |

## 4. Kontekst i izolacija (T03, T08)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-CTX-01 | D17 je aditivan: **sva prethodno prihvaćena F1 sigurnosna jamstva su očuvana** i svi F1 testovi zeleni. Izmjene i proširenja F1 testova dopuštene su samo ako nijedno jamstvo nije uklonjeno, nijedna tvrdnja oslabljena, a ekvivalentnost starih i novih provjera dokumentirana i dokazana (matrica ekvivalentnosti u izvještaju CP09). Preformulirano odlukom vlasnika 2026-11-25 (D45); prije: "svi F1 testovi neizmijenjeni i zeleni" | CI + matrica ekvivalentnosti |
| AC-CTX-02 | Bootstrap kontekst ne curi između konekcija iz poola ni transakcija | PG test |
| AC-CTX-03 | Bootstrap kontekst postavlja isključivo auth modul; ne otkriva tuđe retke | statički test + PG test |
| AC-CTX-04 | Klijentski `tenant_id`/`branch_id` (header/body/path/query) ne mijenja kontekst | API test |
| AC-CTX-05 | Tuđi i nepostojeći tenant daju identičan 404 `WORKSPACE_NOT_FOUND` | API test |
| AC-CTX-06 | Opoziv članstva, promjena uloge, uklonjena poslovnica djeluju na sljedeći zahtjev (dvojnik) | integracijski |
| AC-CTX-07 | Dvije sesije istog korisnika imaju neovisan kontekst | integracijski |
| AC-CTX-08 | Promjena konteksta: If-Match/`context_version`, 412 pri trci, audit staro→novo | API/konkurentni |
| AC-CTX-09 | Cross-tenant čitanje, upis i join odbijeni na API i DB razini uz probne tablice | PG + API |
| AC-CTX-10 | Greška porta autorizatora → 503 (fail closed); `None` → bez konteksta | unit |
| AC-CTX-11 | `request.state.principal_id/tenant_id` samo iz validiranog konteksta; limiter se ne može zavarati | API test |
| AC-CTX-12 | Produkcijski wiring koristi `DenyAllAuthorizer`; testni dvojnik nije dostupan izvan testova | statički test |

## 5. Korisnici (T04) — F2.02
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-USR-01 | Prvi login stvara `users` po `sub` (JIT); status prema `email_verified` | integracijski |
| AC-USR-02 | Paralelni prvi login istog `sub` daje jedan redak | konkurentni |
| AC-USR-03 | Isti `email_normalized` pod drugim `sub` → odbijanje, audit, bez spajanja | integracijski |
| AC-USR-04 | `auth_subject` nepromjenjiv; UNIQUE na `auth_subject` i `email_normalized` | PG test |
| AC-USR-05 | Matrica prijelaza: svaki dopušteni par prolazi, svaki ostali odbijen; `ACTIVE` traži `email_verified_at` | PG + unit |
| AC-USR-06 | App rola ne može mijenjati `status`; platform samo uz grant | PG test |
| AC-USR-07 | RLS: vlastiti redak; tuđi nevidljiv i neizmjenjiv; INSERT s tuđim `sub` odbijen | PG test |
| AC-USR-08 | `users` nema tenant/customer/uloga/članstva stupaca (shema test) | schema test |
| AC-USR-09 | Normalizacija e-maila (NFKC, trim, lower); plus-adrese ostaju različite | unit |
| AC-USR-10 | Neverificirani korisnik: samo dopuštene rute; ostalo 403 `EMAIL_NOT_VERIFIED` | API test |

## 6. Sesije (T05) — F2.03
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-SES-01 | U bazi samo SHA-256 vjerodajnice; tajna se nigdje ne pohranjuje ni logira | test + sken |
| AC-SES-02 | Sesija je živa samo dok nije opozvana i nije prošla idle/apsolutni rok; istek bez cron-a | unit + PG |
| AC-SES-03 | Opoziv pojedinačne, ostalih i svih sesija djeluje na sljedeći zahtjev | integracijski |
| AC-SES-04 | Deaktivacija/blokada opoziva sve sesije u istoj transakciji; prijava nakon toga ne stvara sesiju | integracijski + konkurentni |
| AC-SES-05 | Opoziv vs. zahtjev u tijeku: redoslijed zajamčen `FOR SHARE/UPDATE` | konkurentni |
| AC-SES-06 | Max 10 sesija; 11. evakuira najstariju, paralelno ispravno | konkurentni |
| AC-SES-07 | RLS: tuđa sesija nevidljiva i neopoziva; platform samo uz grant | PG test |
| AC-SES-08 | `user_id`, `credential_hash`, `absolute_expires_at` nepromjenjivi iz app uloge | PG test |
| AC-SES-09 | Touch najviše 1×/60 s | unit |
| AC-SES-10 | UA promjena opoziva sesiju (`SECURITY_POLICY`); promjena države samo audit + obavijest. Izvor geolokacije: odluka odgođena do T11 (vlasnik 2026-11-25, D45) | integracijski |
| AC-SES-11 | Rotacija vjerodajnice pri prijavi i step-upu; stara odmah neupotrebljiva | integracijski |
| AC-SES-12 | Migracija 0005 up/down/up | CI korak |

## 7. Web tok (T06)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-WEB-01 | Cijeli tok login→sesija→zahtjev→odjava→401 protiv Keycloaka | KC integracija |
| AC-WEB-02 | Kolačić `__Host-at_session`: Secure, HttpOnly, SameSite=Lax, Path=/, bez Domain | test zaglavlja |
| AC-WEB-03 | `state`, `nonce`, PKCE jednokratni; replay i krivi nonce odbijeni | KC + negativni |
| AC-WEB-04 | Tokeni se ne pohranjuju ni ne vraćaju pregledniku | test + pregled |
| AC-WEB-05 | Sesija se rotira pri prijavi (nema fiksacije) | negativni |
| AC-WEB-06 | `return_to` samo relativna allowlist putanja (`//`, apsolutni, `\`, kodirani odbijeni) | negativni skup |
| AC-WEB-07 | CSRF: bez/pogrešan token ili krivi `Origin` na nesigurnoj metodi → 403 `CSRF_INVALID` + audit | negativni |
| AC-WEB-08 | Kolačić + bearer istodobno → 400 | negativni |
| AC-WEB-09 | Backchannel logout opoziva sesije; replay `jti`, krivi `iss`/`aud`, bez `events` odbijeni | KC + negativni |
| AC-WEB-10 | Step-up: `STEP_UP_REQUIRED`, uspjeh podiže `auth_level`, istek vraća zahtjev | KC integracija |
| AC-WEB-11 | `Cache-Control: no-store` na auth rutama; greške bez detalja | test zaglavlja |
| AC-WEB-12 | Limiti ruta D38 aktivni; Redis nedostupan → 503 | integracijski |

## 8. Mobilni tok (T07)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-MOB-01 | Valjan token bez sesije → `SESSION_REQUIRED`; `POST /auth/mobile/session` stvara sesiju idempotentno | integracijski |
| AC-MOB-02 | Pogrešan `azp`/`aud`/`sid`: odbijeno; token jednog korisnika ne otvara tuđu sesiju | negativni |
| AC-MOB-03 | Opozvana sesija odbija još valjani access token odmah | integracijski |
| AC-MOB-04 | Refresh reuse detection: ponovna uporaba → opoziv `REFRESH_REUSE` | KC integracija |
| AC-MOB-05 | Popis sesija samo vlastitih; tuđa → 404; opoziv radi | API test |
| AC-MOB-06 | Server ne pohranjuje refresh tokene | pregled + test |
| AC-MOB-07 | Paralelno otvaranje sesije istog `sid` daje jednu sesiju | konkurentni |
| AC-MOB-08 | Upute za klijenta (PKCE, Keystore/Keychain, redirect) dokumentirane | `F2-MOBILE-AUTH-NOTES.md` |

## 9. Autorizacija (T08, T10) — F2.05
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-AUTHZ-01 | Svaka ruta deklarira autorizaciju; ruta bez nje ne ulazi u OpenAPI/registar (deny by default) | test registra |
| AC-AUTHZ-02 | Autorizacija se čita iz baze na svakom zahtjevu; token/kolačić ne nose ovlasti | test |
| AC-AUTHZ-03 | Platformske i tenant ovlasti nezavisne: tenant uloga ne daje grant i obratno | test |

## 10. Sigurnosne politike (T09) — F2.04
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-POL-01 | 5 neuspjelih prijava u 15 min → 6. odbijen (privremeno); 5 prolazi | KC test |
| AC-POL-02 | Odgovor pri zaključavanju ne otkriva stanje računa | KC test |
| AC-POL-03 | Oporavak: max 3 poruke/h po računu (4. se ne šalje), po IP-u limit; odgovor uvijek identičan 202 | integracijski |
| AC-POL-04 | Enumeracija: postojeći/nepostojeći/deaktiviran račun nerazlučivi (status, tijelo, zaglavlja, vrijeme u toleranciji) | negativni |
| AC-POL-05 | Link oporavka jednokratan, 30 min; reset opoziva sve sesije i šalje obavijest | KC + integracijski |
| AC-POL-06 | Promjena lozinke/e-maila zahtijeva step-up; ostale sesije opozvane; obavijesti poslane | KC + integracijski |
| AC-POL-07 | Politika lozinke djeluje (duljina, blacklist, notUsername/Email) | KC test |
| AC-POL-08 | Autokuće bez MFA-a prijavljuju se normalno; MFA enrol dobrovoljan | KC test |
| AC-POL-09 | Korisnik s platformskim grantom bez MFA-a ne može koristiti platformske rute | negativni |
| AC-POL-10 | Step-up svježina i razina provode se po D23 popisu radnji | integracijski |
| AC-POL-11 | Obavijesti sadržavaju samo dopuštene podatke; DEV isporuka u Mailpit/fake; PROD slanje isključeno | test sadržaja |
| AC-POL-12 | Replay: `logout_token jti`, `state/nonce`, Idempotency-Key | negativni |
| AC-POL-13 | Krađa sesije: rotacija, UA veza, refresh reuse (vidi SES/MOB) | ref. |
| AC-POL-14 | `RateLimitSettings` dokumentacija/semantika ažurirana (recovery limit provodi aplikacija) | pregled + test config |

## 11. Platforma i minimalni AT-17 (T10, T11)
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-PLT-01 | Grant: obvezan istek (≤ limit), tip iz CHECK-a, `granted_by ≠ user_id` | PG test |
| AC-PLT-02 | Nakon aktivacije dopušten samo revoke; DELETE zabranjen | PG test |
| AC-PLT-03 | Four-eyes: nema samoodobrenja, nema odobrenja istog podnositelja; paralelno odobrenje jedan pobjednik | konkurentni |
| AC-PLT-04 | Eskalacija: nema samododjele, nema tipa koji dodjeljivač ne drži | negativni |
| AC-PLT-05 | Opoziv i istek djeluju na sljedeći zahtjev; TOCTOU zatvoren | integracijski + konkurentni |
| AC-PLT-06 | Anti-lockout: zadnji `PLATFORM_GRANT_ADMIN` ne može se opozvati | negativni |
| AC-PLT-07 | Platform rola bez granta vidi 0 redaka; app rola nema platformske politike | PG test |
| AC-PLT-08 | Verifikator nema user/grant ovlasti; ovlasti se ne nasljeđuju | negativni |
| AC-PLT-09 | Platformski grant ne omogućuje pristup tenant podacima (probna tablica) | cross-tenant |
| AC-PLT-10 | Svaka upotreba granta auditirana u istoj transakciji | PG test |
| AC-PLT-11 | Bootstrap CLI: samo ACTIVE korisnik, audit `SYSTEM`, traži owner vjerodajnice, DEV/CI | test + pregled |
| AC-PLT-12 | Migracija 0006 up/down/up | CI korak |
| AC-ADM-01 | Deaktivacija/blokada/reaktivacija: ispravan status, sesije odmah, audit, outbox | integracijski |
| AC-ADM-02 | Pristup ostaje odbijen i kad je Keycloak nedostupan (sinkronizacija se ponavlja) | integracijski |
| AC-ADM-03 | Platformske rute: grant + LoA2 + limit; bez toga 403/401 | negativni |
| AC-ADM-04 | Pretraga samo točnim e-mailom/ID-em; auditirana | API test |
| AC-ADM-05 | Outbox idempotentan, backoff, otporan na pad usred obrade | integracijski |
| AC-ADM-06 | Worker radi pod vlastitom rolom i ne vjeruje poruci bez provjere | PG test |
| AC-ADM-07 | Obavijesti ne blokiraju opoziv | integracijski |
| AC-ADM-08 | Konkurentna deaktivacija + login: nema aktivne sesije nakon deaktivacije | konkurentni |
| AC-ADM-09 | Korisnik vidi samo vlastite sigurnosne događaje | API test |
| AC-ADM-10 | Migracija 0007 up/down/up | CI korak |

## 12. API ugovori (T12) — F2.07
| ID | Kriterij | Dokaz |
|---|---|---|
| AC-API-01 | Odgovori svih F2 ruta odgovaraju ugovoru (uspjeh i svaka greška iz kataloga) | contract test |
| AC-API-02 | Svaka operacija deklarira sigurnosnu shemu i `x-authorization`; javne rute samo allowlist | test |
| AC-API-03 | Kodovi grešaka = katalog §10.4; `problem+json` s `request_id` | test |
| AC-API-04 | Mutacije podržavaju Idempotency-Key, izmjene If-Match; liste cursor paginaciju | contract test |
| AC-API-05 | OpenAPI drift/validator OK; TS i Dart generiranje prolaze (Dart bez analize, R10 rezidual) | CI |
| AC-API-06 | Preglednička preusmjerenja `x-internal`, izostavljena iz klijenata | test |
| AC-API-07 | Nema PII izvan modela; `no-store` na auth rutama; CORS prazan po zadanom | test |
| AC-API-08 | Kompatibilnost: Next.js (kolačić+CSRF) i Flutter (bearer) tokovi opisani i testirani na ugovornoj razini | dokumentacija + test |

## 13. Završno prihvaćanje F2 (CP13)
F2 je **prihvaćen** samo ako su ispunjeni svi uvjeti:
1. Svi AC iz §1–§12 su PASS, osim izričito BOUNDED stavki koje je vlasnik pojedinačno odobrio (npr. AC-API-05 Dart).
2. CI run na točnom SHA kandidata: svi jobovi zeleni, 0 skipped, `-W error`, Ruff/mypy čisti, OpenAPI drift OK, gitleaks cijela povijest bez nalaza, pip-audit čist, migracijski ciklus 0002–0007 up/down/up, role SQL dvaput.
3. Matrica AC→test potpuna (T13 traceability test zelen).
4. Scope guard zelen; pregled diffa `main..dev` za F2 ne pokazuje putanje izvan D35; nema poslovnih modula, Compose/Traefik/secrets izmjena, generiranih klijenata ni tajni.
5. Nema otvorenih nalaza P0/P1; preostali P2 imaju vlasnika i rok.
6. Sve PROPOSED odluke koje implementacija koristi su ACCEPTED (ili izričito odbijene/izmijenjene uz ponovljen test); D42 ostaje OPEN do AT-20 i to je zabilježeno.
7. Spike ishodi S1–S10 zabilježeni; odstupanja od D19/D20/D23 odobrena.
8. Završni dokaz `F2-FINAL-ACCEPTANCE-EVIDENCE.md` + pointer statusa u MASTER-BLUEPRINT i G6 ažuriran.
9. Preduvjeti za live (R05, R11, R12, `TRUSTED_PROXY_CIDRS`, D13, D43, O15, O06–O17, AT-20) izričito navedeni kao **neispunjeni** i kao zaseban gate; F2 ih ne zatvara.
10. Prihvaćanje ne znači merge u `main`, release ni deployment; F3a ostaje blokiran do AT-03 usklađivanja.

## Keycloak security provider (owner order of 2026-11-25)
Normative for F2-T09-REC; evidence per criterion in the [CP09 report](F2-CP09-RECONCILIATION-REPORT.md).

| ID | Criterion | Verification |
|---|---|---|
| KC-SP-01 | Feasibility of the SPI approach proven on the exact Keycloak version | source analysis + real Keycloak |
| KC-SP-02 | F-1R-C closed | KC |
| KC-SP-03 | Remaining F-3K closed | KC |
| KC-SP-04 | Open recovery-authentication finding closed | KC |
| KC-SP-05 | Obligation `at_mfa_required` set automatically, consistently with the first permanent factor | KC |
| KC-SP-06 | Controlled switch-off of MFA | KC + integration |
| KC-SP-07 | No automatic security downgrade | build check + KC |
| KC-SP-08 | Protection of concurrent operations proven (one and several instances) | KC, two nodes |
| KC-SP-09 | Relevant Keycloak paths protected | KC |
| KC-SP-10 | Fail-closed behaviour | KC + CI step |
| KC-SP-11 | Reproducible Keycloak image | build check |
| KC-SP-12 | Java dependencies and the image checked | build check + static tests |
| KC-SP-13 | Upgrade and safe rollback documented | review |
| KC-SP-14 | Every earlier security regression test passes | CI |
| KC-SP-15 | FULL local CI PASS | Local CI |
| KC-SP-16 | GitHub CI PASS on the final SHA | GitHub |
| KC-SP-17 | Matrix of all 126 criteria updated | CP09 report |
| KC-SP-18 | No open P0/P1 finding within the authorized scope | CP09 report |
| KC-SP-19 | No unauthorized infrastructure or production change | review |
| KC-SP-20 | Ready for an independent security review | CP09 report |
