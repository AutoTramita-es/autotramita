# AutoTramita.es — MASTER BLUEPRINT

> **Current status pointer (REC-07.4, 2026-11-24):** F1 implementation T01–T10 is accepted (CP10) and REC-07.1–07.3 are accepted; REC-07.4 and REC-07.5 are accepted. **F1: COMPLETED / ACCEPTED FOR DEVELOPMENT AND CI. REC process: CLOSED. F2: PLAN ACCEPTED (CP00, D01–D41 and D43; D42 OPEN); CP01–CP08 accepted 2026-11-24; F2-T09-REC implemented including owner decisions F-0 (a), F-1 (b), F-1R (d), F-2, F-3, F-4, the final MFA decision (option A) and the Keycloak security provider and the Final Completion Order (8e49b91); Keycloak upgraded to 26.8.2 for development, tests and CI (owner authorization D45, one-time 14-day exception; production not upgraded); **F2-T09-REC — IMPLEMENTATION COMPLETED / OWNER SECURITY DECISION REQUIRED**: every test passes, the Trivy scan finds 0 CRITICAL / 6 HIGH (was 9 / 93), each analysed and awaiting the owner's decision; CP09 is not accepted ([report](design/F2-CP09-RECONCILIATION-REPORT.md)); mandatory STOP at F2-CP09** (T10–T13 not authorized; see [F2 execution order](design/F2-EXECUTION-ORDER.md)). Release option 3: F1 stays on `dev`; `main` is unchanged. Deferred production prerequisites (R05, R11, R12, real trusted proxy networks, the 15 PROPOSED decisions) block only the corresponding production operations. The status blocks below are historical records, not current authorization. Authoritative current state: [F1 reconciliation plan](design/F1-RECONCILIATION-PLAN.md) and [REC-07.4 scope review](design/F1-REC-07-4-SCOPE-REVIEW.md). Normative requirements are unchanged; no merge, deployment or shared-infrastructure access is authorized.

**Status:** MASTER INDEX / WORKING BLUEPRINT (not implementation authorization)  
**Version:** 1.6
**Date:** 2026-11-24  
**Repository:** [AutoTramita-es/autotramita](https://github.com/AutoTramita-es/autotramita)  
**Language:** Croatian for planning; existing technical ADRs remain authoritative.

## Current F1 status — REC-02
REC-02 (2026-11-24): F1 implementation exists on f1/foundation at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a, preserved identically in archive/f1-foundation-2026-11-24; not merged or accepted. Historical broad authorization quoted in c467005 ("Autoriziram F1 prema G6-EXECUTION-ORDER.md") is UNVERIFIED: repository record exists, original owner instruction not established; neither confirmed nor invalidated retroactively. Later explicit T01-only authorization b6462e4 / 0973e24 remains recorded; CP01 blocked in preflight, no new implementation authorized or executable during reconciliation. T02–T10 not currently authorized. Audit reports 93 passing CI tests at e22ae3b (run 45398235580), not independently rerun; T01–05/T08–10 PARTIAL, T06–07 NON-COMPLIANT; AC05–08 compliant per reported CI, 7 partial, 3 non-compliant, AC09 not verified. F1 acceptance pending REC-07. REC-01 and REC-02 documentation approved; REC-03–07 require separate approval. No merge, deployment, F2 or infrastructure changes authorized. O01/O02/O03/O18/O19 remain ACCEPTED; 15 deferred decisions remain PROPOSED. Maintenance page and routing reported on implementation branch; live state and separate authorization unverified. Preserve both histories; no duplicate implementation or automatic cherry-pick.

[Audit](design/F1-RECONCILIATION-AUDIT.md) | [Plan](design/F1-RECONCILIATION-PLAN.md)

## 1. Purpose and scope

AutoTramita.es is a Spanish multi-tenant SaaS platform for vehicle-related administrative procedures, connecting dealerships (including autónomos), end customers, AutoTramita operators and authorized external professional partners. This blueprint is the central navigation index for 20 workstreams; it is **not** a claim that those features are implemented or approved in detail.

The existing ADRs and specifications take precedence over high-level summaries here, except where a later explicit user decision supersedes them, as recorded in [DNS, Nextcloud and mail](DNS-NEXTCLOUD-MAIL.md). A status such as “ADR accepted” applies to the referenced core decision, **not** to every feature or outstanding detail in the module. Unresolved decisions must remain open until explicitly approved.

## 2. Accepted architectural foundation

- **ADR-001:** Python/FastAPI modular monolith, Pydantic v2, PostgreSQL, SQLAlchemy 2.x, Alembic, psycopg 3, Redis/Celery, Next.js/TypeScript, Flutter, Docker Compose. Its S3-compatible storage proposal is superseded by the later shared Nextcloud decision in [DNS, Nextcloud and mail](DNS-NEXTCLOUD-MAIL.md).
- **ADR-002:** Shared PostgreSQL tenant-scoped tables, server-validated tenant context and enforced row-level security (RLS).
- **ADR-003:** Global user identities, tenant-local customers and memberships, controlled anonymous-case claiming.
- **ADR-004:** REST `/api/v1/`, OpenAPI-first generated TypeScript/Dart clients, idempotency and contract tests.
- **ADR-005:** Private document storage with tenant/case authorization, audit and retention design.
- **ADR-006:** Centrally versioned service catalog, case workflows, authorized gestoría partners, integrated outsourced Ficha Reducida.
- **ADR-007:** Unified public retail prices, dealership-funded discounts, centrally managed dealership credit and payment collection; unresolved provider/funds-flow details remain open.
- **ADR-008:** Architecture/specification approval before module-by-module Claude Code implementation.
- **ADR-009:** One tenant per legal entity, branches, membership roles and verification with manual AutoTramita approval.

## 3. Twenty modules

| ID | Module | Scope | Existing ADRs | Status |
|---|---|---|---|---|
| **AT-01** | Temelj sustava i infrastruktura | FastAPI, PostgreSQL, Redis, Celery, Docker, CI/CD, razvojna i produkcijska okruženja. | [ADR-001](adr/ADR-001-technology-stack.md), [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-004](adr/ADR-004-api-contracts.md), [ADR-008](adr/ADR-008-delivery-governance.md) | [AT-01 v1.1 APPROVED](specifications/AT-01-foundation-infrastructure.md); 5 F1 odluka potvrđeno, 15 otvoreno; F1 implementation on separate branch; RECONCILIATION / NOT ACCEPTED; REC-03 pending |
| **AT-02** | Korisnički računi i sigurnost | Prijava, registracija, OIDC, e-mail verifikacija, sesije, MFA, uloge. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | [F2 plan PROPOSED, čeka F2-CP00](specifications/AT-02-identity-security.md) — 13 paketa, 14 CP; bez implementacije; osnovne odluke ADR-010/003/002 Accepted |
| **AT-03** | Autokuće, poslovnice i zaposlenici | Tenant, NIF, pravni oblici, provjera autokuća, poslovnice, pozivnice i pristupi. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-007](adr/ADR-007-pricing-credit-payments.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | [27 poslovnih odluka potvrđeno](specifications/AT-03-decisions.md); tehničko usklađivanje prije implementacije |
| **AT-04** | Klijenti i vlasnici vozila | Fizičke i pravne osobe, anonimni zahtjevi, korisnički profili, zastupanje, povezivanje predmeta. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | [AT-04 specifikacija — prijedlog za pregled](specifications/AT-04-customers-vehicle-owners.md); bez implementacije |
| **AT-05** | Registar vozila | VIN, registracije, tehničke karakteristike, vlasništvo i povijest. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za razradu |
| **AT-06** | Katalog administrativnih usluga | Registracija, prijenos vlasništva, uvoz, tehnička dokumentacija i drugi postupci. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Osnovna arhitektura prihvaćena |
| **AT-07** | Predmeti i radni procesi | Otvaranje, statusi, zadaci, dodjele, kontrolne liste, završetak i arhiva. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Osnovna arhitektura; detalji otvoreni |
| **AT-08** | Rokovi, prioriteti i nadzor predmeta | Zakonski i interni rokovi, službeni kalendari, nadležnosti, revizije i eskalacije. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Opsežna specifikacija; bez implementacije |
| **AT-09** | Dokumenti i digitalna obrada | Upload, PDF, OCR, klasifikacija, validacija, potpisi, predlošci, Nextcloud i audit. | [ADR-005](adr/ADR-005-document-storage.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Zajednički Nextcloud dostupan; integracija i detalji otvoreni |
| **AT-10** | Gestorías i profesionalni partneri | Ovlašteni gestor administrativo, partneri i delegiranje reguliranih radnji. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za razradu |
| **AT-11** | Vanjski inženjeri i Ficha Reducida | AutoTramita naručuje Ficha Reducida od kvalificiranog vanjskog inženjera u pozadini. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Poslovni princip prihvaćen; tijek za razradu |
| **AT-12** | Cjenik, ponude i popusti | Jedinstveni javni maloprodajni cjenik, popusti autokuća, marže, zasebne pristojbe. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; detalji otvoreni |
| **AT-13** | Kreditni limiti autokuća | Centralno odobreni limiti, rezervacije, dospijeća, blokade i reaktivacija. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; detalji otvoreni |
| **AT-14** | Plaćanja, fakture i naplata | Kartice, SEPA, računi, IVA, odgođena naplata, povrati i usklađivanje. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; pružatelj i tok novca otvoreni |
| **AT-15** | Integracije sa španjolskim institucijama | DGT, AEAT, ITV, registri, službeni obrasci, identifikacija i statusi. | [ADR-004](adr/ADR-004-api-contracts.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za pravnu i tehničku provjeru |
| **AT-16** | Obavijesti i komunikacija | E-mail, in-app, dopune, predlošci i praćenje isporuke. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Djelomično definirano |
| **AT-17** | Centralna administracija AutoTramite | Odobravanje autokuća, nadzor, partneri, cjenici, financije, sporovi. | [ADR-007](adr/ADR-007-pricing-credit-payments.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Minimalni dio (platform_grants, audit, administracija korisnika) planiran u [F2](design/F2-IMPLEMENTATION-PLAN.md), PROPOSED; ostatak za razradu |
| **AT-18** | Portali i mobilne aplikacije | Javni web, klijentski portal, autokuće, backoffice i Flutter Android/iOS. | [ADR-001](adr/ADR-001-technology-stack.md), [ADR-004](adr/ADR-004-api-contracts.md) | Tehnologija odabrana; javni web i 11 SaaS UX faza dokumentirani za pregled; zajednički dizajn i odobrenja otvoreni |
| **AT-19** | Izvještaji i poslovna analitika | Naplata, marže, broj predmeta, trajanje obrade, poslovnice, produktivnost. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-007](adr/ADR-007-pricing-credit-payments.md) | Za razradu |
| **AT-20** | Pravna usklađenost i operacije | GDPR, ovlasti, audit, backup, monitoring, incidenti i ugovori. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-005](adr/ADR-005-document-storage.md), [ADR-008](adr/ADR-008-delivery-governance.md) | Djelomično definirano |

## 4. Existing source documentation

- [AT-01 foundation specification v1.1](specifications/AT-01-foundation-infrastructure.md) — APPROVED 2026-11-24; 15 deferred decisions remain PROPOSED; [G6 execution order](G6-EXECUTION-ORDER.md) Accepted; F1 reconciliation pending.

- [DNS, Nextcloud and mail](DNS-NEXTCLOUD-MAIL.md) — current domain and infrastructure decisions, deployed components and remaining work.
- [Docker Compose operations](DOCKER-COMPOSE.md) — prepared environments, shared services, configuration and prerequisites; not evidence that the application stack is deployed.

- [Master Design Blueprint](design/MASTER-DESIGN-BLUEPRINT.md) — consolidated design review, verified indexed assets, gaps and approval gates; not implementation authorization.

- [AT-02 identity and security specification (F2, PROPOSED 2026-11-24)](specifications/AT-02-identity-security.md) — plan: [implementation](design/F2-IMPLEMENTATION-PLAN.md), [execution order](design/F2-EXECUTION-ORDER.md), [acceptance criteria](design/F2-ACCEPTANCE-CRITERIA.md), [decision register](design/F2-DECISION-REGISTER.md); awaiting owner review at F2-CP00; no implementation authorized.

- [AT-04 customer and vehicle owner specification](specifications/AT-04-customers-vehicle-owners.md) — 25 proposed decisions and 40 acceptance criteria; pending product-owner review.

- [AT-03 decision register](specifications/AT-03-decisions.md) — all 27 confirmed business decisions; implementation not authorized.

- [ADR register](adr/ADR-REGISTER.md) — ADR-001 through ADR-009 Accepted as of 2026-11-23; ADR-010 (Keycloak) and ADR-011 (shared Nextcloud) Accepted 2026-11-24.
- [TenantBranch specification](specifications/tenant-branch.md) — approved business rules, no implementation.
- [TenantMembership and workspace specification](specifications/tenant-membership.md) — draft containing confirmed decisions; no implementation.
- [Case deadlines and priority specification](specifications/case-deadlines.md) — design approved in principle, no implementation.

The current repository includes placeholder folders `app/api`, `app/auth`, `app/billing`, `app/cases`, `app/core`, `app/credit`, `app/customers`, `app/documents`, `app/integrations`, `app/services`, `app/tenants`, `app/vehicles`, `migrations` and `tests`. On main these are placeholders; the separate F1 branch contains foundation code, not accepted business modules. The AT-01–AT-20 workstreams are logical planning units, not a mandated one-folder-per-module code layout.

## 5. Collaboration and separate conversation rules

1. Use a dedicated conversation titled `AT-XX — <module name>` for each module; split into additional conversations only when scope becomes too large.
2. At the beginning of each conversation, read this blueprint, the ADR register, all linked ADRs and relevant specifications **from GitHub**; do not rely on an outdated chat summary.
3. Advance **one decision or one step at a time**. Ask the product owner to confirm unresolved business decisions before recording them as accepted.
4. Keep a clear separation between **Accepted**, **Approved business rules**, **Draft/Proposed**, **Open decisions**, **Implemented** and **Deployed**. These statuses are not interchangeable.
5. For each module define: purpose, actors and permissions, business rules, workflow/state transitions, data model and tenant boundaries, API contracts, integrations, financial/legal impacts, security/privacy, acceptance criteria, dependencies and open decisions.
6. Record approved architecture in an ADR (or explicit amendment/superseding ADR), and detailed behavior in `docs/specifications/`. Cross-reference both from this index. Do not silently overwrite an accepted ADR.
7. Changes affecting another module require a documented cross-module dependency and consistency review; preserve the single source of truth.
8. ChatGPT and the product owner define and approve architecture/specifications. Claude Code implements **only** separately authorized, sufficiently specified tasks; require tests and review. Do not infer implementation authorization from this blueprint.
9. No code, migrations, infrastructure changes, deployments or payment transactions are authorized by creating or editing this document.
10. Verify legal/regulatory requirements and official Spanish sources before treating any deadline, administrative entitlement, DGT/AEAT/ITV access, professional act, tax or payment flow as legally valid.

## 6. Recommended sequence

**First design focus: AT-03 — Autokuće, poslovnice i zaposlenici.** Existing ADR-009 and tenant specifications provide the most developed foundation. The 27 business decisions are now recorded; reconcile detailed specifications before separately authorizing implementation.

Next modules should be selected according to dependencies, not forced into a rigid all-at-once roadmap. A useful early chain is AT-02/AT-03 → AT-04/AT-05 → AT-06/AT-07/AT-08/AT-09; financial and regulated integrations require their own approvals before production use.

## 7. Cross-cutting decisions to keep open

- Keycloak is the chosen identity provider; deployment, configuration, precise permissions, account recovery, privacy retention and security controls remain open.
- Full service catalog, exact per-service regulatory requirements, case state machines and partner integrations.
- Payment provider, merchant-of-record/funds flow, discounts/invoice allocation, holiday calendars and collection policies under ADR-007.
- Official DGT/AEAT/ITV integration availability, authority to perform regulated acts, and legal evidence sources.
- Backup/recovery provider and procedures, independent monitoring, test strategy and operational SLAs. The current shared-server topology and partially deployed components are recorded in [DNS, Nextcloud and mail](DNS-NEXTCLOUD-MAIL.md).

## 8. Blueprint maintenance

Update this file when a module is added, renamed, split, superseded or its verified status changes. Link to the approved decision/specification; do not replace them with an informal summary. Record substantive changes in Git commits. This document remains a **planning index**, not an executable specification or deployment plan.

## 9. Design roadmap follow-up — 2026-11-24
[Design Roadmap](design/DESIGN-ROADMAP.md) proposes dependency slices, limited prepaid commercial MVP, manual Tramisur and integrated Ficha procurement, and readiness/release gates. All five originally missing design documents drafted for review; no domain approval or implementation inferred. G5 foundation technical review completed and G6 bounded execution order accepted; AT-01 v1.1 approved. Execution brief v1.0 approved; REC-03 DEV consolidation preparation approved. No deployment authorization.

## 10. Infrastructure status — 2026-11-24

- Cloudflare DNS is active. `autotramita.es` serves a temporary development page through the running PROD tunnel and shared Traefik; `www` redirects to the apex. Other PROD application hostnames currently fall through to 404. Nested DEV hostnames use a DNS-only wildcard `*.dev.autotramita.es` directly to shared Traefik, with an issued Let's Encrypt wildcard certificate and an HTTP 418 fallback until application routers exist. The separate DEV tunnel runs but is not used by those nested hostnames.
- Existing `cloud.autotramita.es` reaches the shared Nextcloud through Cloudflare and Traefik. PROD and DEV will use that instance with separate service accounts and folder roots; these accounts and roots are not yet provisioned. Existing shared PostgreSQL, Traefik, mailserver and SnappyMail are to be reused; Uptime Kuma is a monitoring candidate on the same host.
- PROD and DEV Docker Compose configurations and database provisioning script are prepared and validated. The application, Keycloak, Redis, ClamAV and DEV Mailpit services are not deployed, and main contains placeholders; separate F1 implementation branch exists and is not accepted. Database roles and databases have not yet been provisioned by the script.
- DNSSEC, SMTP/domain setup, transactional mail provider, Nextcloud integration, authentication, malware scanning and backup/recovery remain incomplete. Cloudflare Zero Trust is not required by the current decision. See [DNS, Nextcloud and mail](DNS-NEXTCLOUD-MAIL.md) and [Docker Compose operations](DOCKER-COMPOSE.md) for details and current limitations.

- **Design raster import — 2026-11-24:** 80 raster candidates imported into [design/assets](design/assets/MANIFEST.csv) via Git LFS (see [Master Design Blueprint §15](design/MASTER-DESIGN-BLUEPRINT.md)); not approved for release.
- **G5 foundation review — 2026-11-24:** see [FOUNDATION-G5-REVIEW.md](design/FOUNDATION-G5-REVIEW.md); ADR-010 and ADR-011 later Accepted; [G6 execution order](G6-EXECUTION-ORDER.md) Accepted; F1 not yet authorized.

- **AT-01.04 — 2026-11-24:** owner approved AT-01 v1.1; G6 prerequisites updated. Fifteen open decisions remain assigned to their respective gates. No F1 or deployment authorization.

## REC-03 — Approved DEV/PROD Git policy (2026-11-24)
Owner approved two active branches: dev for all development and integration, main for stable production releases. This supersedes the proposed feature/maintenance branches and the earlier main-only plan. dev maps to Docker project autotramita-dev; main maps to autotramita-prod. Mapping is a policy, not an active deployment connection. No automatic deployment or CI/CD deployment configuration is authorized. Future DEV automation is a separate decision; PROD release and deployment require explicit approval. No production data or secrets in DEV.
REC-03 preparation: create dev from updated main, then integrate f1/foundation into dev with a history-preserving merge after checking conflicts and automation. Preserve newer approved documentation, existing code, maintenance assets and historical records; retain original and archive branches. Review .gitleaksignore and disputed migration 0002 in later authorized work. Do not merge unfinished F1 into main. No new features, live changes or F1 acceptance. REC-04–07 remain unauthorized. Stop if external deployment triggers or loss of content cannot be ruled out. Prior REC-02 status is historical; this section supersedes its branch/merge restrictions only for the approved DEV consolidation preparation. Actual merge remains pending verification.
