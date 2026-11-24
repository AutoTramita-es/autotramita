# AT-04 — Klijenti i vlasnici vozila
Datum: 2026-11-24 | Verzija 0.1 | Status: PROPOSED — za pregled vlasnika proizvoda. Bez implementacije/deploymenta.

## 1. Izvori i granice
Obvezujući: [ADR-002](../adr/ADR-002-multi-tenancy-rls.md), [ADR-003](../adr/ADR-003-identity-customer-membership.md), [ADR-004](../adr/ADR-004-api-contracts.md), [ADR-005](../adr/ADR-005-document-storage.md), [ADR-006](../adr/ADR-006-service-catalog-case-workflows.md), [ADR-007](../adr/ADR-007-pricing-credit-payments.md), [ADR-009](../adr/ADR-009-tenant-organization-membership-verification.md), [AT-03](AT-03-decisions.md), [tenant-membership](tenant-membership.md), [tenant-branch](tenant-branch.md). Sve nove odluke ispod su prijedlozi, ne prihvaćeni ADR. AT-03 novije odluke o prijenosu i preraspodjeli imaju prednost pred starijim nacrtima; usklađivanje ostaje zadatak AT-03/07.

## 2. Registar predloženih odluka
- D01: User je globalni login; Customer je lokalna stranka (fizička ili pravna osoba). Bez globalnog CRM-a.
- D02: Klijent, naručitelj, platitelj, kupac, prodavatelj, sadašnji/budući vlasnik, suvlasnik, držatelj i zastupnik su odvojene uloge po predmetu. Ista stranka može imati više uloga.
- D03: Klijent može nastati bez računa i bez emaila. Izraz anonimni zahtjev znači bez računa, ne bez zakonski potrebnog identiteta.
- D04: Autokuća unosi klijenta; samostalni javni unos koristi serverom odobreni intake kontekst. Ako nije vezan uz autokuću, predlaže se zaseban interni intake tenant, bez izlaganja drugim tenantima; potvrditi s AT-03/07 prije realizacije.
- D05: Jedan Customer po stvarnoj stranci unutar tenanta kao cilj, ne globalno; poslovnice dijele zapis samo uz izričitu autorizaciju.
- D06: NIF/DNI/NIE, strani porezni broj ili putovnica prema državi i postupku. Strukturna validacija nije dokaz identiteta; ne izmišljati identifikatore.
- D07: Kontakt, identitet, ovlast zastupanja i vlasništvo imaju neovisne provjere.
- D08: Email/telefon mogu biti zajednički; nisu jedinstveni identifikatori stranke niti dokaz prava na predmet.
- D09: Duplikati: točno podudaranje provjerenog identifikatora pokreće kontrolirano ponovno korištenje ili pregled; neprovjereni i približni rezultati samo kandidati. Bez automatskog spajanja.
- D10: Spajanje unutar tenanta uz posebnu dozvolu, pregled konflikata i audit; bez fizičkog brisanja povijesti ili automatskog prijenosa pristupa.
- D11: Customer.user_id opcionalan, samo za verificiranu fizičku osobu; pravne osobe pristupaju preko eksplicitnih ovlasti zastupnika, ne zajedničkog logina.
- D12: Claim pojedinačnog predmeta ne daje pristup svim predmetima istog Customer zapisa.
- D13: Claim zahtijeva verificirani login, jednokratni kratkotrajni token i dokaz prava na konkretan predmet; email sam nije dovoljan.
- D14: Sporovi, promjene kontakta i nedostatak pouzdanog dokaza idu u ručnu provjeru; bez sigurnosnih pitanja temeljenih na javnim podacima.
- D15: Pristup zastupnika vremenski i sadržajno ograničen, opoziv odmah; dokaz ovlasti odvojen od portalnog pristupa.
- D16: Vlasništvo nad vozilom je povijesna činjenica s izvorom i statusom provjere u AT-05; zahtjev za prijenos nije dokaz dovršenog prijenosa.
- D17: Predmet zadržava verzionirani snapshot relevantnih podataka stranke; izmjena CRM-a ne prepisuje potpisane obrasce, račune ili podneske.
- D18: Klijent može ažurirati vlastite kontaktne podatke uz provjeru; pravni identitet i zastupanje kroz kontrolirani zahtjev.
- D19: Poslovni i osobni portal su odvojeni konteksti; zaposlenik ne dobiva dodatna prava zato što je klijent.
- D20: Dokumenti u AT-09, privatni pristup prema svrsi; bez javnih URL-ova ili kopiranja među tenantima.
- D21: Arhiviranje klijenta ne briše predmete niti automatski opoziva zakonito portalno pravo. Brisanje/ograničenje prema AT-20.
- D22: Platitelj ne postaje vlasnik ili ovlaštenik; financije i kredit ostaju AT-12–14.
- D23: Izvoz osobnih podataka posebna dozvola, opseg poslovnice i audit prema AT-03.
- D24: Španjolski primarni UI, podrška međunarodnim imenima, adresama i jezicima; bez obveznog drugog prezimena.
- D25: Nema automatske DGT/AEAT provjere bez potvrđene dostupnosti i ovlasti; ručni dokaz i status izvora.

## 3. Konceptualni model
Sve tablice osim globalnog User imaju tenant_id, UUID, created_at/updated_at UTC, tenant-aware FK; statusi i povijest prema svrsi.
| Entitet | Ključna polja i pravila |
|---|---|
| Customer | id, tenant_id, user_id nullable, type PERSON/ORGANIZATION, status ACTIVE/ARCHIVED/MERGED, display_name, preferred_language, version, merged_into_id nullable |
| PersonDetails | customer_id, given_names, surnames, birth_date samo kada potrebno, nationality samo kada potrebno |
| OrganizationDetails | customer_id, legal_name, trade_name optional, legal_form, registration_country |
| CustomerIdentifier | customer_id, type, issuer_country, encrypted_value, tenant-scoped keyed fingerprint, verification_status, verified_at, evidence_ref, valid_from/to |
| CustomerContact | customer_id, type EMAIL/PHONE, normalized_value, purpose, verification_status, verified_at, primary flag |
| CustomerAddress | customer_id, purpose RESIDENTIAL/REGISTERED/BILLING/POSTAL, lines, postal_code, locality, province, country, validity |
| CustomerBranch | customer_id, branch_id, grant source, status, created_by; explicit relation, no implicit access from search |
| CaseParty | case_id, customer_id, role, snapshot_version, status, source; unique case/customer/role |
| PartySnapshot | case_party_id, version, necessary identity/address fields, captured_at, reason, document references; immutable after submission |
| Representation | principal_customer_id, representative_customer_id, scope, case_id optional, validity, evidence_ref, status, reviewer |
| CaseAccessGrant | case_id, user_id, party_id, permissions, basis, representation_id optional, expiry, status |
| ClaimRequest | case_id, intended party, token_digest, expires_at, attempts, status, requester_user_id, evidence_ref, reviewer |
| VerificationReview | subject, type, status, source, evidence_ref, reviewer, timestamps, reason |
| MergeRequest | source/target customer, conflict resolution, reviewer, status, mapping, audit reference |
| PrivacyRequest | subject, request type, verification, status, due date per AT-20, resolution |
No document bytes, passwords, payment card data or vehicle ownership source of truth in Customer. Type changes after use require correction review, not destructive conversion. At most one active verified identifier of a given issuer/type/value per tenant across canonical customers, subject to validated identifier semantics. Fingerprints keyed per tenant, never public. Contact verification belongs to a specific contact version.

## 4. Permissions and isolation
OWNER/ADMIN: all authorized branches, explicit cross-branch CRM view; MANAGER: assigned active branch, create/edit, merge only with special permission; EMPLOYEE: selected authorized branch, create/edit ordinary data, request verification/merge; VIEWER: read-only authorized branch, masked sensitive fields. All roles require explicit sensitive-document/export permissions. Default lists selected branch; no arbitrary branch parameter. Existing Customer outside branch: blind request to authorized reviewer, no identity disclosure or existence oracle; reviewer may grant branch relation for documented purpose. Case transfer grants destination only necessary party visibility, not all historical cases. Shared master-field changes affecting other branches require OWNER/ADMIN review when sensitive; no cross-branch case disclosure.
Customer portal: only explicit active CaseAccessGrant and permitted fields/actions; no internal notes, dealer margin, credit or other parties' documents by default. Organization representatives each use personal User and verified Representation. Partner/gestor: case-specific assignment and minimum data, no CRM browse. AutoTramita support follows AT-03 scoped access; exceptional access audited. Revocation checked on every request including downloads, jobs and export delivery. RLS forced, transaction-local tenant context, composite FK; portal enumerates authorized grants through separately authorized broker then reads each tenant in its own transaction, never disables RLS.

## 5. Workflows
### Intake
Select existing authorized customer or create minimal record (type/name and contact if available); attach case parties; service version defines required data/documents before submission. Guest receives opaque receipt, no sequential public ID. Public submission is rate limited, abuse protected, idempotent; draft upload scoped and quarantined. No case processing until tenant/branch active and service requirements met. Direct intake routing remains a gate.
### Verification
UNVERIFIED -> PENDING -> VERIFIED / MORE_INFO_REQUIRED / REJECTED; VERIFIED -> EXPIRED/REVOKED on evidence expiry or invalidation. Automated syntax checks only; official or manual evidence recorded. No universal mandatory KYC assumption; service/risk rules determine requirements. Changes invalidate only affected verification, not historical evidence.
### Claim
Authorized intake operator identifies eligible party and verifies entitlement evidence; issue random >=128-bit token, store digest only, proposed 30-minute expiry, single-use, bound to case/party and intended verified contact when available. Delivery contains no sensitive data. User authenticates and verifies email, presents token plus independent entitlement evidence (e.g. reviewed identity/authority matching party). A token alone or email match alone never grants access. Manual review when no reliable channel; no automatic claims based on names, VIN or NIF. ISSUED -> PENDING_REVIEW -> APPROVED/REJECTED, or EXPIRED/REVOKED; approval atomically consumes token and creates grant; if review exceeds expiry issue fresh token after review. Resend revokes old token; max 5 failed attempts per token proposed, rate limits by account/IP/context; generic errors. Concurrent claims locked; disputed claim freezes affected grant pending review, preserves legitimate unrelated access. No automatic global user linkage or bulk grants; optional Customer.user_id link separately verified.
### Representation
DRAFT -> PENDING -> ACTIVE -> EXPIRED/REVOKED; reject invalid evidence. Verify principal, representative, scope, dates and legal basis per service. Minor/incapacity, deceased owner, estate, leasing and corporate signatories require manual specialist review. Portal grant separate and cannot outlive representation. Revocation blocks future actions, preserves past lawful acts; notify AT-07 for pending submissions.
### Merge
Detect candidates only within tenant; authorized reviewer compares identifiers, snapshots, contacts, grants and disputes. Conflicting verified identities block merge. Lock records, choose canonical target, migrate approved operational references, preserve original snapshots and source alias, re-evaluate grants individually; audit before/after without raw sensitive values. No cross-tenant merge; no cycles; idempotent. Correction of erroneous merge requires controlled compensating review and restoration from recorded mapping, not blind undo.
### Ownership
AT-04 supplies parties and evidence; AT-05 records effective ownership intervals, shares where relevant, source and verification. AT-07 triggers update only after authoritative completion evidence; rejected/canceled transfer does not change current owner. Distinguish registered holder, legal owner and applicant; no inferred ownership from payment or portal login.
### Lifecycle
ACTIVE -> ARCHIVED -> ACTIVE with authorized review; MERGED terminal alias except controlled correction. Archive blocks new use until restored, not ongoing case obligations. Privacy request verified, routed to AT-20; legal hold prevents premature deletion; erase/anonymize eligible data and derived caches/indexes, handle backups under approved policy.

## 6. API contract proposal
All under /api/v1; exact shared error/pagination conventions pending AT-01/02. Tenant workspace server-resolved; no trusted tenant_id from body. Explicit response schemas and field allowlists.
| Method/path | Behavior |
|---|---|
| GET/POST /customers | scoped list/create; cursor, q, type, status; minimal results |
| GET/PATCH /customers/{id} | scoped detail/update; version or If-Match; sensitive fields separate review |
| POST /customers/{id}/archive or /restore | authorized transition, reason |
| POST /customers/{id}/identifiers | encrypted identifier submission, verification pending |
| POST /customers/{id}/verification-requests | review request; evidence references |
| POST /customer-merge-requests | candidate pair and reason |
| POST /customer-merge-requests/{id}/approve | privileged review and atomic merge |
| GET/POST /cases/{id}/parties | case-specific party list/add |
| PATCH /cases/{id}/parties/{party_id} | versioned role correction, workflow restrictions |
| POST /cases/{id}/claim-invitations | authorized issuance, no raw token in response/log |
| POST /public/intake | guest submission, scoped receipt |
| POST /me/claims | authenticated claim submission, generic failure |
| GET /me/cases | explicit grant-scoped cross-tenant list |
| GET /me/cases/{id} | sanitized case projection |
| POST /representations | submit evidence and scope |
| POST /representations/{id}/revoke | revoke and invalidate dependent grants |
| POST /privacy-requests | verified request, restricted workflow |
401 unauthenticated; 403 forbidden action when existence safely known; 404 for inaccessible object; 409 conflict/state; 422 validation; 429 rate limit. No raw identifiers in URLs. Idempotency for intake, claim, merge, grant/revoke; same key different payload conflict. Optimistic versioning for edits, transactional locks for merge/claim. OpenAPI generated clients and contract tests.

## 7. UX and integrations
Dealer: customer search/create, profile tabs (contacts, identifiers masked, addresses, authorized cases, representation), duplicate review, case party picker. Guest: service form, evidence upload, receipt, optional account creation. Portal: own cases grouped by dealership, representation selector, missing-document requests, claim status, privacy/contact settings. Never display other tenant customer records. Admin: verification/merge/dispute queues, restricted audit. Notifications AT-16 via transactional outbox; no sensitive attachments, reauthorize deep links. Events CustomerCreated/Updated/Merged, CasePartyChanged, ClaimGranted/Revoked, RepresentationRevoked, VerificationChanged; tenant + opaque IDs, version, event ID; consumers deduplicate and reauthorize. AT-05 ownership, AT-07 workflow/snapshot, AT-09 documents, AT-10 regulated acts, AT-14 billing, AT-18 UI, AT-20 privacy. No automatic financial or legal effects from CRM changes.

## 8. Privacy and security
Minimize collection by service; distinguish contract/legal obligation/other lawful basis from optional marketing consent; no blanket consent. AT-20 must determine controller/processor roles, notices, legal bases, retention by record category, rights handling, international transfers and legal holds. Proposed encryption in transit/at rest plus field encryption for identifiers, tenant-specific keyed lookup, restricted key access, rotation plan. No raw IDs, tokens, documents or full addresses in logs/events/analytics. Audit actor, tenant, branch, object, action, reason, time, outcome, redacted changes; audit sensitive reads and exports. No production personal data in tests. Threats: IDOR, enumeration, token replay, shared email, insider export, stale grant, cross-tenant cache, malicious upload, merge hijack. Apply rate limits, generic errors, access checks, audit, short-lived signed downloads and quarantine. Legal sources to verify before implementation: GDPR (EUR-Lex Regulation 2016/679), LOPDGDD (BOE Ley Orgánica 3/2018), DGT official procedure requirements and representation rules; no legal validation claimed.

## 9. Acceptance tests (future)
AC01 guest without User creates tenant-scoped customer; AC02 missing email allowed where service permits; AC03 company and person validation differ; AC04 shared email never auto-merges; AC05 same identity in two tenants remains isolated; AC06 forged tenant/branch rejected; AC07 inaccessible branch search leaks no existence; AC08 transfer preserves source history and limits destination scope; AC09 VIEWER cannot mutate; AC10 sensitive export requires separate permission; AC11 exact verified duplicate handled under concurrency; AC12 conflicting IDs block merge; AC13 merge preserves snapshots; AC14 merge never expands grants; AC15 expired/replayed token rejected; AC16 email alone denied; AC17 concurrent claim grants once; AC18 claim one case exposes no other cases; AC19 employee/customer contexts independent; AC20 representation expires and revokes access; AC21 company users have individual grants; AC22 disputed claim isolated; AC23 contact change does not rewrite historical snapshot; AC24 canceled transfer leaves ownership unchanged; AC25 payer cannot infer access; AC26 private documents enforce case entitlement; AC27 revoked grant blocks new downloads/jobs; AC28 archive preserves ongoing obligations; AC29 legal hold blocks erasure; AC30 audit redacts identifiers/tokens; AC31 background worker without tenant fails closed; AC32 cache/search/export isolated; AC33 idempotency rejects changed payload; AC34 concurrent edits detect stale version; AC35 notification failure does not roll back grant; AC36 portal shows only sanitized projections; AC37 suspended tenant follows AT-03 restrictions without automatically destroying customer rights; AC38 international names/addresses supported; AC39 no external registry availability assumed; AC40 OpenAPI contract and generated client tests pass.

## 10. Review gates and delivery
Owner review of D01–D25, especially public intake tenant, branch CRM visibility, merge authority, claim parameters and representation. AT-02 identity/recovery, AT-03 permission reconciliation, AT-05 ownership contract, AT-06 service-specific requirements, AT-07 case transitions, AT-09 evidence handling, AT-20 legal review and retention must be aligned before implementation. Proposed delivery slices: domain/RLS tests; CRM/branch access; case parties/snapshots; guest intake and claim; representation/ownership integration; privacy/export/audit; end-to-end tests. Each requires separately approved execution task. No migrations, code, deployment or accepted ADR changes authorized.
