# G6 — Redoslijed izvršavanja

Datum: 2026-11-24
Status: ACCEPTED (2026-11-24) — pravila izvršavanja i detaljni redoslijed F1 potvrdio vlasnik projekta. **Nije autorizacija implementacije:** F1 zahtijeva zasebnu izričitu autorizaciju.

## Aktualni status — REC-02
REC-02 (2026-11-24): F1 implementation exists on f1/foundation at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a, preserved identically in archive/f1-foundation-2026-11-24; not merged or accepted. Historical broad authorization quoted in c467005 ("Autoriziram F1 prema G6-EXECUTION-ORDER.md") is UNVERIFIED: repository record exists, original owner instruction not established; neither confirmed nor invalidated retroactively. Later explicit T01-only authorization b6462e4 / 0973e24 remains recorded; CP01 blocked in preflight, no new implementation authorized or executable during reconciliation. T02–T10 not currently authorized. Audit reports 93 passing CI tests at e22ae3b (run 45398235580), not independently rerun; T01–05/T08–10 PARTIAL, T06–07 NON-COMPLIANT; AC05–08 compliant per reported CI, 7 partial, 3 non-compliant, AC09 not verified. F1 acceptance pending REC-07. REC-01 and REC-02 documentation approved; REC-03–07 require separate approval. No merge, deployment, F2 or infrastructure changes authorized. O01/O02/O03/O18/O19 remain ACCEPTED; 15 deferred decisions remain PROPOSED. Maintenance page and routing reported on implementation branch; live state and separate authorization unverified. Preserve both histories; no duplicate implementation or automatic cherry-pick.

[Audit](design/F1-RECONCILIATION-AUDIT.md) | [Plan](design/F1-RECONCILIATION-PLAN.md)

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

## F1 — AT-01 temelj sustava (ACCEPTED redoslijed; RECONCILIATION / NOT ACCEPTED)
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

**Potvrđene tehničke odluke (2026-11-24):** sinkroni sloj baze (SQLAlchemy 2.x, psycopg 3); Python 3.12 i `uv`; GitHub Actions kao CI; Redis za rate limiting s gore navedenim početnim limitima. Vlasnik projekta izričito je potvrdio G6 i sve četiri tehničke odluke, uključujući osam početnih limita. Povijesno stanje pri potvrdi G6: F1 tada nije bio autoriziran ovim zapisom; aktualni status vidi REC-02.

## Dodatak — potvrda AT-01.03 (2026-11-24)
O01, O02, O03, O18 i O19 izričito potvrđeni. Normativni detalji u AT-01 §10a; testirati prema tamošnjim kriterijima uz postojeće G6 sigurnosne testove. Ostalih 15 odluka ostaje PROPOSED. Nema proširenja dopuštenih putanja ni autorizacije F1/deploymenta. Ako detalj fingerprinta, cursora ili testne perzistencije zahtijeva novu arhitektonsku odluku, stati prema G6.

## Odobrenje AT-01.04 (2026-11-24)
Vlasnik je odobrio AT-01 v1.1. Preostalih 15 odluka ostaje PROPOSED za pripadajuće faze. Slijedi priprema naloga za Claude Code; F1 i deployment nisu autorizirani. Opseg i redoslijed G6 ostaju nepromijenjeni.

## AT-01.06 — djelomična autorizacija (2026-11-24)
Vlasnik odobrio [Execution Brief v1.0](specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md) i autorizirao isključivo F1-T01 (G6.1). Obvezan STOP na CP01; T02–T10, merge i deployment nisu autorizirani. Ovaj kasniji zapis nadjačava ranije povijesne navode da nijedan F1 zadatak nije autoriziran. Nema proširenja opsega.

## F2 i F3a — samo okvir
F2 (AT-02 identitet/sesije, minimalni AT-17): `users`, `user_sessions`, validacija konteksta, opoziv, `audit_events`, `platform_grants`; prije toga zaseban detalj i autorizacija. F3a (AT-03 tenant/poslovnica/članstvo/pozivnica/verifikacija, minimalni AT-09): tek nakon AT-03 usklađivanja (pravilo 4). Detaljni redoslijed za F2 i F3a piše se kad F1 završi.

## REC-03 — Approved DEV/PROD Git policy (2026-11-24)
Owner approved two active branches: dev for all development and integration, main for stable production releases. This supersedes the proposed feature/maintenance branches and the earlier main-only plan. dev maps to Docker project autotramita-dev; main maps to autotramita-prod. Mapping is a policy, not an active deployment connection. No automatic deployment or CI/CD deployment configuration is authorized. Future DEV automation is a separate decision; PROD release and deployment require explicit approval. No production data or secrets in DEV.
REC-03 preparation: create dev from updated main, then integrate f1/foundation into dev with a history-preserving merge after checking conflicts and automation. Preserve newer approved documentation, existing code, maintenance assets and historical records; retain original and archive branches. Review .gitleaksignore and disputed migration 0002 in later authorized work. Do not merge unfinished F1 into main. No new features, live changes or F1 acceptance. REC-04–07 remain unauthorized. Stop if external deployment triggers or loss of content cannot be ruled out. Prior REC-02 status is historical; this section supersedes its branch/merge restrictions only for the approved DEV consolidation preparation. Actual merge remains pending verification.

REC-03 execution: 2026-11-24. The dev branch was created from 1e8be38, automation was reviewed with no deployment trigger, and f1/foundation was integrated with a history-preserving merge. The G6 conflict was resolved by preserving the newer approved dev documentation. Local disposable PostgreSQL 16 and Redis 7 tests passed: 93 tests, plus Ruff, formatting, mypy, OpenAPI contract and client generation checks. Gitleaks found no leaks across 413 commits; pip-audit found no known vulnerabilities. No Docker, database, DNS or Traefik state was changed.

## REC-04.1 / CP01 acceptance and REC-04.2 authorization (2026-11-24)
Owner explicitly ACCEPTED CP01 / F1-T01. Implementation commit 8e1de017e0dcf2ab1537d432d600b5183a4766b8 on dev; verified CI run 45411248406, all three jobs successful, 93 passed, no skips, one Starlette TestClient/HTTPX deprecation warning, pip-audit no known vulnerabilities. Python 3.12.16, uv 0.13.9, OTel API/SDK 1.45.2; no instrumentation. Warning tracked for later review. Owner authorizes ONLY REC-04.2 / F1-T02 under existing brief and G6 scope, mandatory STOP CP02, owner acceptance required before T03. T03–T10 and deployment not authorized. Work on dev only; main unchanged. This current authorization supersedes earlier historical blocked/not-authorized statements only for T01 acceptance and T02. Full regression may use isolated GitHub Actions services after a scoped dev commit, as previously approved for T01; for T02 use the same CI-only approach only with owner approval if local integration is blocked. No shared infrastructure access or bypass of tool restrictions.

## REC-04.6 / F1-T06 authorization record (2026-11-24)
Owner authorized F1-T06 (API contracts) only, with mandatory STOP CP06. T07–T10, deployment and any change to `main` remain unauthorized; work on `dev` only, no access to shared services. This entry records the T06 authorization and does not formally record acceptance of CP02–CP05, which requires separate owner confirmation.

Approved path exceptions, limited to these two files: removal of `migrations/versions/0002_idempotency_keys.py` and regeneration of `openapi/openapi.json` for the T06 contract change. Removal of 0002 was approved on condition that it was never applied to a persistent DEV or PROD database. Evidence available in the repository (no database was queried): no compose file, script, workflow or Dockerfile runs Alembic; the API image is only the placeholder `autotramita-api:pending`; project documentation states the provisioning script was not executed against the database and the application is not deployed; `.secrets/` holds no `dev.env` or `prod.env`, which the provisioning script needs to create the owner role that migrations require. This is documentary evidence, not a check of the live databases.

Technical decisions approved by the owner for T06: cursors are `base64url(payload).base64url(HMAC-SHA256)` signed with the secret `CURSOR_SIGNING_KEY` (at least 32 bytes, no default, no fallback) and bound to tenant, filter hash, sort and a unique tie-breaker; request fingerprint is SHA-256 over method, operation and canonical JSON (sorted keys, compact, UTF-8, numbers as parsed; non-JSON bodies raw); the idempotency table exists only as a disposable test fixture; error codes are UPPER_SNAKE_CASE with `type` `https://docs.autotramita.es/errors/<kebab-code>`; `CurrencyCode` validates the ISO 4217 format only, not the full registry.

CI-only rule: the owner approved CI-only integration validation (isolated GitHub Actions services after a scoped `dev` commit, no skipped tests) for T06 and for future separately authorized F1 tasks. This is not an authorization to implement those tasks.

## REC-07.0 — CP10 accepted; final validation planning (2026-11-24)
Owner explicitly accepted CP10 and completion of T01–T10 collectively and authorized REC-07 planning only. Baseline dev 5d46c234f75ada37fe7121543fb3236d9d3cdb1f; verified CI run 45430813346 all three jobs passed, 336 passed, zero skipped, one warning, mypy 46 files, no leaks or known vulnerabilities. See [final validation plan](design/F1-FINAL-VALIDATION-PLAN.md) for R01–R15, AC01–15 and proposed packets. CP01 previously accepted; individual historical CP02–09 approvals not inferred. REC-04–06 implementation complete; F1 final acceptance pending. This entry supersedes stale execution status/authorization text only; normative requirements unchanged. STOP V0: no corrections, merge, F2, deployment or shared infrastructure access authorized. Main remains 1e8be38a40aac63f5c58d6dbb01daaa051326e6b.
