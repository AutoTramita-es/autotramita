# AutoTramita.es — Brand & Web Design System
Date: 2026-11-24
Status: visual direction approved by product owner; detailed specifications and assets pending review. No implementation or deployment authorized.

## Consolidated review
[MASTER-DESIGN-BLUEPRINT.md](MASTER-DESIGN-BLUEPRINT.md) — 19 existing design specs, 85 verified indexed SVGs, gaps and approval gates.

## Scope
Cross-cutting design workstream under [AT-18](../MASTER-BLUEPRINT.md), not a new numbered module. Covers public website, customer portal, dealership workspace, central administration and mobile design consistency. Next.js/TypeScript web and Flutter mobile remain authoritative under [ADR-001](../adr/ADR-001-technology-stack.md).

## Approved direction
Professional Spanish automotive administration SaaS, not a car dealership website. Navy #082344, blue #005BCB, pale blue #EFF5FC, success #16A34A, white #FFFFFF. Inter (selected for brand review). Clean typography, generous spacing, responsive layouts, subtle animation, light/dark modes. Logo concept combines automotive silhouette and verified document; Spanish accent colors used sparingly. Editable vector concepts saved; final visual approval and raster exports pending.
Proposed frontend tools: Tailwind CSS, shadcn/ui, Lucide, Motion, next/image, next/font; exact versions and compatibility pending. Use WCAG 2.2 AA as design target; keyboard access, visible focus, reduced motion, non-color status indicators.

## Public homepage
Spanish-first navigation, hero with live HTML heading and CTA, service cards, professional/dealership section, process explanation, FAQ, contact and legal footer. Candidate copy: “Tus trámites de vehículos, online.” CTA “Iniciar trámite”. Avoid guarantees of completion time, official affiliation or fully online completion where physical steps are required. Service availability and prices must derive from approved catalog, not hardcoded marketing.

## Architecture constraints
ADR-002/003/009: server-authorized tenant and branch context; distinct customer and employee workspaces; role-aware UI is not authorization. ADR-004: generated TypeScript/Dart API clients. ADR-005: no real private documents or customer data in public assets, demos or shared caches. ADR-006: versioned catalog, anonymous submission and secure claim; regulated actions routed to authorized professionals, integrated Ficha Reducida. ADR-007: public unified prices, separately disclosed statutory fees, dealership-funded discounts and centrally managed credit; never present pending payments as settled. ADR-008: specifications and review precede implementation.

## Planned documents
- [BRAND-IDENTITY.md](BRAND-IDENTITY.md) — logo variants, color tokens, typography, usage rules.
- [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) — shared tokens, themes, typography, geometry, motion and accessibility; G0 drafted, approval pending.
- [WEBSITE-STRUCTURE.md](WEBSITE-STRUCTURE.md) — homepage UX, public routes, Spanish copy and responsive rules.
- [Homepage desktop wireframe](assets/wireframes/homepage-desktop.svg) — editable layout concept; raster placeholders pending.
- [SERVICE-PAGES.md](SERVICE-PAGES.md) — dynamic service details, pricing, documents and guest request UX.
- [Service detail wireframe](assets/wireframes/service-detail-desktop.svg) — editable layout concept.
- [B2B-PAGES.md](B2B-PAGES.md) — professional pages and verified onboarding.
- [B2B wireframe](assets/wireframes/b2b-desktop.svg) — shared layout concept.
- [PUBLIC-AUTH-SUPPORT-LEGAL.md](PUBLIC-AUTH-SUPPORT-LEGAL.md) — authentication, recovery, support and legal UX.
- [Authentication wireframe](assets/wireframes/auth-desktop.svg) — desktop layout concept.
- [SAAS-APPLICATION-SHELL.md](SAAS-APPLICATION-SHELL.md) — shared workspace navigation, context, roles, themes and responsive UX.
- [Light shell](assets/wireframes/saas-shell-light.svg) / [Dark shell](assets/wireframes/saas-shell-dark.svg) — editable concepts.
- [DEALER-DASHBOARD.md](DEALER-DASHBOARD.md) — dealer dashboard metrics, tasks, credit and responsive UX.
- [Dealer dashboard wireframe](assets/wireframes/dealer-dashboard.svg) — fictional data concept.
- [CASE-MANAGEMENT.md](CASE-MANAGEMENT.md) — case list, board, creation, detail, deadlines and assignments.
- Case wireframes: [table](assets/wireframes/case-table.svg), [Kanban](assets/wireframes/case-kanban.svg), [detail](assets/wireframes/case-detail.svg), [wizard](assets/wireframes/case-wizard.svg).
- [DEALER-CRM-VEHICLES.md](DEALER-CRM-VEHICLES.md) — customer and vehicle registry UX, representation and ownership evidence.
- CRM wireframes: [customers](assets/wireframes/crm-customers.svg), [customer detail](assets/wireframes/crm-customer-detail.svg), [vehicles](assets/wireframes/crm-vehicles.svg), [vehicle detail](assets/wireframes/crm-vehicle-detail.svg).
- [DOCUMENTS-DIGITAL-SIGNATURES.md](DOCUMENTS-DIGITAL-SIGNATURES.md) — document register, capture, OCR, review, templates, mandates, signatures and CSV verification.
- Document wireframes: [register](assets/wireframes/documents-register.svg), [viewer](assets/wireframes/documents-viewer.svg), [capture](assets/wireframes/documents-capture.svg), [signature](assets/wireframes/documents-signature.svg), [CSV](assets/wireframes/documents-csv.svg).
- [FINANCE-CREDIT-MANAGEMENT.md](FINANCE-CREDIT-MANAGEMENT.md) — tariffs, quotes, discounts, credit, invoices, payments, refunds and reports.
- Finance wireframes: [dashboard](assets/wireframes/finance-dashboard.svg), [quote](assets/wireframes/finance-quote.svg), [credit](assets/wireframes/finance-credit.svg), [invoices](assets/wireframes/finance-invoices.svg), [payments](assets/wireframes/finance-payments.svg), [reports](assets/wireframes/finance-reports.svg).
- [ORGANIZATION-EMPLOYEE-MANAGEMENT.md](ORGANIZATION-EMPLOYEE-MANAGEMENT.md) — organization, branches, staff, permissions, security and audit; all 27 AT-03 decisions.
- Organization wireframes: [profile](assets/wireframes/org-profile.svg), [branches](assets/wireframes/org-branches.svg), [team](assets/wireframes/org-team.svg), [invite](assets/wireframes/org-invite.svg), [permissions](assets/wireframes/org-permissions.svg), [reassignment](assets/wireframes/org-reassignment.svg), [security](assets/wireframes/org-security.svg), [audit](assets/wireframes/org-audit.svg).
- [CUSTOMER-PORTAL.md](CUSTOMER-PORTAL.md) — mobile-first customer portal, secure claims, documents, signatures, payments and communication.
- Customer mobile wireframes: [dashboard](assets/wireframes/customer-dashboard.svg), [intake](assets/wireframes/customer-intake.svg), [claim](assets/wireframes/customer-claim.svg), [case](assets/wireframes/customer-case.svg), [vehicles](assets/wireframes/customer-vehicles.svg), [documents](assets/wireframes/customer-documents.svg), [quote](assets/wireframes/customer-quote.svg), [signature](assets/wireframes/customer-signature.svg), [payments](assets/wireframes/customer-payments.svg), [messages](assets/wireframes/customer-messages.svg), [profile](assets/wireframes/customer-profile.svg).
- [GESTOR-PORTAL.md](GESTOR-PORTAL.md) — future professional workspace; preserves approved Phase 1 manual Tramisur handoff.
- Gestor wireframes: [dashboard](assets/wireframes/gestor-dashboard.svg), [verification](assets/wireframes/gestor-verification.svg), [assignment](assets/wireframes/gestor-assignment.svg), [case](assets/wireframes/gestor-case.svg), [filing](assets/wireframes/gestor-filing.svg), [receipt](assets/wireframes/gestor-receipt.svg), [fees](assets/wireframes/gestor-fees.svg), [audit](assets/wireframes/gestor-audit.svg).
- [ENGINEER-PORTAL.md](ENGINEER-PORTAL.md) — integrated Ficha Reducida procurement and professional technical workspace.
- Engineer wireframes: [dashboard](assets/wireframes/engineer-dashboard.svg), [verification](assets/wireframes/engineer-verification.svg), [assignment](assets/wireframes/engineer-assignment.svg), [vehicle](assets/wireframes/engineer-vehicle.svg), [homologation](assets/wireframes/engineer-homologation.svg), [editor](assets/wireframes/engineer-editor.svg), [signature](assets/wireframes/engineer-signature.svg), [quality](assets/wireframes/engineer-quality.svg), [fees](assets/wireframes/engineer-fees.svg), [audit](assets/wireframes/engineer-audit.svg).
- [CENTRAL-ADMIN-PORTAL.md](CENTRAL-ADMIN-PORTAL.md) — central administration and backoffice across all 20 modules.
- Admin wireframes: [dashboard](assets/wireframes/admin-dashboard.svg), [tenants](assets/wireframes/admin-tenants.svg), [operations](assets/wireframes/admin-operations.svg), [staff](assets/wireframes/admin-staff.svg), [partners](assets/wireframes/admin-partners.svg), [catalog](assets/wireframes/admin-catalog.svg), [credit](assets/wireframes/admin-credit.svg), [finance](assets/wireframes/admin-finance.svg), [quality](assets/wireframes/admin-quality.svg), [reports](assets/wireframes/admin-reports.svg), [integrations](assets/wireframes/admin-integrations.svg), [audit](assets/wireframes/admin-audit.svg).
- SaaS design phases 09.1–09.11: specification coverage complete for review; domain approvals and implementation remain pending.
- [UI-COMPONENTS.md](UI-COMPONENTS.md) — 82 shared component contracts and 40 acceptance criteria; G1 drafted, approval pending.
- IMAGE-ASSETS.md — asset inventory, briefs, formats, naming and rights.
- RESPONSIVE-DESIGN.md — mobile/tablet/desktop and Flutter parity.
- DESIGN-ROADMAP.md — review gates and acceptance criteria.

- [ICON-SYSTEM.md](ICON-SYSTEM.md) — 50 core Lucide icons and accessibility rules.
- [BACKGROUND-PATTERNS.md](BACKGROUND-PATTERNS.md) — three editable SVG patterns.
- [HERO-BANNERS.md](HERO-BANNERS.md) — hero concepts and integration requirements.

## Asset production plan
5 logo variants (SVG/PNG); 5 hero banners (AVIF/WebP); 12 service illustrations; 6 business photographs; 5 process illustrations; 30–50 SVG icons (prefer Lucide); 5 product screenshots after implementation; 3 background patterns; favicon SVG/ICO; 3 PWA PNG icons including maskable variant; 5 social and 5 Open Graph PNG images. Counts are planning targets, not completed assets. Generated concept images are not yet production assets.
First asset: homepage hero, target 2560×1440, text-free and logo-free, light background with left-side negative space, car and digital administration visual on right. Generate mobile crop separately if necessary. No official agency marks or misleading real interface claims.
Proposed public/images/{brand,hero,services,business,process,product,patterns,social}/ relative to the eventual Next.js app root; actual app path must follow repository architecture. Keep originals separate from optimized derivatives; use descriptive filenames, alt text, explicit dimensions and responsive sizes. Never embed headings or buttons in raster artwork.

## Public web status
Design specification coverage complete for review; legal approval, raster upload, identity details and final visual approval pending. All 11 SaaS UX phases now documented for review.

## Next gate
G0 and G1 drafted for approval; next G2 responsive/Flutter, then asset manifest and roadmap; resolve relevant domain gates before implementation. Link design index from master blueprint when updating it. No application code, dependencies, migrations or deployment in this step.
