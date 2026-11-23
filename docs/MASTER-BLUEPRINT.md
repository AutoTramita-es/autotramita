# AutoTramita.es — MASTER BLUEPRINT

**Status:** MASTER INDEX / WORKING BLUEPRINT (not implementation authorization)  
**Version:** 1.0  
**Date:** 2026-11-23  
**Repository:** [AutoTramita-es/autotramita](https://github.com/AutoTramita-es/autotramita)  
**Language:** Croatian for planning; existing technical ADRs remain authoritative.

## 1. Purpose and scope

AutoTramita.es is a Spanish multi-tenant SaaS platform for vehicle-related administrative procedures, connecting dealerships (including autónomos), end customers, AutoTramita operators and authorized external professional partners. This blueprint is the central navigation index for 20 workstreams; it is **not** a claim that those features are implemented or approved in detail.

The existing ADRs and specifications take precedence over high-level summaries here. A status such as “ADR accepted” applies to the referenced core decision, **not** to every feature or outstanding detail in the module. Unresolved decisions must remain open until explicitly approved.

## 2. Accepted architectural foundation

- **ADR-001:** Python/FastAPI modular monolith, Pydantic v2, PostgreSQL, SQLAlchemy 2.x, Alembic, psycopg 3, Redis/Celery, private S3-compatible storage, Next.js/TypeScript, Flutter, Docker Compose.
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
| **AT-01** | Temelj sustava i infrastruktura | FastAPI, PostgreSQL, Redis, Celery, Docker, CI/CD, razvojna i produkcijska okruženja. | [ADR-001](adr/ADR-001-technology-stack.md), [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-004](adr/ADR-004-api-contracts.md), [ADR-008](adr/ADR-008-delivery-governance.md) | ADR prihvaćen; implementacija nije započela |
| **AT-02** | Korisnički računi i sigurnost | Prijava, registracija, OIDC, e-mail verifikacija, sesije, MFA, uloge. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Djelomično definirano |
| **AT-03** | Autokuće, poslovnice i zaposlenici | Tenant, NIF, pravni oblici, provjera autokuća, poslovnice, pozivnice i pristupi. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-007](adr/ADR-007-pricing-credit-payments.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Detaljno razrađeno; bez implementacije |
| **AT-04** | Klijenti i vlasnici vozila | Fizičke i pravne osobe, anonimni zahtjevi, korisnički profili, zastupanje, povezivanje predmeta. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | ADR prihvaćen; detalji otvoreni |
| **AT-05** | Registar vozila | VIN, registracije, tehničke karakteristike, vlasništvo i povijest. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za razradu |
| **AT-06** | Katalog administrativnih usluga | Registracija, prijenos vlasništva, uvoz, tehnička dokumentacija i drugi postupci. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Osnovna arhitektura prihvaćena |
| **AT-07** | Predmeti i radni procesi | Otvaranje, statusi, zadaci, dodjele, kontrolne liste, završetak i arhiva. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Osnovna arhitektura; detalji otvoreni |
| **AT-08** | Rokovi, prioriteti i nadzor predmeta | Zakonski i interni rokovi, službeni kalendari, nadležnosti, revizije i eskalacije. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Opsežna specifikacija; bez implementacije |
| **AT-09** | Dokumenti i digitalna obrada | Upload, PDF, OCR, klasifikacija, validacija, potpisi, predlošci, S3 i audit. | [ADR-005](adr/ADR-005-document-storage.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | ADR prihvaćen; detalji otvoreni |
| **AT-10** | Gestorías i profesionalni partneri | Ovlašteni gestor administrativo, partneri i delegiranje reguliranih radnji. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za razradu |
| **AT-11** | Vanjski inženjeri i Ficha Reducida | AutoTramita naručuje Ficha Reducida od kvalificiranog vanjskog inženjera u pozadini. | [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Poslovni princip prihvaćen; tijek za razradu |
| **AT-12** | Cjenik, ponude i popusti | Jedinstveni javni maloprodajni cjenik, popusti autokuća, marže, zasebne pristojbe. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; detalji otvoreni |
| **AT-13** | Kreditni limiti autokuća | Centralno odobreni limiti, rezervacije, dospijeća, blokade i reaktivacija. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; detalji otvoreni |
| **AT-14** | Plaćanja, fakture i naplata | Kartice, SEPA, računi, IVA, odgođena naplata, povrati i usklađivanje. | [ADR-007](adr/ADR-007-pricing-credit-payments.md) | ADR prihvaćen; pružatelj i tok novca otvoreni |
| **AT-15** | Integracije sa španjolskim institucijama | DGT, AEAT, ITV, registri, službeni obrasci, identifikacija i statusi. | [ADR-004](adr/ADR-004-api-contracts.md), [ADR-006](adr/ADR-006-service-catalog-case-workflows.md) | Za pravnu i tehničku provjeru |
| **AT-16** | Obavijesti i komunikacija | E-mail, in-app, dopune, predlošci i praćenje isporuke. | [ADR-003](adr/ADR-003-identity-customer-membership.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Djelomično definirano |
| **AT-17** | Centralna administracija AutoTramite | Odobravanje autokuća, nadzor, partneri, cjenici, financije, sporovi. | [ADR-007](adr/ADR-007-pricing-credit-payments.md), [ADR-009](adr/ADR-009-tenant-organization-membership-verification.md) | Za razradu |
| **AT-18** | Portali i mobilne aplikacije | Javni web, klijentski portal, autokuće, backoffice i Flutter Android/iOS. | [ADR-001](adr/ADR-001-technology-stack.md), [ADR-004](adr/ADR-004-api-contracts.md) | Tehnologija odabrana; UX za razradu |
| **AT-19** | Izvještaji i poslovna analitika | Naplata, marže, broj predmeta, trajanje obrade, poslovnice, produktivnost. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-007](adr/ADR-007-pricing-credit-payments.md) | Za razradu |
| **AT-20** | Pravna usklađenost i operacije | GDPR, ovlasti, audit, backup, monitoring, incidenti i ugovori. | [ADR-002](adr/ADR-002-multi-tenancy-rls.md), [ADR-005](adr/ADR-005-document-storage.md), [ADR-008](adr/ADR-008-delivery-governance.md) | Djelomično definirano |

## 4. Existing source documentation

- [ADR register](adr/ADR-REGISTER.md) — ADR-001 through ADR-009; all listed Accepted as of 2026-11-23.
- [TenantBranch specification](specifications/tenant-branch.md) — approved business rules, no implementation.
- [TenantMembership and workspace specification](specifications/tenant-membership.md) — draft containing confirmed decisions; no implementation.
- [Case deadlines and priority specification](specifications/case-deadlines.md) — design approved in principle, no implementation.

The current repository includes placeholder folders `app/api`, `app/auth`, `app/billing`, `app/cases`, `app/core`, `app/credit`, `app/customers`, `app/documents`, `app/integrations`, `app/services`, `app/tenants`, `app/vehicles`, `migrations` and `tests`. These are **not implemented modules**. The AT-01–AT-20 workstreams are logical planning units, not a mandated one-folder-per-module code layout.

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

**First design focus: AT-03 — Autokuće, poslovnice i zaposlenici.** Existing ADR-009 and tenant specifications provide the most developed foundation. Finish remaining open questions, then prepare a bounded approved implementation task separately if desired.

Next modules should be selected according to dependencies, not forced into a rigid all-at-once roadmap. A useful early chain is AT-02/AT-03 → AT-04/AT-05 → AT-06/AT-07/AT-08/AT-09; financial and regulated integrations require their own approvals before production use.

## 7. Cross-cutting decisions to keep open

- Identity provider, precise permissions, account recovery, privacy retention and security controls.
- Full service catalog, exact per-service regulatory requirements, case state machines and partner integrations.
- Payment provider, merchant-of-record/funds flow, discounts/invoice allocation, holiday calendars and collection policies under ADR-007.
- Official DGT/AEAT/ITV integration availability, authority to perform regulated acts, and legal evidence sources.
- Hosting provider, deployment topology, monitoring, backup/recovery, test strategy and operational SLAs.

## 8. Blueprint maintenance

Update this file when a module is added, renamed, split, superseded or its verified status changes. Link to the approved decision/specification; do not replace them with an informal summary. Record substantive changes in Git commits. This document remains a **planning index**, not an executable specification or deployment plan.
