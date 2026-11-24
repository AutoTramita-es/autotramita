# G6 — Redoslijed izvršavanja

Datum: 2026-11-24
Status: DRAFT — pravila izvršavanja dokumentirana; detaljni redoslijed faza čeka usklađivanje s izvornim planom i potvrdu. Nije autorizacija implementacije.

## Preduvjeti F1
- [x] ADR-010 Accepted — Keycloak.
- [x] ADR-011 Accepted — Nextcloud, bez MinIO/S3.
- [ ] G6 — potvrđen detaljni redoslijed izvršavanja.
- [ ] Izričita autorizacija F1 od vlasnika projekta.

## Pravila
1. Svaka faza zahtijeva zasebnu autorizaciju.
2. Nakon svake faze provesti testiranje, pregled rezultata i GitHub commit.
3. Sljedeća faza ne započinje automatski.
4. Konačno usklađivanje AT-03 obvezno je prije F3a, ne prije F1. Uskladiti ADR-009, tenant-branch.md, tenant-membership.md i kriterije prihvata s 27 potvrđenih odluka i pregledanim završnim dizajnom.
5. Deployment zahtijeva zasebno odobrenje.

## Izvori
- [ADR register](adr/ADR-REGISTER.md)
- [ADR-008](adr/ADR-008-delivery-governance.md)
- [AT-03 potvrđene odluke](specifications/AT-03-decisions.md)
- [AT-03 završni prijedlog](specifications/AT-03-final-design.md)

## Otvoreno
GitHub pretragom G6 nije pronađen izvorni detaljni plan faza. To ne dokazuje da plan ne postoji. Prije potvrde G6 pronaći i uskladiti postojeći plan, definirati opseg, ovisnosti, kriterije prolaza i granice F1 i sljedećih faza; ne izmišljati sadržaj F1–F3a. Ovaj zapis ne mijenja postojeći plan niti autorizira kod, migracije, infrastrukturu ili deployment.
