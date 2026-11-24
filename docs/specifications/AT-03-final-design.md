# AT-03 — Završna razrada za pregled

Status: PROPOSED / korisnički pregled; 24.11.2026. Bez implementacije.
Potvrđeni izvor: [27 odluka](AT-03-decisions.md). Temelj: [ADR-009](../adr/ADR-009-tenant-organization-membership-verification.md), ADR-002/003/005/007/008, [poslovnice](tenant-branch.md), [članstva](tenant-membership.md).
Ovaj prijedlog ne mijenja prihvaćene ADR-ove bez eksplicitne dopune. Nakon pregleda uskladiti izvorne specifikacije i kriterije prihvata.

## 1. Registracija i podaci
Tenant: UUID, entity_type COMPANY/SELF_EMPLOYED, legal_name, legal_form (za COMPANY), normalized_nif, tax_country ES, registered_address, billing_address (može biti ista), contact_email, contact_phone, optional trade_name, status, timestamps, version. NIF jedinstven u registru pravnih subjekata uz zakonito čuvanje; ne koristiti ga kao primarni ključ. Ne spremati kreditni limit u Tenant.
Zastupnik: zaseban zapis s imenom, vezom na User, vrstom ovlaštenja, dokazom i statusom provjere; osobni identifikatori samo ako potrebni za provjeru. Kontakt i zastupnik nisu isto.
Adrese: ulica/broj, dodatak, poštanski broj, mjesto, provincija, država; španjolski poštanski broj validirati za ES. Ne pretpostavljati da je sjedište poslovnica. NIF/NIE validirati prema tipu, normalizirati bez promjene značenja; provjera formata nije dokaz registracije.
DRAFT dopušta nepotpune podatke. Predaja zahtijeva obvezne podatke, dokaze, verificiran email kandidata i potvrđenu fizičku adresu BR-0001. Admin ručni unos prolazi isti proces; nema zaobilaženja.
Promjena pravnog naziva/sjedišta/NIF-a kroz TenantChangeRequest (old/new, reason, evidence, reviewer, status); do odobrenja vrijede prethodni podaci, osim ako rizik zahtijeva blokadu. Nova pravna osoba = novi Tenant. Ne otkrivati postojanje ili osoblje drugog Tenanta neovlaštenom korisniku.

## 2. Verifikacija i ugovor
TenantVerification: UUID, tenant_id, attempt_no, status PENDING/MORE_INFO_REQUIRED/APPROVED/REJECTED, checks, submitted_at, reviewer_id, reviewed_at, reason. Novi pokušaj ne prepisuje prethodni. Samo platform reviewer odobrava; provjera ovlasti zastupanja obvezna.
Dokazi: COMPANY — NIF, registracija, zastupanje, identitet; SELF_EMPLOYED — NIF/NIE, identitet, poslovna/porezna registracija. Alternativni valjani dokazi ručno. Ne zahtijevati bankovne izvode za običnu aktivaciju. Službeni API samo nakon provjere dostupnosti i pravne osnove.
TenantVerificationDocument: tenant_id, verification_id, document_id, category, review_result, retention_class. Privatni storage prema ADR-005; kratkotrajni autorizirani pristup, provjera datoteke, audit pregleda/preuzimanja. Obični zaposlenici nemaju pristup. Sačuvati minimalan rezultat provjere; izvorne dokumente čuvati samo koliko opravdano. Rokove po kategorijama i pravne osnove odrediti prije produkcije; legal hold za konkretan spor, kontrolirano brisanje i evidencija. Ne obećavati trajnu pohranu svih dokumenata.
ContractVersion: nepromjenjiv sadržaj/hash, verzija, effective_at, language; TenantContractAcceptance: tenant_id, version_id, representative_user_id, authority_reference, accepted_at, evidence. Aktivacija zahtijeva važeći ugovor prihvaćen od ovlaštenog zastupnika. Nove bitne uvjete treba ponovno prihvatiti; prijelazni rok i učinak neprihvaćanja pravno/poslovno provjeriti. Ne tvrditi da klik zamjenjuje zakonski potreban potpis.

## 3. Životni ciklus
Tenant DRAFT -> PENDING_VERIFICATION -> ACTIVE; odbijanje ostavlja zahtjev neaktivnim, dopuna/novi pokušaj prema ADR-009. Aktivacija atomarno: odobrena provjera, ugovor, aktivni OWNER, točno jedna aktivna glavna poslovnica. ACTIVE -> SUSPENDED -> ACTIVE; ACTIVE/SUSPENDED -> CLOSED nakon razrješenja obveza; CLOSED -> PENDING_VERIFICATION -> ACTIVE samo kontrolirana reaktivacija iste osobe. Pri reaktivaciji bez automatskog povrata kredita ili starih članstava; potvrditi OWNER-a.
Za zatvaranje TenantClosureRequest s intake_blocked_at, razlogom, provjerom predmeta, računa, sporova i obveza. Ne uvoditi dodatni status bez potrebe. Suspendirani OWNER/ADMIN ima ograničeni portal za račune, dokumente i komunikaciju prema odluci 14; sigurnosna blokada može ukinuti i taj pristup. Kreditna blokada odvojena.
Branch: zadržati postojeća polja i statuse DRAFT/ACTIVE/INACTIVE; dodati intake_blocked_at ili ekvivalent. Kreirati BR-0001 pri nastanku Tenanta; potvrditi adresu. Aktivacija prve poslovnice zajedno s Tenantom. Dodatne poslovnice samostalno uz provjere; sumnjive ostaju DRAFT do ručnog pregleda. Kodovi iz atomarnog tenant brojača, bez ponovne uporabe. Zatvaranje blokira novi intake, dovršava ili prenosi otvorene predmete, deaktivira dodjele; primarnu zamijeniti prije deaktivacije. Završeni predmeti ostaju povijesno vezani.

## 4. Matrica dozvola (predloženi default)
| Radnja | OWNER | ADMIN | MANAGER | EMPLOYEE | VIEWER |
|---|---|---|---|---|---|
| Operativni pregled | sve poslovnice | sve | dodijeljene | dodijeljene | dodijeljene, read-only |
| Obrada predmeta | da | da | da | da, prema dodjeli predmeta | ne |
| Upravljanje poslovnicama | da | da | ne | ne | ne |
| Pozivanje MANAGER/EMPLOYEE/VIEWER | da | da | samo EMPLOYEE/VIEWER uz grant | ne | ne |
| Dodavanje/uklanjanje ADMIN | da | ne | ne | ne | ne |
| Promjena OWNER | kontrolirani postupak | ne | ne | ne | ne |
| Prijenos predmeta | da | da | grant + obje dodijeljene poslovnice | zahtjev | ne |
| Popust | da | da | grant + limit | grant + limit | ne |
| Odgođeno plaćanje | da | da | zaseban grant + limit | zaseban grant + limit | ne |
| Promjena kreditnog limita | ne | ne | ne | ne | ne |
| Financijski pregled/izvoz | dopuštene kategorije | dopuštene kategorije | zaseban grant | zaseban ograničen grant | ne po defaultu |
| Operativni izvoz | da | da | grant, dodijeljene poslovnice | grant, vlastiti predmeti | ne |
| Audit pregled | dopušteni tenant zapisi | dopušteni tenant zapisi | ne po defaultu | ne | ne |
| Zatvaranje Tenanta | zahtjev | ne | ne | ne | ne |

Deny by default. Granular grants: INVITE_STAFF, TRANSFER_CASE, APPROVE_DISCOUNT, APPROVE_DEFERRED_PAYMENT, VIEW_FINANCE, EXPORT_OPERATIONAL, EXPORT_FINANCIAL, EXPORT_PERSONAL, EXPORT_BULK; kategorije izvoza kumulativno provjeravati. VIEWER ostaje read-only, bez dodatnih mutacijskih dozvola. ADMIN ne smije sam sebi povećati ovlasti ili upravljati OWNER/ADMIN članstvima. Delegirani MANAGER ne može delegirati vlastiti grant. OWNER/ADMIN upravlja operativnim grantovima podređenih, ne platformskim ovlastima. Financijski limit po zaposleniku predloženo: maksimalni popust u postotku i iznosu po predmetu, maksimalni odgođeni iznos po predmetu; obje granice primijeniti ako su zadane. Bez eksplicitnog limita/granta za delegiranu financijsku radnju deny. Valuta EUR, decimalni iznosi, provjera u transakciji s kreditnim računom AT-13. Pravila cjenika i naplate ostaju ADR-007.
Default workspace jedan aktivni Tenant/branch po sesiji. Tenant-wide administracija zasebna autorizirana operacija, ne implicitno objedinjavanje case listi. Povijesni pregled neaktivne poslovnice OWNER/ADMIN; ostali samo uz izričitu dopuštenu povijesnu ovlast.

## 5. Članstva i sigurnost
TenantMembership jedinstveno aktivno članstvo po User/Tenant, status INVITED/ACTIVE/SUSPENDED/REVOKED; povrat nakon REVOKED novom pozivnicom i novim povijesnim zapisom. MembershipBranch i MembershipGrant tenant-aware FK, created/revoked timestamps, grantor. Pozivnica zasebna, hash tokena, intended_email, role, branches, inviter, expiry 168h, accepted/revoked timestamps. Resend poništava staru. Pri prihvatu ponovno provjeriti email, inviterovu trenutnu ovlast, tenant, poslovnice, token; atomarno i idempotentno. MANAGER samo svoje poslovnice i niže uloge uz grant.
Više OWNER-a dopušteno prema ADR-009; svako dodavanje/prijenos uz postojeću OWNER potvrdu (ili kontrolirani oporavak), prihvat kandidata, provjeru zastupanja i platform approval. Prijenos ne znači automatsko uklanjanje svih drugih OWNER-a. Zaključati Tenant pri promjeni OWNER-a radi invarianta najmanje jednog aktivnog. Globalna sigurnosna blokada računa ne smije dati pristup; pokrenuti recovery ako nema dostupnog OWNER-a.
Opoziv/suspenzija odmah blokira tenant pristup u svim sesijama, bez utjecaja na druga članstva. Dodjela odgovornosti za nedovršene predmete: deterministički odrediti odgovornog aktivnog MANAGER-a poslovnice (predloženo eksplicitni designated manager), inače ADMIN/OWNER; odgovornost za red nije automatska promjena operativnog assignee-a. Ako nema odgovornog, platform escalation. Red, dnevni podsjetnici i 72h elapsed escalation ostaju. Ova interpretacija odluke 12 rješava konflikt s postojećom specifikacijom; potvrditi u pregledu.
2FA dobrovoljan za tenant uloge (odluka 18); platform admin sigurnost zasebno AT-02/17. Reset računa kroz verificirani email, jednokratni kratkotrajni token (predloženo 30 min), rate limit, generičke poruke protiv enumeracije, obavijest o promjeni, opoziv ostalih sesija pri resetu. Oporavak OWNER pristupa bez emaila nije obični reset: dokumentirana provjera zastupanja i posebno ovlašteni platform reviewer, audit i obavijest postojećim vlasnicima kada sigurno. Bez samostalnog preuzimanja računa.
Sesije: server-bound workspace, pregled i opoziv uređaja; predloženo 30 min neaktivnosti i 12h maksimalne web sesije uz zasebno razmatranje mobilnog refresh modela u AT-02. Provjera trenutne autorizacije na svakom zahtjevu, ne samo JWT claim. Podrška: SupportAccessGrant tenant/case scope, approver, purpose, expiry, revocation; predloženo najviše 24h po odobrenju; break-glass zaseban audit i naknadni pregled.

## 6. Podatkovni model i transakcije
Dodatni konceptualni entiteti: TenantAddress, TenantRepresentative, TenantChangeRequest, TenantClosureRequest, TenantContractAcceptance, ContractVersion, MembershipInvitation, MembershipGrant, BranchCodeCounter, CaseReassignmentQueue, SupportAccessGrant, ExportJob, AuditEvent, OutboxEvent. Globalni User/ContractVersion izvan tenant scope; svi tenant podaci tenant_id i RLS, composite FK (tenant_id,id), server provjeren tenant context prema ADR-002. Platform review preko posebno autoriziranog kontroliranog puta. Indeksi tenant/status, tenant/branch/status, tenant/user, expiry i queue due time. UTC timestamptz, prikaz lokalno; dnevni podsjetnik po tenant vremenskoj zoni (predloženo Europe/Madrid default, konfigurabilno).
Transakcije: zaključavanje tenant/branch pri aktivaciji, primarnoj promjeni, zatvaranju i dodjeli koda; provjera case intake pod istim zaključavanjem ili ekvivalentnom izolacijom. Prihvat pozivnice i zadnji OWNER concurrency-safe. Idempotency za mutacije prema ADR-004. Outbox za obavijesti; retry bez duplikata; ne blokira opoziv. Audit u istoj transakciji za poslovnu mutaciju, osjetljivi read audit zasebno pouzdano. Bez tajni/tokena i punih dokumenata u logovima.
ExportJob: scope, filters, categories, requester, status, private object, expires_at; ponovno provjeriti ovlasti pri generiranju i preuzimanju. Predložena dostupnost 24h; poništiti pristup pri opozivu. Audit kategorije, broj zapisa i preuzimanje, ne puni sadržaj.

## 7. Predloženi API ugovor
REST /api/v1 prema ADR-004, konačni OpenAPI prije implementacije. Operacije: POST /tenant-applications; GET/PATCH /tenant-applications/{id}; POST /tenant-applications/{id}/submit; POST /platform/tenant-verifications/{id}/review; GET/PATCH /tenants/{id}; POST /tenants/{id}/change-requests; POST /tenants/{id}/closure-requests; POST /platform/tenants/{id}/suspend|reactivate|close (zasebne rute); POST /tenants/{id}/contract-acceptances; GET/POST /tenants/{id}/branches; PATCH /tenants/{id}/branches/{branch_id}; POST branch activate/deactivate/set-primary; GET/POST /tenants/{id}/invitations; POST invitation accept/resend/revoke; GET/PATCH memberships i POST suspend/reactivate/revoke; PUT membership branch assignments/grants; POST owner-transfer-requests i platform review; POST /sessions/workspace; GET /sessions i DELETE /sessions/{id}; GET reassignment queue i POST reassignment; POST/GET exports i autorizirani download; GET audit events. Tenant path nije dokaz ovlasti. Paginacija, schema validation, idempotency keys za relevantne POST, optimistic version za izmjene. 401 neautentificiran, 403 nedopuštena radnja, 404 za nevidljivi resurs, 409 konflikt stanja/konkurencije, 422 nevaljani podaci; ne otkrivati drugi Tenant. API nazivi prijedlog, ne implementirani endpointi.

## 8. Kriteriji prihvata (dopuna postojećih)
- AT03-AC01: samostalna i ručna registracija prolaze istu provjeru; nema aktivacije bez dokaza, OWNER-a, ugovora i primarne poslovnice.
- AC02: paralelna registracija istog normaliziranog NIF-a ne stvara duplikat; pristupni zahtjev ne otkriva osoblje.
- AC03: promjena NIF-a nije direktna; novi subjekt nema povijest drugog Tenanta.
- AC04: BR-0001 automatski, neaktivan do odobrenja; konkurentni kodovi i primarna poslovnica zadovoljavaju invariant.
- AC05: zatvaranje poslovnice blokira intake i ne ostavlja otvorene predmete; povijest očuvana.
- AC06: MANAGER bez granta ne poziva; s grantom samo niže uloge u vlastite poslovnice; opoziv granta prije prihvata blokira pozivnicu.
- AC07: token istekao, opozvan, ponovno korišten ili pogrešan email ne aktivira članstvo; paralelni prihvat samo jednom.
- AC08: OWNER promjena zahtijeva platform approval i ne uklanja zadnjeg aktivnog OWNER-a pod konkurencijom.
- AC09: opoziv članstva blokira sve tenant sesije odmah, drugi Tenant ostaje dostupan.
- AC10: red preraspodjele ima odgovornog, operativni assignee ne dobiva neovlašten pristup; 72h eskalacija i dnevni podsjetnici bez duplikata.
- AC11: popust ne daje pravo odgođenog plaćanja; oba granta i limiti provjereni, konkurentne rezervacije ne prelaze kredit; tenant ne mijenja kreditni limit.
- AC12: kreditna blokada ne suspendira prepaid pristup; administrativna suspenzija blokira novi intake.
- AC13: reaktivacija ne vraća automatski kredit, zaposlenike ni stare dodjele.
- AC14: 2FA nije uvjet tenant prijave; reset token jednokratan; opoziv sesije učinkovit.
- AC15: cross-tenant i cross-branch ID manipulacija odbijena na API i DB razini; testovi RLS uključuju background job i export.
- AC16: izvoz zahtijeva sve relevantne kategorijske grantove; opoziv prije downloada blokira datoteku; istek i audit.
- AC17: support bez odobrenja nema poslovni pristup; grant istekne; break-glass opravdan i pregledan.
- AC18: verifikacijski dokumenti nisu javni ni dostupni običnim zaposlenicima; retention i legal hold testirani prema odobrenoj politici.
- AC19: ugovor verzioniran; prihvaćanje vezano uz ovlaštenog zastupnika i točnu verziju.
- AC20: audit ne sadrži tajne i ne može ga izmijeniti tenant korisnik; promjene ovlasti i financijske radnje sljedive.

## 9. Usklađivanje i granice
ADR-009: dopuniti delegirani MANAGER, platform approval OWNER promjena, automatski BR-0001, precizne lifecycle i grantove; zadržati samo OWNER upravlja ADMIN-om i više OWNER-a. tenant-branch: MANAGER transfer zahtijeva grant; EMPLOYEE može tražiti, ne izvršiti; closure dopušta formalni dovršetak, intake block. tenant-membership: delegirani inviter, ponovna provjera, odgovornost reda vs operativni assignee, dodatne ovlasti i session scope. Primjeri MAR-01 zamijeniti BR-0001 formatom.
Ovisnosti: AT-02 identity/session/recovery; AT-07 završni statusi i dodjele predmeta; AT-09 storage; AT-12/13/14 financijski limiti i atomarna rezervacija; AT-16 obavijesti; AT-17 platform review; AT-19 izvještaji; AT-20 pravne osnove, retention, ugovori. Prije produkcije provjeriti službene španjolske izvore, pravila ugovora i rokove. Nije potrebno izmišljati nova poslovna pitanja za standardne tehničke detalje.
Novi defaulti za pregled: obvezna polja, ugovor prije aktivacije, granularna matrica, odgovornost reda umjesto automatskog operativnog assignee-a, financijski limiti po predmetu, 30 min reset, 30 min idle/12h web session, 24h support i export. Sve ostalo primjena potvrđenih odluka. Nakon korisničkog pregleda uskladiti ADR/specifikacije i izraditi zaseban plan implementacije. Nema implementacije/deploymenta.
