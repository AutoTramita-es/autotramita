# AT-05 — BOE Vehicle Catalog: plan
Datum: 2026-11-24 | v0.1 | PROPOSED — za pregled vlasnika; nije autorizacija implementacije.

## Opseg i izvori
Globalni referentni katalog, odvojen od tenant registra stvarnih vozila (VIN, vlasnik, registracija). AT-05 vlasnik kataloga; AT-12 koristi procjene u ponudama; AT-15 prati službene izvore. Uskladiti s [Master Blueprint](../MASTER-BLUEPRINT.md), ADR-001/002/004/006/007/008. Python 3.12, uv, SQLAlchemy 2.x, psycopg 3, PostgreSQL, FastAPI; dev razvoj, main stabilna produkcija.
Kandidati za provjeru: https://www.boe.es/eli/es/o/2025/12/17/hac1501/dof/spa/html i https://boe.es/datosabiertos/api/api.php. Prije uvoza potvrditi identifikator propisa, datum primjene, priloge, ispravke i dostupnost strukturiranih tablica. PDF službena kontrola; HTML/XML preferirani samo ako potpuni. Nije potvrđen službeni CSV niti broj redaka; ne koristiti brojke trećih strana kao kriterij potpunosti. Bez komercijalnih baza kao izvora istine.

## Redoslijed rada i kontrolne točke
| ID | Rad | Izlaz / uvjet prolaza |
|---|---|---|
| BOE-01 | Otkriti godišnji propis, priloge i ispravke; preuzeti original uz timeout, retry, ograničenje veličine i provjeru domene | manifest URL, BOE ID, godina, datum primjene, SHA-256, vrijeme preuzimanja, format; nepromjenjiv original |
| BOE-02 | Parsirati tablice prema zaglavljima i prilogu; obraditi rowspan/colspan, ponovljena zaglavlja, decimalni zarez i nedostajuća polja | staging raw redci s lokatorom tablice/retka; izvještaj svih odbijenih redaka; ne nagađati nedostajuće podatke |
| BOE-03 | Normalizirati Unicode, razmake, jedinice, marku, izvedbu, gorivo i godine komercijalizacije; sačuvati izvorni tekst | deterministički normalizirani zapisi; ne spajati slične izvedbe automatski |
| BOE-04 | Usporediti broj redaka po prilogu, kategoriji i marki s izvornikom; provjeriti iznose i duplikate, ručni uzorak i granične slučajeve | svaki izvorni redak evidentiran kao prihvaćen, duplikat ili odbijen; nerazriješene anomalije blokiraju objavu |
| BOE-05 | Izvesti UTF-8 CSV i JSON sa stabilnim redoslijedom, decimalnim iznosima bez float zaokruživanja, schema_version i manifestom | reproducibilni hash, isti sadržaj u oba formata, dokumentirana shema; CSV zaštita od formula za tablične programe |
| BOE-06 | Projektirati migracije i transakcijski staging import; idempotentnost prema izvoru i hash-u; aktivacija tek nakon odobrenja | DEV dry-run, ponovljeni import bez duplikata, rollback i test izolacije |
| BOE-07 | Parsirati službene koeficijente starosti i posebna pravila iz relevantnog priloga | verzionirani intervali, test granica datuma i službenih primjera; pravna provjera |
| BOE-08 | OpenAPI pretraga po marki/modelu/godinama/gorivu/snazi; paginacija, indeksiranje, rate limiting | ugovorni testovi, stabilni ID, nejasni rezultati traže odabir korisnika |
| BOE-09 | Izračun referentne fiskalne vrijednosti prema primjenjivom propisu i datumu prve registracije | Decimal, koeficijent preostale vrijednosti (ne zamijeniti s postotkom amortizacije), objašnjiv rezultat i izvor; bez tvrdnje da je to konačna porezna obveza |
| BOE-10 | Periodična provjera novih propisa i ispravaka; diff, staging, ručno odobrenje i aktivacija po datumu | povijesne verzije ostaju dostupne; upozorenje kod greške ili zastarjelog izvora; povrat na prethodnu odobrenu verziju |
| BOE-11 | Integracijski, regresijski, sigurnosni i prihvatni testovi; pregled gestora | potpisani izvještaj i zasebna odluka o releaseu |

## Predloženi podatkovni model
- boe_source_release: BOE ID, fiscal_year, effective_from/to, revision, URL, sha256, fetched_at, status (discovered/staged/validated/approved/active/rejected/superseded).
- boe_import_run: source_release_id, parser_version, counts, errors, timestamps, actor, artifact manifest.
- vehicle_catalog_entry: stabilni interni ID, brand, model/variant, year_from/to, engine_cc, cylinders, fuel_type, power_kw, power_cv, fiscal_power, vehicle_category; nullable gdje izvor nema podatak; identitet između godina samo nakon pouzdanog povezivanja.
- vehicle_fiscal_value: entry_id, release_id, amount_eur NUMERIC, raw_row_id; jedinstvenost prema potvrđenom identitetu unutar izdanja; ispravke ne prepisuju povijest.
- boe_raw_row: release_id, annex, table/row locator, raw payload, normalized hash, disposition.
- depreciation_rule: release_id, category, age bounds i inkluzivnost, remaining_value_percent, exceptions, source locator.
- Procjena u AT-12 čuva snapshot izdanja, vrijednosti, pravila, ulaza, datuma i rezultata; promjena kataloga ne mijenja stare ponude.

Globalni katalog ne sadrži osobne podatke; read-only pristup aplikacijskim ulogama, upis samo ovlaštenom importeru/administratoru. Tenant vozila i ponude ostaju pod RLS. Originali i veliki generirani artefakti: predloženo odvojeno DEV/PROD spremanje u odobreni Nextcloud, uz hash i backup; Git sadrži sheme, manifest i male testne uzorke, ne velike godišnje dumpove. Lokacija i retencija za odobrenje.

## Porezni opseg
BOE vrijednost nije univerzalna tržišna cijena ni automatska porezna osnovica. ITP zahtijeva zasebna verzionirana regionalna pravila, vrstu prodavatelja/transakcije i primjenjive iznimke; IEDMT zasebna pravila (uključujući emisije CO2, teritorij, osnovicu i oslobođenja). DGT pristojbe, ITV, IVA i naknada AutoTramita zasebne stavke. Bez konačnog poreznog kalkulatora dok gestor ne potvrdi pravila i službene izvore. Nepoznata izvedba ili nedostajući podatak vodi na ručnu provjeru, ne na izmišljenu vrijednost.

## Kriteriji prihvaćanja
AC01 službeni izvor i hash provjerljivi; AC02 svi redci obračunati i bez nerazriješenih grešaka; AC03 kontrolni uzorak usklađen s PDF; AC04 CSV/JSON ekvivalentni i reproducibilni; AC05 ponovni import idempotentan; AC06 rollback bez gubitka; AC07 povijesne vrijednosti i snapshot ponuda nepromijenjeni; AC08 test granica starosti i decimalne aritmetike; AC09 tenant izolacija i ovlasti; AC10 greška preuzimanja ne aktivira nepotpun katalog; AC11 OpenAPI i testovi; AC12 pravna validacija prije javnih poreznih procjena.

## Otvorene odluke i autorizacija
Prvo odobriti BOE-01 zasebno. Potvrditi kategorije (osobna vozila, motocikli, ostalo), raspon povijesnih godina, format izvora, pohranu i retenciju, raspored provjera (predloženo češće u prosincu/siječnju), vlasnika validacije i pragove anomalija. Nema automatskog deploymenta, CI/CD konfiguracije, koda, migracija, uvoza ili promjena infrastrukture ovim dokumentom. Claude Code izvršava samo zasebno odobrene faze nakon provjere aktualnog F1 statusa i ovisnosti.
