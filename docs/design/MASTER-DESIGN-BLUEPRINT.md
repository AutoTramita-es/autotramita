# AutoTramita.es — MASTER DESIGN BLUEPRINT
Date: 2026-11-24 | v1.0 | Review draft, not implementation authorization.
Scope: AT-18 cross-cutting design, all 20 workstreams, all five portals and public web. Source: [Master Blueprint](../MASTER-BLUEPRINT.md), [ADR register](../adr/ADR-REGISTER.md), [design index](README.md). Review based on direct retrieval of 19 linked design documents, 9 ADRs, 75 indexed wireframes and 10 brand/pattern SVGs; source inspection, not browser rendering or exhaustive unindexed repository tree audit. Five planned document paths returned 404. No code, deployment, legal approval or production readiness claimed.

## 1. Status and precedence
Accepted ADRs and explicitly confirmed business decisions govern; domain specs and UX proposals cannot silently amend them. 27 AT-03 decisions confirmed; AT-04 D01–D25 proposed; AT-08 existing approved-in-principle rules and manual Tramisur initial operating model preserved. 11/11 SaaS UX phases documented, public web specification coverage documented, final visual approval pending. All five portals conceptually covered; Flutter implementation-specific UX not complete. No readiness percentage inferred from document counts.

## 2. Complete indexed design specification register (19 existing)
- [BRAND-IDENTITY.md](BRAND-IDENTITY.md) — logo variants, color tokens, typography, usage rules.
- [WEBSITE-STRUCTURE.md](WEBSITE-STRUCTURE.md) — homepage UX, public routes, Spanish copy and responsive rules.
- [SERVICE-PAGES.md](SERVICE-PAGES.md) — dynamic service details, pricing, documents and guest request UX.
- [B2B-PAGES.md](B2B-PAGES.md) — professional pages and verified onboarding.
- [PUBLIC-AUTH-SUPPORT-LEGAL.md](PUBLIC-AUTH-SUPPORT-LEGAL.md) — authentication, recovery, support and legal UX.
- [SAAS-APPLICATION-SHELL.md](SAAS-APPLICATION-SHELL.md) — shared workspace navigation, context, roles, themes and responsive UX.
- [DEALER-DASHBOARD.md](DEALER-DASHBOARD.md) — dealer dashboard metrics, tasks, credit and responsive UX.
- [CASE-MANAGEMENT.md](CASE-MANAGEMENT.md) — case list, board, creation, detail, deadlines and assignments.
- [DEALER-CRM-VEHICLES.md](DEALER-CRM-VEHICLES.md) — customer and vehicle registry UX, representation and ownership evidence.
- [DOCUMENTS-DIGITAL-SIGNATURES.md](DOCUMENTS-DIGITAL-SIGNATURES.md) — document register, capture, OCR, review, templates, mandates, signatures and CSV verification.
- [FINANCE-CREDIT-MANAGEMENT.md](FINANCE-CREDIT-MANAGEMENT.md) — tariffs, quotes, discounts, credit, invoices, payments, refunds and reports.
- [ORGANIZATION-EMPLOYEE-MANAGEMENT.md](ORGANIZATION-EMPLOYEE-MANAGEMENT.md) — organization, branches, staff, permissions, security and audit; all 27 AT-03 decisions.
- [CUSTOMER-PORTAL.md](CUSTOMER-PORTAL.md) — mobile-first customer portal, secure claims, documents, signatures, payments and communication.
- [GESTOR-PORTAL.md](GESTOR-PORTAL.md) — future professional workspace; preserves approved Phase 1 manual Tramisur handoff.
- [ENGINEER-PORTAL.md](ENGINEER-PORTAL.md) — integrated Ficha Reducida procurement and professional technical workspace.
- [CENTRAL-ADMIN-PORTAL.md](CENTRAL-ADMIN-PORTAL.md) — central administration and backoffice across all 20 modules.
- [ICON-SYSTEM.md](ICON-SYSTEM.md) — 50 core Lucide icons and accessibility rules.
- [BACKGROUND-PATTERNS.md](BACKGROUND-PATTERNS.md) — three editable SVG patterns.
- [HERO-BANNERS.md](HERO-BANNERS.md) — hero concepts and integration requirements.
All above are review drafts except explicitly approved visual direction and inherited accepted decisions. Public routes and UI labels proposed, not API contracts. Public web: home, dynamic service detail, B2B hub and three audiences, authentication, guest claim, recovery, support and legal outlines. Portal namespaces: /empresa, /cliente, /gestoria, /ingenieria, /administracion. Professional portals future gated, not required for phase 1.

## 3. Accepted ADR register (9/9)
| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](../adr/ADR-001-technology-stack.md) | Technology stack and modular monolith | Accepted | 2026-11-23 |
| [ADR-002](../adr/ADR-002-multi-tenancy-rls.md) | Shared PostgreSQL database with tenant isolation and RLS | Accepted | 2026-11-23 |
| [ADR-003](../adr/ADR-003-identity-customer-membership.md) | Global user identity, tenant-local customers and memberships | Accepted | 2026-11-23 |
| [ADR-004](../adr/ADR-004-api-contracts.md) | API-first contracts and client generation | Accepted | 2026-11-23 |
| [ADR-005](../adr/ADR-005-document-storage.md) | Document storage and tenant isolation | Accepted | 2026-11-23 |
| [ADR-006](../adr/ADR-006-service-catalog-case-workflows.md) | Configurable service catalog and case workflows | Accepted | 2026-11-23 |
| [ADR-007](../adr/ADR-007-pricing-credit-payments.md) | Unified pricing, dealership credit and central payment collection | Accepted | 2026-11-23 |
| [ADR-008](../adr/ADR-008-delivery-governance.md) | Architecture-first, module-by-module delivery with Claude Code | Accepted | 2026-11-23 |
| [ADR-009](../adr/ADR-009-tenant-organization-membership-verification.md) | Tenant organization, memberships and verification | Accepted | 2026-11-23 |
ADR-001 stack unchanged; 002 forced RLS and scoped admin; 003 global identity/tenant-local CRM/secure claim; 004 generated OpenAPI clients; 005 private storage; 006 versioned services/qualified partners; 007 unified pricing/credit; 008 approval gate; 009 legal entity/branches/manual approval. Open clauses remain open.

## 4. Module traceability and remaining gates
| Module | Design coverage | Remaining domain gate |
|---|---|---|
| AT-01 | Shell/admin health | hosting, environments, CI, backup/restore, observability, API conventions |
| AT-02 | Auth/shell/security | OIDC, session/recovery, MFA central/professional, rate limits |
| AT-03 | Organization/admin/B2B | reconcile 27 confirmed decisions with older drafts, permission IDs, constraints, tests |
| AT-04 | CRM/customer | approve D01–25, public intake tenant, merge, claim, representation |
| AT-05 | CRM/engineer | VIN legacy, ownership evidence, snapshots, plate history, schema |
| AT-06 | Public services/admin catalog | actual service list, eligibility, versioned requirements, legal source |
| AT-07 | Case management/all portals | canonical transitions, task/assignment state, reopen/cancel, handoff |
| AT-08 | Cases/gestor/admin | consolidate approved deadlines, authority/calendar evidence, test vectors |
| AT-09 | Documents/customer/professionals | storage/scanning/limits, entitlement, signatures, templates, retention |
| AT-10 | Gestor/admin | manual phase 1 contract and scope; future portal approval |
| AT-11 | Engineer/admin | qualification, procurement, technical templates, QA, honoraria |
| AT-12 | Finance/public services | discount base/caps, commission, tax presentation, tariff approval |
| AT-13 | Finance/admin | ledger, reservations, calendar, SEPA grace, dunning |
| AT-14 | Finance/customer | PSP, merchant-of-record, funds flow, invoices, settlement/refund |
| AT-15 | Admin/gestor/engineer | verified official access, permissions, adapters, uncertain outcomes |
| AT-16 | Shell/all portals | event catalog, recipients, delivery, privacy, preferences |
| AT-17 | Central admin | central permission matrix, separation of duties, approval thresholds |
| AT-18 | 11 SaaS phases + public | shared design system, components, responsive/Flutter, assets, review |
| AT-19 | Dashboards/reports | metric dictionary, denominators, aging, event basis, access |
| AT-20 | All portals | GDPR roles/bases, retention/holds, contracts, legal/tax review, incidents |

## 5. Verified visual inventory (85 SVG)
75 wireframes directly fetched and checked for SVG source; 64 desktop and 11 customer mobile (390x844). Desktop viewBoxes vary 1000-wide public, 1440x900 dealer, 1200x760 professional/admin. These are editable conceptual wireframes, many schematic placeholders, not final screenshots or responsive proof.
- [Homepage desktop wireframe](assets/wireframes/homepage-desktop.svg) — editable layout concept; raster placeholders pending.
- [Service detail wireframe](assets/wireframes/service-detail-desktop.svg) — editable layout concept.
- [B2B wireframe](assets/wireframes/b2b-desktop.svg) — shared layout concept.
- [Authentication wireframe](assets/wireframes/auth-desktop.svg) — desktop layout concept.
- [Light shell](assets/wireframes/saas-shell-light.svg) / [Dark shell](assets/wireframes/saas-shell-dark.svg) — editable concepts.
- [Dealer dashboard wireframe](assets/wireframes/dealer-dashboard.svg) — fictional data concept.
- Case wireframes: [table](assets/wireframes/case-table.svg), [Kanban](assets/wireframes/case-kanban.svg), [detail](assets/wireframes/case-detail.svg), [wizard](assets/wireframes/case-wizard.svg).
- CRM wireframes: [customers](assets/wireframes/crm-customers.svg), [customer detail](assets/wireframes/crm-customer-detail.svg), [vehicles](assets/wireframes/crm-vehicles.svg), [vehicle detail](assets/wireframes/crm-vehicle-detail.svg).
- Document wireframes: [register](assets/wireframes/documents-register.svg), [viewer](assets/wireframes/documents-viewer.svg), [capture](assets/wireframes/documents-capture.svg), [signature](assets/wireframes/documents-signature.svg), [CSV](assets/wireframes/documents-csv.svg).
- Finance wireframes: [dashboard](assets/wireframes/finance-dashboard.svg), [quote](assets/wireframes/finance-quote.svg), [credit](assets/wireframes/finance-credit.svg), [invoices](assets/wireframes/finance-invoices.svg), [payments](assets/wireframes/finance-payments.svg), [reports](assets/wireframes/finance-reports.svg).
- Organization wireframes: [profile](assets/wireframes/org-profile.svg), [branches](assets/wireframes/org-branches.svg), [team](assets/wireframes/org-team.svg), [invite](assets/wireframes/org-invite.svg), [permissions](assets/wireframes/org-permissions.svg), [reassignment](assets/wireframes/org-reassignment.svg), [security](assets/wireframes/org-security.svg), [audit](assets/wireframes/org-audit.svg).
- Customer mobile wireframes: [dashboard](assets/wireframes/customer-dashboard.svg), [intake](assets/wireframes/customer-intake.svg), [claim](assets/wireframes/customer-claim.svg), [case](assets/wireframes/customer-case.svg), [vehicles](assets/wireframes/customer-vehicles.svg), [documents](assets/wireframes/customer-documents.svg), [quote](assets/wireframes/customer-quote.svg), [signature](assets/wireframes/customer-signature.svg), [payments](assets/wireframes/customer-payments.svg), [messages](assets/wireframes/customer-messages.svg), [profile](assets/wireframes/customer-profile.svg).
- Gestor wireframes: [dashboard](assets/wireframes/gestor-dashboard.svg), [verification](assets/wireframes/gestor-verification.svg), [assignment](assets/wireframes/gestor-assignment.svg), [case](assets/wireframes/gestor-case.svg), [filing](assets/wireframes/gestor-filing.svg), [receipt](assets/wireframes/gestor-receipt.svg), [fees](assets/wireframes/gestor-fees.svg), [audit](assets/wireframes/gestor-audit.svg).
- Engineer wireframes: [dashboard](assets/wireframes/engineer-dashboard.svg), [verification](assets/wireframes/engineer-verification.svg), [assignment](assets/wireframes/engineer-assignment.svg), [vehicle](assets/wireframes/engineer-vehicle.svg), [homologation](assets/wireframes/engineer-homologation.svg), [editor](assets/wireframes/engineer-editor.svg), [signature](assets/wireframes/engineer-signature.svg), [quality](assets/wireframes/engineer-quality.svg), [fees](assets/wireframes/engineer-fees.svg), [audit](assets/wireframes/engineer-audit.svg).
- Admin wireframes: [dashboard](assets/wireframes/admin-dashboard.svg), [tenants](assets/wireframes/admin-tenants.svg), [operations](assets/wireframes/admin-operations.svg), [staff](assets/wireframes/admin-staff.svg), [partners](assets/wireframes/admin-partners.svg), [catalog](assets/wireframes/admin-catalog.svg), [credit](assets/wireframes/admin-credit.svg), [finance](assets/wireframes/admin-finance.svg), [quality](assets/wireframes/admin-quality.svg), [reports](assets/wireframes/admin-reports.svg), [integrations](assets/wireframes/admin-integrations.svg), [audit](assets/wireframes/admin-audit.svg).
Brand (7): [logo-horizontal](assets/brand/logo-horizontal.svg), [logo-stacked](assets/brand/logo-stacked.svg), [logo-dark](assets/brand/logo-dark.svg), [logo-monochrome](assets/brand/logo-monochrome.svg), [brand-mark](assets/brand/brand-mark.svg), [favicon](assets/brand/favicon.svg), [app-icon-master](assets/brand/app-icon-master.svg).
Patterns (3): [light-digital](assets/patterns/light-digital.svg), [corporate-navy](assets/patterns/corporate-navy.svg), [automotive-flow](assets/patterns/automotive-flow.svg).
Icon system: 50 Lucide concepts, not 50 separately verified SVG files. Hero 5, service illustrations 12, business photos 6, process illustrations 5 = 28 concept raster targets; generated in conversation per project history, repository upload not verified. Do not mark delivered. Pending PNG logo exports, ICO, Apple touch, PWA 192/512/maskable, social 5, OG 5, product screenshots 5 after implementation. Require source/rights, dimensions, alt, optimized WebP/AVIF, mobile crops, safe areas, approval and manifest. No official logos or misleading product screenshots.

## 6. Findings and conflict register
| ID | Severity | Finding | Proposed resolution / owner |
|---|---|---|---|
| R01 | Blocker | Five planned docs absent (404): DESIGN-SYSTEM, UI-COMPONENTS, IMAGE-ASSETS, RESPONSIVE-DESIGN, DESIGN-ROADMAP | AT-18 create and approve before shared UI implementation |
| R02 | High | Brand midnight #0B1220 vs shell canvas #0B1728; brand vs semantic token distinction undocumented | preserve both as named brand/semantic tokens, approve mapping, contrast tests |
| R03 | High | Older AT-03 membership/ADR wording lacks manager delegated invitations D11; D12 responsibility routing vs no automatic assignee mutation; D22 closure alternatives; D23 transfers; D13 owner transfer | reconcile explicit approved D11–13/22–23, distinguish queue responsibility from assignee, preserve last-owner invariant and multiple owners; explicit ADR amendment if necessary, not silent |
| R04 | High | Public guest intake requires non-null tenant_id but public intake tenant/branch routing unresolved | AT-04/07 approve intake ownership and entitlement, no null tenant or global CRM bypass |
| R05 | High | Canonical case enums vs UI Kanban groups and partner/technical states not mapped | AT-07 versioned state/transition matrix; orthogonal blockers, no filing via drag |
| R06 | High | Future partner portals vs approved manual Tramisur phase | feature gate future portals, manual handoff evidence and central status authority remain |
| R07 | High | Central/partner mandatory MFA proposed, dealer optional D18 confirmed; global identity may hold multiple roles | AT-02 define workspace/action-specific assurance without imposing dealer-wide mandatory MFA |
| R08 | High | Case-entitled docs ADR-005 vs standalone CRM/vehicle/verification evidence | AT-09 explicit resource grants and separate verification scope; no broad access |
| R09 | High | Payment/credit ledger and invoice allocation unresolved; UI examples not accounting truth | AT-12/13/14/20 approve funds flow, PSP, tax, ledger and confirmed settlement; separate headroom vs usable, no double count |
| R10 | Medium | Finance aging proposed 1–30/31–60/61–90/90+ vs admin illustrative 1–15/16–30/31–60/60+ | AT-19 one approved aging dictionary, calendar aging distinct from business-day grace |
| R11 | High | Central role matrix and dual approval only proposed; demo role switching not security | AT-17 explicit permissions and actor separation, server enforcement, audit |
| R12 | Medium | Route naming accents/plurals and finance nested vs sidebar routes not consolidated | AT-18 canonical route registry, redirects and deep-link entitlement |
| R13 | High | Customer mobile wireframes only; Flutter navigation, secure capture/offline, permissions, platform lifecycle not fully specified | responsive/native parity matrix and threat model; no sensitive offline cache by default |
| R14 | Medium | SVG dimensions and layout fidelity inconsistent; many placeholder cards, editable text font fallback | browser render review, shared geometry, final high fidelity critical journeys, outline final wordmark |
| R15 | High | Legal copy outlines, professional authority, official API access and CSV issuer verification not approved | AT-15/20 verify official sources and legal review before launch |
| R16 | Medium | Metrics reopened cases, denominators, revenue vs collections and aggregation unresolved | AT-19 canonical metric contracts and test fixtures |
| R17 | Medium | README next gate still brand/hero and public next workstream SaaS despite 11 completed specs; master AT-18 status stale | link this review, distinguish coverage from approval, update index status only |
| R18 | Medium | Raster concepts and interactive chat prototypes not durable repository assets | export approved raster and durable design interaction specs; no claim of executable prototype stored |
| R19 | High | Accessibility targets stated but no component state/contrast/keyboard/native test evidence | AT-18 WCAG 2.2 AA target, focus, errors, reduced motion, 320px/200% zoom, screen reader validation |
| R20 | High | API error/pagination, idempotency and authorization contracts not finalized | AT-01/02/04 shared contract then per-module OpenAPI and negative tests |
No confirmed architecture reversal required by this review. R03 is an explicit reconciliation issue, R02/R10/R12 are design inconsistencies, others gaps or scope gates. Do not promote proposed resolutions to accepted decisions.

## 7. Shared design baseline (candidate)
Inter, Lucide, Spanish-first, EUR es-ES; brand navy #082344 blue #005BCB ice #EFF5FC success #16A34A. Light canvas #F5F7FA surface #FFFFFF text #082344 secondary #475569 border #CBD5E1. Dark canvas #0B1728 surface #12243A text #F1F5F9 secondary #B8C7DA border #40536B selected #203C60 link #60A5FA; brand midnight distinct pending approval. Desktop 256/72 sidebar, 64 topbar, 24 padding, 12 columns; tablet 768–1279 rail/overlay, mobile <768 drawer 56 topbar 16 padding, 48 action targets. Public max width 1280, header 72, H1 48/32. Claro/Oscuro/Sistema. Shared semantic status text+icon, no color-only signals. Next.js/TypeScript and Flutter remain ADR-001; Tailwind/shadcn/Motion proposed, versions pending. Component contracts must cover loading, empty, true zero, error, stale, offline, denied, revoked, validation, focus, confirmation and concurrency.

## 8. Delivery sequence and review gates
G0 (next): approve master review and create DESIGN-SYSTEM.md; semantic tokens, themes, contrast, spacing, typography, geometry, icons, brand approval. G1 UI-COMPONENTS.md with reusable forms/tables/dialogs/filters/wizards/status/file/finance states and accessibility. G2 RESPONSIVE-DESIGN.md including Flutter parity, capture, deep links, secure storage, lifecycle and mobile testing. G3 IMAGE-ASSETS.md inventory/rights/export and final browser-render review; upload approved raster assets. G4 DESIGN-ROADMAP.md dependency gates and route/status/metric registries; reconcile R03/R04/R05/R07/R08/R09/R11/R20. G5 approve bounded AT-01/02/03 foundation specifications, data models, OpenAPI, RLS tests and acceptance criteria; resolve relevant ADR open clauses. G6 prepare Claude Code execution order per bounded module, explicit product-owner authorization, PR/test review. Then AT-04/05 -> AT-06/07/08/09 -> manual partner workflow and approved financial slices -> future integrations/portals/analytics. AT-20 applies throughout. No need to finish every future feature before approved foundation slice, but no module starts with unresolved relevant blockers.
Each implementation packet requires scope/non-goals, approved sources, data model/constraints, permission matrix, state transitions, API contract, test vectors including cross-tenant negative tests, migration/rollback plan, acceptance and explicit approval. No deployment authorization.

## 9. Review limitations and maintenance
Inventory covers indexed files, not proof of no other unindexed files. SVG source checked, not rendered pixel QA. Legal and payment compliance not verified by this documentation review. No raster binary or production screenshots verified. Update status after explicit approval; retain ADR history. This file is the consolidated design index and proposed review roadmap, not replacement for domain specs.

## 10. G0 follow-up — 2026-11-24
[DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) created for review. Historical audit counts above remain baseline: now 20 design specifications excluding this master/index, four of five originally missing documents remain. R02 proposed semantic/brand separation documented; R19 standards defined, runtime evidence outstanding. G0 approval pending; next G1 UI-COMPONENTS.md. No ADR or implementation changes.

## 11. G1 follow-up — 2026-11-24
[UI-COMPONENTS.md](UI-COMPONENTS.md) created: 82 component contracts, 40 acceptance criteria, portal composition, Next.js/Flutter mapping. Historical audit baseline unchanged; now 21 design specifications excluding master/index, three originally missing documents remain. G0/G1 approval pending; R19 runtime evidence pending. Next G2 RESPONSIVE-DESIGN.md. No ADR or implementation changes.

## 12. G2 follow-up — 2026-11-24
[RESPONSIVE-DESIGN.md](RESPONSIVE-DESIGN.md) created with 80 acceptance criteria. R13 design proposal addressed; runtime/security evidence and R19 remain pending. Historical audit baseline unchanged; 22 design specifications excluding master/index, two originally missing documents remain. G0–G2 owner approval pending. Next G3 IMAGE-ASSETS.md. No ADR changes or implementation.

## 13. G3 follow-up — 2026-11-24
[IMAGE-ASSETS.md](IMAGE-ASSETS.md) created: 85 indexed SVGs, 18 source rechecks, 28 raster briefs, 40 acceptance criteria. Raster originals, exports, rights and rendered QA pending; R18/R19 remain open. 23 design specifications excluding master/index; DESIGN-ROADMAP.md remains missing from original five. Next G4; G3 asset release gate remains open. No ADR changes or implementation.

## 14. G4 follow-up — 2026-11-24
[DESIGN-ROADMAP.md](DESIGN-ROADMAP.md) created: all20 modules,9 ADRs,23 input designs,14 phase labels F0–F13 (F3 split), R01–R20,40 acceptance criteria. All five originally missing design documents now drafted; 24 design specifications excluding master/index. Approval, asset recovery, domain blockers and runtime evidence remain open. Next G5 bounded foundation technical review, then G6 execution order. No ADR or implementation changes.

## 15. Raster import — 2026-11-24
70 source PNGs from the owner Design Package (plus 10 additions, 2026-11-24, see IMAGE-ASSETS.md §11.1–11.2) imported byte-identical into [assets/](assets/) (SHA-256 verified against [assets/MANIFEST.csv](assets/MANIFEST.csv), stored via Git LFS; browsable [catalog](assets/catalog/VISUAL-CATALOG.html)): brand/raster 1, hero 8, services 15, business 7, process 7, mockups 32 (public-website 3, dealer-portal 11, customer-portal 1, mobile 1, archive 16 reference only — note 99-Archive and the visual-direction mockups are not part of the 28 raster briefs). Exact per-folder counts are in the manifest. Owner accepted the set as visual direction (see IMAGE-ASSETS.md §11, proposed R-ID mapping, R2-06/08/11 added from the additional R2 images). Files are candidates: rights, content review, alt text, optimized exports and approval remain open (R18/R19). 28-brief to file mapping is a proposal only. No design approval or implementation implied.

## 16. G0 approval — 2026-11-24
Owner approved the design-system token/theme specification ([DESIGN-SYSTEM.md](DESIGN-SYSTEM.md), review in [DESIGN-SYSTEM-G0-REVIEW.md](DESIGN-SYSTEM-G0-REVIEW.md)) with two contrast fixes. G0 approved for tokens/themes only; G1–G3 approvals, rendered accessibility evidence and release of assets remain open. Next: G1 review (UI-COMPONENTS.md). No ADR changes or implementation.
