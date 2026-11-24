# G6 — Redoslijed izvršavanja

Datum: 2026-11-24
Status: ACCEPTED (2026-11-24) — pravila izvršavanja i detaljni redoslijed F1 potvrdio vlasnik projekta. **Nije autorizacija implementacije:** F1 zahtijeva zasebnu izričitu autorizaciju.

## Preduvjeti F1
- [x] ADR-010 Accepted — Keycloak.
- [x] ADR-011 Accepted — Nextcloud, bez MinIO/S3.
- [x] G6 — detaljni redoslijed izvršavanja potvrđen (Accepted).
- [x] AT-01 O01/O02/O03/O18/O19 — potvrđeno 2026-11-24.
- [x] Završno odobrenje cjelovite AT-01 specifikacije v1.1 — APPROVED (2026-11-24).
- [x] Izričita djelomična autorizacija F1 od vlasnika projekta — samo F1-T01 (2026-11-24).
- [ ] F1-T02–T10: zasebne autorizacije nakon checkpointova.

## Pravila
1. Svaka faza zahtijeva zasebnu autorizaciju.
2. Nakon svake faze provesti testiranje, pregled rezultata i GitHub commit.
3. Sljedeća faza ne započinje automatski.
4. Konačno usklađivanje AT-03 obvezno je prije F3a, ne prije F1. Uskladiti ADR-009, tenant-branch.md, tenant-membership.md i kriterije prihvata s 27 potvrđenih odluka i pregledanim završnim dizajnom.
5. Deployment zahtijeva zasebno odobrenje.

## Izvori
- [AT-01 specifikacija v1.1, §10a — potvrđene F1 odluke](specifications/AT-01-foundation-infrastructure.md#10a-potvrđene-f1-odluke--accepted-2026-11-24)
- [ADR register](adr/ADR-REGISTER.md)
- [ADR-008](adr/ADR-008-delivery-governance.md)
- [AT-03 potvrđene odluke](specifications/AT-03-decisions.md)
- [AT-03 završni prijedlog](specifications/AT-03-final-design.md)

## Izvor i sljedivost plana
Izvorni plan faza pronađen je u design dokumentima, ne u zasebnom G6 dokumentu: [DESIGN-ROADMAP.md](design/DESIGN-ROADMAP.md) §5 (pakete F0–F13), §9 (definition of ready) i §10 (izvršavanje i definition of done) te [FOUNDATION-G5-REVIEW.md](design/FOUNDATION-G5-REVIEW.md) §3 (granice F1/F2/F3a). Detalji F1 u nastavku izvedeni su iz njih i iz odobrenih odluka H1–H6 te potvrđenih tehničkih odluka G6; F2 i F3a ostaju samo okvir. Ovaj zapis ne autorizira kod, migracije, infrastrukturu ni deployment.

## F1 — AT-01 temelj sustava (ACCEPTED redoslijed; čeka izričitu autorizaciju)
**Cilj:** reproducibilan lokalni i CI kostur s dokazano ispravnom RLS izolacijom i zajedničkim API konvencijama, bez ijedne poslovne tablice.

**Dopuštene putanje:** `pyproject.toml`, `uv.lock`, `.python-version`, `alembic.ini`, `app/core/**`, `app/api/**`, `migrations/**`, `tests/**`, `scripts/db/**` (SQL rola), `openapi/**` (izvezeni ugovor), `.github/workflows/**`, `docs/DEVELOPMENT.md`.
**Zabranjeno:** `app/auth`, `app/tenants`, `app/customers`, `app/cases`, `app/documents`, `app/billing`, `app/credit` i ostali poslovni moduli; frontend i Flutter; Keycloak, Nextcloud, Celery i poslovni poslovi (Redis samo za rate limiting, korak 6); promjene `docker-compose*.yml`, `.secrets/`, Traefik/Cloudflare; pokretanje `scripts/provision-postgres.py` nad zajedničkim PostgreSQL-om; deployment.

**Redoslijed (svaki korak završava testom i malim commitom na grani, bez automatskog nastavka):**
1. Alati: Python 3.12 i `uv` s lockfileom (potvrđeno); Ruff, mypy, pytest; verzije pinirane. Instalacija tek nakon autorizacije. O01: Python 3.12.x, PostgreSQL 16.x, Redis 7.x; točne kompatibilne patch verzije i uv zaključati, odvojiti dev/runtime, CI uv sync --locked; Dependabot bez auto-mergea, izvan dopuštenih putanja samo uz zasebno odobrenje.
2. Konfiguracija: Pydantic v2 settings iz okoline, bez tajni u repou; odvojeni DB URL-ovi za owner/app/worker/platform.
3. Sloj baze: **sinkroni** SQLAlchemy 2.x i psycopg 3; `app.user_id`/`app.tenant_id` kroz `set_config(..., true)` na istoj konekciji i transakciji (ADR-002).
4. Alembic baseline: owner rola izvodi migracije; SQL za role u `scripts/db/` idempotentan, aplikacijske role nisu vlasnici (G5-01).
5. RLS test harness na pravom PostgreSQL 16 (ne SQLite): probna tablica samo u testovima; testovi: izostavljen kontekst vraća 0 redaka, krivotvoreni `tenant_id` pada na `WITH CHECK`, `FORCE ROW LEVEL SECURITY` aktivan, app rola nije vlasnik i nema `BYPASSRLS`, cross-tenant join i composite FK odbijeni, kontekst ne curi između konekcija iz pool-a, `SET ROLE` zaobilaženje odbijeno, worker uspostavlja vlastiti kontekst.
6. API konvencije (G5-08): `application/problem+json` (RFC 9457) sa stabilnim `code`; cursor paginacija bez izmišljenog ukupnog broja; `Idempotency-Key` s retencijom 24 h; `If-Match`/verzija za izmjene; rate limiting preko Redisa (korak 6a); request ID i zapisnici bez tajni i osobnih podataka. O03/O19: primijeniti detaljne ugovore iz AT-01 §10a (scope actor/tenant/operation/key, SHA-256, 24 h, replay/409/400, ponovna autorizacija, cursor 25/1/100, ETag/If-Match, 412/428); PostgreSQL poslovna atomska perzistencija kasnije, F1 samo testne strukture i zajednički mehanizam.
6a. Rate limiting: Redis kao centralni mehanizam; limiti konfigurabilni iz okoline, ne tvrdo kodirani. Početne vrijednosti: javni API 60 zahtjeva/min po IP-u; autentificirani API 300/min po korisniku; tenant 3.000/min; upload 30/min po korisniku; izvoz 5/min po korisniku; interni health check (`/api/v1/health`) izuzet. U F1 samo mehanizam, konfiguracija i testovi (limit, reset, izuzeće, ključevi odvojeni po tenantu). Brute-force zaštita prijave (5 neuspjelih u 15 min) i oporavak lozinke (3/h po računu) konfigurira se u Keycloaku u F2; F1 samo rezervira konfiguracijske ključeve. Limiti poslovnih modula definiraju se u njihovim fazama. O02/O18: približni Sliding Window Counter, atomska Lua obrada, Redis vrijeme, svi primjenjivi limiti; 429 i Retry-After prema blokirajućim limitima; fail closed 503 RATE_LIMIT_UNAVAILABLE, Retry-After 5 s, connect/operation timeout po 500 ms, bez retryja ili lokalnog fallbacka. Trusted proxy provjera i spoofing testovi; konkretne adrese prije deploymenta.
7. Zdravlje: `/api/v1/health` bez detalja o infrastrukturi; OpenTelemetry samo kao priključna točka.
8. OpenAPI: izvoz ugovora, contract test, provjera da se TypeScript i Dart klijenti generiraju (generiranje u CI, generirani klijenti se ne commitaju u F1).
9. CI na GitHub Actions: Ruff, mypy, pytest s PostgreSQL 16 i Redis service containerima, migration up/down, skeniranje tajni i ovisnosti.

**Kriteriji prolaza (dokaz, ne tvrdnja):** reproducibilan lokalni i CI test run; migracija gore i dolje; svi RLS negativni testovi zeleni; nijedan put s `BYPASSRLS`; OpenAPI se podudara sa stvarnim odgovorima; nema tajni ni produkcijskih podataka u repou; `docs/DEVELOPMENT.md` opisuje pokretanje.
**Uvjeti zaustavljanja:** neriješena odluka, pao sigurnosni test, neočekivana promjena sheme, potreba za vanjskim vjerodajnicama ili stvarnim PostgreSQL-om izvan CI/lokalnog spremnika, proširenje opsega. Tada stati i prijaviti.
**Izvješće nakon F1:** promijenjene datoteke, migracije, naredbe i rezultati testova, neuspjesi, rizici, rollback, sljedeća ovisnost. Prihvaćanje vlasnika odvojeno je od merge-a i deploymenta.

**Potvrđene tehničke odluke (2026-11-24):** sinkroni sloj baze (SQLAlchemy 2.x, psycopg 3); Python 3.12 i `uv`; GitHub Actions kao CI; Redis za rate limiting s gore navedenim početnim limitima. Vlasnik projekta izričito je potvrdio G6 i sve četiri tehničke odluke, uključujući osam početnih limita. F1 nije autoriziran; potrebna je zasebna izričita autorizacija.

## Dodatak — potvrda AT-01.03 (2026-11-24)
O01, O02, O03, O18 i O19 izričito potvrđeni. Normativni detalji u AT-01 §10a; testirati prema tamošnjim kriterijima uz postojeće G6 sigurnosne testove. Ostalih 15 odluka ostaje PROPOSED. Nema proširenja dopuštenih putanja ni autorizacije F1/deploymenta. Ako detalj fingerprinta, cursora ili testne perzistencije zahtijeva novu arhitektonsku odluku, stati prema G6.

## Odobrenje AT-01.04 (2026-11-24)
Vlasnik je odobrio AT-01 v1.1. Preostalih 15 odluka ostaje PROPOSED za pripadajuće faze. Slijedi priprema naloga za Claude Code; F1 i deployment nisu autorizirani. Opseg i redoslijed G6 ostaju nepromijenjeni.

## AT-01.06 — djelomična autorizacija (2026-11-24)
Vlasnik odobrio [Execution Brief v1.0](specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md) i autorizirao isključivo F1-T01 (G6.1). Obvezan STOP na CP01; T02–T10, merge i deployment nisu autorizirani. Ovaj kasniji zapis nadjačava ranije povijesne navode da nijedan F1 zadatak nije autoriziran. Nema proširenja opsega.

## F2 i F3a — samo okvir
F2 (AT-02 identitet/sesije, minimalni AT-17): `users`, `user_sessions`, validacija konteksta, opoziv, `audit_events`, `platform_grants`; prije toga zaseban detalj i autorizacija. F3a (AT-03 tenant/poslovnica/članstvo/pozivnica/verifikacija, minimalni AT-09): tek nakon AT-03 usklađivanja (pravilo 4). Detaljni redoslijed za F2 i F3a piše se kad F1 završi.
