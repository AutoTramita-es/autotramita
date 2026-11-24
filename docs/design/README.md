# AutoTramita.es — Brand & Web Design System
Date: 2026-11-24
Status: visual direction approved by product owner; detailed specifications and assets pending review. No implementation or deployment authorized.

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
- DESIGN-SYSTEM.md — semantic tokens, spacing, elevation, themes and accessibility.
- [WEBSITE-STRUCTURE.md](WEBSITE-STRUCTURE.md) — homepage UX, public routes, Spanish copy and responsive rules.
- [Homepage desktop wireframe](assets/wireframes/homepage-desktop.svg) — editable layout concept; raster placeholders pending.
- [SERVICE-PAGES.md](SERVICE-PAGES.md) — dynamic service details, pricing, documents and guest request UX.
- [Service detail wireframe](assets/wireframes/service-detail-desktop.svg) — editable layout concept.
- [B2B-PAGES.md](B2B-PAGES.md) — professional pages and verified onboarding.
- [B2B wireframe](assets/wireframes/b2b-desktop.svg) — shared layout concept.
- UI-COMPONENTS.md — forms, tables, navigation, status, dialogs and states.
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

## Next gate
Review brand identity and primary hero first, then create individual production assets and detailed specifications. Link design index from master blueprint when updating it. No application code, dependencies, migrations or deployment in this step.
