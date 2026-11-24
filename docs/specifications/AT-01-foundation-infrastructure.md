# AT-01 — Temelj sustava i infrastruktura

- Verzija: 1.0, 2026-11-24
- Status: PROPOSED — završni prijedlog za pregled vlasnika
- Prihvaćene odluke ostaju Accepted; ovaj dokument ne autorizira F1, kod, migracije, provisioning ili deployment.

## 1. Izvori i prvenstvo
[Master blueprint](../MASTER-BLUEPRINT.md), [ADR registar](../adr/ADR-REGISTER.md), [ADR-001](../adr/ADR-001-technology-stack.md), [ADR-002](../adr/ADR-002-multi-tenancy-rls.md), [ADR-003](../adr/ADR-003-identity-customer-membership.md), [ADR-004](../adr/ADR-004-api-contracts.md), [ADR-005](../adr/ADR-005-document-storage.md), [ADR-008](../adr/ADR-008-delivery-governance.md), [ADR-010](../adr/ADR-010-identity-provider-keycloak.md), [ADR-011](../adr/ADR-011-documents-on-shared-nextcloud.md), [G5](../design/FOUNDATION-G5-REVIEW.md), [G6](../G6-EXECUTION-ORDER.md), [DNS/Nextcloud/mail](../DNS-NEXTCLOUD-MAIL.md), [Compose](../DOCKER-COMPOSE.md).
Prihvaćeni ADR-ovi i kasnije eksplicitne odluke imaju prvenstvo; G6 određuje granice F1. Povijesni prijedlozi G5 nisu novi nalozi. ADR-006/007/009 ostaju mjerodavni za poslovne module.

## 2. Cilj, akteri i granice
AT-01 pruža reproducibilan backend, konfiguraciju, DB izolaciju, API konvencije, CI i operativne temelje za AT-02–20. Vlasnik odobrava odluke i faze; ChatGPT održava specifikacije; Claude Code implementira odobrene pakete; infrastrukturni administrator zasebno odobrava i izvršava operativne promjene. Runtime identiteti imaju najmanje potrebne ovlasti. F1 ne uvodi poslovne tablice, autentifikaciju, frontend, mobilne aplikacije ni stvarne integracije.

## 3. Prihvaćena arhitektura
Modularni monolit FastAPI, Python 3.12, uv i lockfile, Pydantic v2, sinkroni SQLAlchemy 2.x/psycopg 3, Alembic, PostgreSQL (16 za lokalne/CI testove), Redis, Celery za kasnije poslove, HTTPX, Next.js/TypeScript, Flutter, Docker Compose, GitHub Actions, Ruff/mypy/pytest, OpenTelemetry priključna točka. Sentry ili ekvivalent ostaje za operativnu odluku. Nema MinIO/S3.
Jedan server, DEV i PROD zasebni Compose projekti i aplikacijske mreže; nema staginga. Zajednički PostgreSQL, Traefik, Nextcloud, FS-Mailserver, SnappyMail i kandidat Uptime Kuma ostaju pod postojećim stackovima. Zajedničke mreže i host su granice povjerenja i zajedničke točke kvara. Odvojene aplikacijske i Keycloak baze, Redis, ClamAV, tajne i Nextcloud računi po okruženju. DEV Mailpit, bez javnog UI-ja. Nema javnih DB portova.

## 4. Mreže i stanje
PROD web planiran preko Cloudflare Tunnel i zajedničkog Traefika uz provjeren TLS prema originu; DEV nested wildcard DNS-only izravno na Traefik. Cloudflare Access nije preduvjet. Jedan web origin s workspace putanjama; api/auth/webhooks/admin ostaju zasebni hostovi. partners/clientes DNS zapisi ne znače zasebne aplikacije. API je /api/v1/ prema ADR-004/G6 (DNS dokument navodi /v1/; potrebno dokumentacijsko usklađenje). CORS samo dopušteni origini; privatni pristup uvijek autoriziran.
Dokumentirano stanje, ne nova live provjera: DNS zona i konektori aktivni, tuneli catch-all 404, DEV wildcard TLS izdan i fallback 418; cloud.autotramita.es radi preko proxyja izravno prema Traefiku. Compose validiran, aplikacijski projekti nisu pokrenuti. Provisioning skripta nije izvršena; baze, role i Nextcloud računi nisu provisionirani. DNSSEC nije aktivan, Full(strict) i sigurnosne postavke nisu potvrđene. CDN/status/mail ciljevi i www redirect otvoreni. Ne mijenjati postojeće stackove.

## 5. Podatkovni model i sigurnost
Prihvaćeno: jedna aplikacijska baza po okruženju, zajedničke tenant tablice s UUID tenant_id NOT NULL; globalni identitet i katalog odvojeno autorizirani. Četiri role: owner (migracije), app (runtime), worker (vlastiti kontekst), platform (usko autorizirane operacije). Runtime nije owner, superuser ni BYPASSRLS; bez eskalacije SET ROLE. FORCE RLS, USING i WITH CHECK, composite FK s tenant_id. Transakcijski lokalni app.user_id/app.tenant_id preko set_config na istoj konekciji; izostavljen kontekst fail closed. Pool ne smije prenositi kontekst. Worker ne vjeruje proizvoljnom tenant ID-u iz poruke.
G5 H2/H4: prvo vlastito članstvo SELECT kroz user kontekst, zatim provjeren tenant/branch kontekst; platform grants vremenski i opsegom ograničeni, audit u poslovnoj transakciji. Audit događaji tenant/platform scope, nullable tenant_id za platform događaje, append-only. Konkretne poslovne politike i tablice tek F2/F3a. F1 samo testna fixture, bez poslovne sheme. Globalni i tenant podaci u cacheu, logovima, datotekama i integracijama zahtijevaju vlastite kontrole.

## 6. API ugovor
Prihvaćeno: REST /api/v1/, OpenAPI izvor ugovora, generirani TS/Dart klijenti, RFC 9457 application/problem+json sa stabilnim code, cursor pagination bez izmišljenih totals, If-Match/verzija za izmjene, Idempotency-Key za retry-sensitive operacije (24 h), request ID, logovi bez tajni/PII. Potpisani webhookovi i deduplikacija u odgovarajućim fazama. Tenant iz zahtjeva nije autoritet. F1 health /api/v1/health bez infrastrukturnih detalja.
Redis konfigurabilni limiti: javni 60/min/IP; autentificirani 300/min/user; tenant 3000/min; upload 30/min/user; export 5/min/user; interni health izuzet. F2 Keycloak: 5 neuspjelih prijava/15 min i recovery 3/h/račun; F1 rezervira konfiguracijske ključeve, ne implementira autentifikaciju. Poslovni limiti kasnije.

## 7. Integracijski ugovori (izvan F1)
AT-02: Keycloak zaseban realm i baza po okruženju; sub u users.auth_subject; OIDC code+PKCE, web BFF host-only HttpOnly cookies i CSRF, bez browser token storage; aplikacijske sesije i autorizacija na svakom zahtjevu. MFA autokuća opcionalan; centralni/profesionalni MFA i trajanja sesija otvoreni.
AT-09: WebDAV/OCS preko zasebnih računa i AutoTramita/PROD, AutoTramita/DEV; Tenants/{tenant_uuid}, DirectClients, Internal, System. UUID putanje nisu autorizacija. Metadata i SHA-256 u PostgreSQL/RLS; validacija MIME/veličine, karantena, ClamAV prije objave, originali i verzije, kratkotrajni aplikacijski linkovi. Klijenti i partneri bez izravnog Nextcloud pristupa; staff SSO tek nakon odluke i kontrole ovlasti.
AT-16: FS-Mailserver poslovna pošta; vanjski transakcijski SMTP provider još nije odabran. DEV Mailpit uz obveznu buduću egress zaštitu. Dovecot izvor istine za inbound dokumente, Sieve/IDLE/reconciliation prema budućem ugovoru; ne povezivati samo po adresi pošiljatelja. Bez osjetljivih automatskih privitaka.
AT-20: GDPR/LOPDGDD, EU lokacija podataka, audit, retention, legal hold, incidenti i backup; pravne i operativne odluke ostaju otvorene.

## 8. F1 izvršavanje (Accepted G6, NOT AUTHORIZED)
Dopuštene putanje: pyproject.toml, uv.lock, .python-version, alembic.ini, app/core/**, app/api/**, migrations/**, tests/**, scripts/db/**, openapi/**, .github/workflows/**, docs/DEVELOPMENT.md.
Zabranjeno: poslovni moduli uključujući app/auth, frontend/Flutter, Keycloak/Nextcloud/Celery, Compose i secrets izmjene, shared DB provisioning, deployment. Redis samo za rate limiting. Svaki korak test i mali commit na grani; bez automatskog nastavka.
1. Python 3.12/uv, pinning alata.
2. Pydantic settings, četiri DB URL-a, bez tajni.
3. Sinkroni DB sloj i transakcijski kontekst.
4. Alembic baseline, idempotentni SQL za role.
5. RLS harness na stvarnom PostgreSQL 16.
6. API konvencije; 6a Redis limiter i konfiguracija.
7. Health i OTel priključna točka.
8. OpenAPI export/contract test i provjera TS/Dart generiranja u CI; bez commitanja generiranih klijenata.
9. GitHub Actions: lint/typecheck/tests, PostgreSQL 16 i Redis service containers, migration up/down, secret/dependency scanning.
F2 zasebna specifikacija identiteta; F3a tek nakon usklađivanja AT-03 dokumenata. Svaka faza i deployment zahtijevaju zasebnu autorizaciju.

## 9. Kriteriji prihvata F1 (dokazi obvezni)
| ID | Dokaz |
|---|---|
| AC01 | Čista lokalna instalacija iz lockfilea i reproducibilan CI |
| AC02 | Settings validiraju nedostajuće vrijednosti; nema tajni u repou/logovima |
| AC03 | Alembic upgrade/downgrade prolazi na lokalnoj/CI bazi |
| AC04 | Runtime role nisu owner/superuser/BYPASSRLS; SET ROLE eskalacija odbijena |
| AC05 | FORCE RLS aktivan; bez konteksta 0 redaka |
| AC06 | Krivotvoreni tenant write odbijen WITH CHECK; cross-tenant read/join ne otkriva podatke |
| AC07 | Composite FK odbija cross-tenant referencu |
| AC08 | Pool reuse i rollback ne prenose tenant/user kontekst |
| AC09 | Worker uspostavlja vlastiti kontekst |
| AC10 | Problem+json, pagination, idempotency i optimistic concurrency konvencije testirane u F1 opsegu |
| AC11 | Redis limit/reset/izuzeće i tenant key izolacija testirani |
| AC12 | Health bez osjetljivih detalja, request ID i redakcija logova |
| AC13 | OpenAPI odgovara stvarnim odgovorima; TS/Dart generatori prolaze |
| AC14 | CI lint, mypy, pytest, migration i sigurnosne provjere prolaze |
| AC15 | DEVELOPMENT.md, izvještaj testova, rizici i rollback; nema poslovnih tablica ili izmjena izvan opsega |
Nijedan kriterij nije trenutno potvrđen izvršenjem. G6 stop: neriješena odluka, sigurnosni test pada, neočekivana shema, vanjske vjerodajnice/shared DB ili proširenje opsega. Izvještaj: datoteke, migracije, naredbe, rezultati, neuspjesi, rizici, rollback i sljedeća ovisnost.

## 10. Otvorene odluke — PROPOSED, ne odobrene
| ID | Prijedlog | Gate |
|---|---|---|
| O01 | Pinati konkretne kompatibilne verzije u lockfileu, bez proizvoljnog odabira zastarjelih verzija | F1.1 |
| O02 | Redis nedostupan: fail closed za ograničene zahtjeve uz 503; health izuzet, bez tihog lokalnog fallbacka | F1.6a |
| O03 | Idempotency scope actor/tenant/operation/key; fingerprint zahtjeva, konflikt za drukčiji payload, atomski zapis poslovnog rezultata u kasnijim modulima; bez stvarnih financijskih tablica u F1 | F1.6 |
| O04 | Zasebni Keycloak web/native klijenti, strogi redirect URI i recovery provjere | F2 |
| O05 | 30 min idle/12 h web kao početni prijedlog; obvezan MFA centralnih i profesionalnih uloga, mobilni lifetime zasebno | F2 |
| O06 | Inventar PUBLIC grants svih shared DB, minimalne ovlasti i testovi bez izmjena drugih stackova bez odobrenja | Prije live |
| O07 | Enkriptirani offsite backup s odvojenim vjerodajnicama; provider nakon procjene | Prije PROD |
| O08 | Početni cilj RPO 24 h/RTO 8 h, provjeriti prema poslovnom riziku; za financije mogu trebati stroži ciljevi | Prije PROD |
| O09 | Root-only secret files, različite tajne po servisu/okruženju, inventar i kontrolirana rotacija; bez rotacije shared tokena bez analize | Prije live |
| O10 | CPU/RAM/disk kvote nakon mjerenja hosta i load testa; ne pretpostavljati kapacitet | Prije live |
| O11 | Kuma provjere, strukturirani redigirani logovi, alarmi za greške, disk, DB, Redis, certifikate i backup; neovisni vanjski monitoring razmotriti | Prije PROD |
| O12 | Ručno odobren deployment iz nepromjenjivih image tagova/digesta; rollback aplikacije i kompatibilne migracije, restore samo uz odobrenje | Prije live |
| O13 | DEV egress deny prema vanjskom SMTP-u, test da stvarna pošta ne izlazi | Prije DEV live |
| O14 | Nextcloud računi ograničeni na vlastite rootove, kvote i test restore; predloženi limiti 50 MB dokument/20 MB foto/250 MB video | AT-09/prije live |
| O15 | Odabir transakcijskog SMTP providera prema EU privatnosti, cijeni, isporučivosti i bounce webhookovima; uskladiti Compose placeholder | AT-16 |
| O16 | DNSSEC koordinacija s registrarom, provjera Full(strict), WAF i TLS prije izlaganja | Prije PROD |
| O17 | Spriječiti neovlašteni direct-origin pristup PROD routerima uz očuvanje DEV i postojećih stackova; ne oslanjati se na DNS | Prije PROD |
| O18 | Odrediti algoritam limitera i trusted proxy/IP pravila, kombiniranje limita i Retry-After; testirati spoofing forwarded headers | F1.6a |
| O19 | Razjasniti F1 idempotency test fixture/persistence i točan error/cursor contract prije kodiranja; bez poslovnih tablica | F1.6 |
| O20 | Odvojiti liveness od readiness prije live; health javno ne otkriva ovisnosti | Prije live |
Oznake i preporuke su novi prijedlozi za pregled, ne izmjene ADR-ova. O01–03/O18–19 razriješiti najkasnije prije odgovarajućeg F1 koraka; ostalo ne blokira lokalni F1 ako se poštuju granice G6.

## 11. Operativni rizici i gate
Shared host/DB/Nextcloud/Traefik predstavljaju zajednički blast radius; odvojene mreže nisu potpuna izolacija. Cloudflare tokeni prema inventaru dijele istu vjerodajnicu; ne rotirati bez procjene. DEV izravno dostupan bez Cloudflare proxy zaštite; PROD origin javno sluša. Backup mora konzistentno obuhvatiti aplikacijsku DB, Nextcloud sadržaj/DB/konfiguraciju, Keycloak, konfiguraciju i tajne; testirati obnovu u izoliranom okruženju. Ne koristiti stvarne klijentske podatke u DEV/CI. Prije live: potvrditi kapacitet, izolaciju, TLS, egress, tajne, monitoring, backup/restore i rollback; prije PROD dodatno pravne/retention i poslovne gateove.
Financijski utjecaj: reuse smanjuje dodatne servise, ali offsite backup, SMTP, monitoring i kapacitet mogu imati trošak; nema odobrenog budžeta ili procjene. AT-01 ne autorizira plaćanja.

## 12. Sljedeći korak
Vlasnik pregledava ovaj prijedlog; zasebno potvrđuje otvorene F1 odluke i eksplicitno autorizira F1 prema G6. Nema automatskog deploymenta. Dokumentacijska revizija nije live audit niti provjera koda/testova. Postojeći ADR-ovi i G6 nisu izmijenjeni.
