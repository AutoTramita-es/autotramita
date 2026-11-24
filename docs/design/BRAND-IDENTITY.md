# AutoTramita.es — Brand Identity v1.0
Date: 2026-11-24
Status: approved visual direction; vector concepts and detailed standards submitted for product-owner review. No implementation authorization.
Parent: [Design index](README.md); AT-18; ADR-001 and ADR-008.

## Identity
Canonical name AutoTramita.es (case-sensitive in marketing). Spanish-first copy. Descriptor: Gestiones de vehículos online. Voice: professional, clear, approachable; use tú consistently on public pages, concise operational labels in workspaces. No official government affiliation, guaranteed processing times or claims that physical inspections can be completed online. Candidate hero: Tus trámites de vehículos, online. CTA: Iniciar trámite.

## Logo
Original generated concept: automotive roof silhouette plus document and verification check. The SVGs below are simplified editable vector interpretations, not exact traces of the generated raster. Transparent backgrounds except app icon and favicon. Use horizontal in navigation, stacked in square layouts, dark variant on navy, monochrome for single-color contexts, mark for compact navigation. Do not stretch, rotate, add shadows or change proportions. Clear space at least one quarter of symbol height; minimum horizontal width 180 CSS px, stacked 140 px, mark 32 px; favicon separate. Keep tagline as live text when needed.
- [Horizontal](assets/brand/logo-horizontal.svg)
- [Stacked](assets/brand/logo-stacked.svg)
- [Dark background](assets/brand/logo-dark.svg)
- [Monochrome](assets/brand/logo-monochrome.svg)
- [Symbol](assets/brand/brand-mark.svg)
- [Favicon](assets/brand/favicon.svg)
- [App icon master](assets/brand/app-icon-master.svg)

SVG wordmarks currently use editable Inter text with Arial fallback; outline glyphs after visual approval to guarantee consistent rendering. Check spacing and legibility at target sizes. Export transparent PNG at 1x/2x/3x after approval. App master: export 192 and 512 PNG plus separate 512 maskable PNG with essential artwork inside central 80% diameter safe circle; verify actual Android/iOS masks. ICO 16/32/48 and Apple touch icon 180 PNG pending. No raster exports claimed complete.

## Palette
| Token | Hex | Purpose |
|---|---|---|
| brand-navy | #082344 | Primary brand, headings |
| brand-blue | #005BCB | Primary action, links |
| ice | #EFF5FC | Light tinted background |
| white | #FFFFFF | Light surface |
| success | #16A34A | Success accent |
| slate | #475569 | Secondary text |
| error | #DC2626 | Error accent |
| warning | #D97706 | Warning accent |
| midnight | #0B1220 | Dark background |
| dark-accent | #60A5FA | Dark theme links |
| dark-surface | #152238 | Dark cards |
| dark-text | #F1F5F9 | Dark foreground |

White on brand-blue and navy on white are primary combinations. For normal status text on white use success #166534, warning #92400E, error #B91C1C; do not assume accent colors pass contrast. Dark status text use light tints #86EFAC/#FCD34D/#FCA5A5. Verify WCAG 2.2 AA 4.5:1 normal text, 3:1 large text and relevant non-text controls; always combine color with labels/icons. Spanish red/yellow accents optional and decorative only; no official seals.

## Typography
Inter variable, weights 400/500/600/700; system sans fallback. Self-host via next/font or approved local font files with license notice; Flutter uses same family when licensed. Body 16/24, small 14/20, caption 12/16, H1 desktop 48/56 mobile 32/40, H2 32/40 mobile 26/34, H3 24/32. Use tabular numerals for finance and tables. Spanish locale es-ES for dates, EUR and numbers; retain VIN and identifiers without localization. Avoid all caps except short labels.

## Iconography and imagery
Lucide outline, 24px grid, consistent 2px strokes; icon-only controls have accessible names. Photography: contemporary Spanish dealerships, cars, professional staff and realistic documents without personal data. Illustrations: clean blue/white, minimal clutter, no embedded copy or agency logos. No fake testimonials or misleading product screenshots.

## Review checklist
Approve vector geometry and typography, inspect mobile header and dark mode, check contrast and keyboard focus, verify favicon at 16/32 px, export raster variants, document asset provenance and trademark clearance before public launch. Use design assets under docs/design/assets/brand as review sources; copy approved optimized assets to actual Next.js public directory only during authorized implementation. No production code or deployment in this phase.
