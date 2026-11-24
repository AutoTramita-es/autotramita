# AutoTramita.es — Shared Design System
2026-11-24 | v1.0 | Proposed for product-owner approval | AT-18 G0
Sources: [Master Design Blueprint](MASTER-DESIGN-BLUEPRINT.md), [Brand](BRAND-IDENTITY.md), [Shell](SAAS-APPLICATION-SHELL.md), [Icons](ICON-SYSTEM.md), [ADR-001](../adr/ADR-001-technology-stack.md), [ADR-008](../adr/ADR-008-delivery-governance.md). Applies to public web and five portals, Next.js and Flutter. No implementation, dependencies or deployment. Domain rules and accepted ADRs prevail.

## 1. Token architecture and governance
Three layers: primitive (literal values), semantic (purpose and theme), component (references to semantic tokens plus geometry). Stable dot-separated names, e.g. color.brand.blue, color.surface.canvas, color.action.primary.bg, component.button.primary.bg. No portal-specific palette or hardcoded component hex. Future versioned machine-readable token source and generated CSS custom properties/Tailwind mapping and Dart ThemeData/ThemeExtension; not created now. Web CSS px/rem (base 16, respect user settings); Flutter logical dp/sp, respect TextScaler, no fixed device-pixel conversion. Semantic parity, not pixel-identical native controls. Version changes documented, deprecate aliases before removal; visual regression and contrast tests on changes.

## 2. Primitive palette
| Token | Hex |
|---|---|
| brand.navy | #082344 |
| brand.blue | #005BCB |
| brand.ice | #EFF5FC |
| brand.white | #FFFFFF |
| brand.slate | #475569 |
| brand.midnight | #0B1220 |
| brand.darkSurface | #152238 |
| brand.darkAccent | #60A5FA |
| accent.success | #16A34A |
| accent.warning | #D97706 |
| accent.error | #DC2626 |
Brand midnight/darkSurface reserved for marketing/brand artwork; operational dark canvas/surface follow Shell. Accent colors not default normal text. Preserve approved logo direction, final vector/raster approval pending.

## 3. Semantic colors
| Token suffix (color.) | Light | Dark |
|---|---|---|
| surface.canvas | #F5F7FA | #0B1728 |
| surface.default | #FFFFFF | #12243A |
| surface.raised | #FFFFFF | #152238 |
| surface.subtle | #EFF5FC | #203C60 |
| text.primary | #082344 | #F1F5F9 |
| text.secondary | #475569 | #B8C7DA |
| text.muted | #475569 | #94A3B8 |
| text.inverse | #FFFFFF | #FFFFFF |
| border.decorative | #CBD5E1 | #40536B |
| border.control | #64748B | #94A3B8 |
| action.primary.bg | #005BCB | #005BCB |
| action.primary.fg | #FFFFFF | #FFFFFF |
| action.primary.hover | #004AA6 | #004AA6 |
| action.primary.pressed | #003C87 | #003C87 |
| action.link | #005BCB | #60A5FA |
| action.selected | #EFF5FC | #203C60 |
| action.secondary.bg | #FFFFFF | #12243A |
| action.secondary.fg | #082344 | #F1F5F9 |
| action.secondary.hover | #EFF5FC | #203C60 |
| action.danger.bg | #B91C1C | #B91C1C |
| action.danger.fg | #FFFFFF | #FFFFFF |
| action.danger.hover | #991B1B | #991B1B |
| focus.ring | #005BCB | #60A5FA |
| disabled.bg | #E2E8F0 | #203044 |
| disabled.fg | #475569 | #B8C7DA |
| overlay.scrim | #000000 at 48% | #000000 at 64% |
| status.success.fg/bg | #166534 / #DCFCE7 | #86EFAC / #143524 |
| status.warning.fg/bg | #92400E / #FEF3C7 | #FCD34D / #3D2C12 |
| status.error.fg/bg | #B91C1C / #FEE2E2 | #FCA5A5 / #422025 |
| status.info.fg/bg | #1E40AF / #DBEAFE | #93C5FD / #203C60 |
| status.neutral.fg/bg | #475569 / #F1F5F9 | #B8C7DA / #203044 |
Use text+icon, not color alone. Primary button in dark needs contrasting control outline when boundary necessary (border.control); focus ring 2px plus 2px contrasting offset, never clipped. Links in prose underlined. Disabled controls not a substitute for authorization; explain permitted unavailable actions separately. Status examples: Finalizado success only authoritative completion; Pendiente warning; En revisión info; Rechazado error; Borrador neutral. Payment pending never success, credit restriction not tenant suspension, OCR received not verified. Canonical state mappings remain AT-07/09/13/14. Charts use labeled series, patterns/markers and accessible data table, no red-green-only distinctions; categorical colors candidate #005BCB/#0F766E/#7C3AED/#B45309 light and #60A5FA/#5EEAD4/#C4B5FD/#FCD34D dark, test actual marks and adjacent backgrounds.

## 4. Contrast verification (calculated sRGB WCAG relative luminance)
| Foreground/background | Ratio |
|---|---:|
| #FFFFFF / #005BCB | 6.25 |
| #082344 / #FFFFFF | 15.74 |
| #475569 / #F5F7FA | 7.06 |
| #F1F5F9 / #12243A | 14.31 |
| #B8C7DA / #12243A | 9.12 |
| #60A5FA / #12243A | 6.17 |
| #64748B / #FFFFFF | 4.76 |
| #94A3B8 / #12243A | 6.12 |
| Light success/warning/error/info pairs | 6.49 / 6.37 / 5.30 / 7.15 |
| Dark success/warning/error/info pairs | 9.56 / 9.29 / 7.55 / 6.21 |
| White / primary hover / pressed | 8.30 / 10.52 |
| White / danger / danger hover | 6.47 / 8.31 |
| Decorative border on default light/dark | 1.48 / 1.99 (not sufficient for required control boundaries) |
Ratios rounded for reporting only; thresholds use unrounded values. This is palette calculation, not rendered WCAG conformance. Test every actual state, compositing, gradients, images, focus and control boundary against adjacent colors. Reference https://www.w3.org/TR/WCAG22/.

## 5. Theme behavior
Claro / Oscuro / Sistema (default Sistema proposed). Resolve system preference before first paint where possible, update on OS changes only in Sistema, persist explicit non-sensitive preference per device/browser; account synchronization optional pending approval. No tenant-specific theme or private data in preference storage. Public web defaults system too, use approved brand variants; documents retain original colors, viewer chrome adapts, no inversion of official evidence. Web color-scheme, prefers-color-scheme, forced-colors; Flutter ThemeMode.system/light/dark and platform brightness. Native system bars, dialogs and keyboard adapt. No flash, respect OS high contrast, test theme change while forms open without losing input.

## 6. Typography
Inter variable 400/500/600/700, licensed self-hosted, system sans fallback; no faux weights. Scale size/line-height/weight:
| Role | Desktop | Mobile | Weight |
|---|---|---|---|
| Display/public H1 | 48/56 | 32/40 | 700 |
| Public H2 | 32/40 | 26/34 | 700 |
| H3 | 24/32 | 24/32 | 600 |
| Workspace page title | 28/36 | 24/32 | 600 |
| Section title | 20/28 | 20/28 | 600 |
| Card title | 16/24 | 16/24 | 600 |
| Body | 16/24 | 16/24 | 400 |
| Table/small | 14/20 | 14/20 | 400 |
| Label/button | 14/20 | 16/24 | 500/600 |
| Caption | 12/16 | 12/16 | 400 |
| KPI | 32/40 | 28/36 | 700 |
No fixed-height text clipping; headings semantic not merely visual. Body max measure 65–75 characters where practical. Tabular numerals, right-align numeric columns, es-ES EUR/date/number formatting, explicit timezone, preserve VIN/NIF/reference strings. Do not use color or typographic weight alone for status. Text zoom 200%, reflow 320 CSS px, WCAG text spacing overrides; Flutter dynamic text scaling including large accessibility sizes. Spanish copy consistent tú public, concise operational labels, no fake official claims.

## 7. Geometry and layout
Spacing tokens 0,2,4,8,12,16,20,24,32,40,48,64,80,96; base 4, 2 for micro alignment. Radius 0/4/6/8/12/16/24/full (9999 web, pill geometry native). Borders 1 default, 2 emphasis/focus. Cards 16, inputs/buttons 8, dialogs 16, chips full, tables 12 outer. Standard primary controls min48, compact desktop 36 only pointer-dense and accessible, nav44, icon buttons44 desktop/48 touch, all touch controls 48 logical px target (iOS at least 44pt); actual WCAG 2.5.8 minimum 24 CSS px subject to exceptions, not project default. Table rows min48 comfortable/40 compact desktop; grow with text. Input padding 12–16, card padding 16 mobile/24 desktop. Public max1280 content, 12 columns desktop gap24, 8 tablet gap20, 4 mobile gap16; margins 32/24/16, public header72 desktop/56 mobile. Workspace desktop >=1280 sidebar256/72, topbar64, padding24, fluid 12 columns; tablet 768–1279 rail/overlay 8 columns padding20; mobile <768 drawer/topbar56 padding16 4 columns. Public hero vertical section spacing 80–96 desktop, 48–64 mobile. Workspace section gap24 desktop/16 mobile. Content width measured after shell; collapse cards when insufficient width, not device labels. No page overflow at 320; labeled table scroll only when two-dimensional content essential. Safe areas, keyboard insets, sticky actions never obscure focus. Responsive detailed spec G2 pending.

## 8. Elevation and layers
| Token | Light CSS shadow candidate | Flutter elevation guidance |
|---|---|---|
| elevation.0 | none | 0 |
| elevation.1 | 0 1px 2px rgba(8,35,68,.08) | 1 |
| elevation.2 | 0 4px 12px rgba(8,35,68,.12) | 3 |
| elevation.3 | 0 12px 32px rgba(8,35,68,.18) | 8 |
| elevation.4 | 0 24px 48px rgba(8,35,68,.24) | 16 |
Dark uses surface/outline plus black shadow, not light glow; Flutter shadows are semantic approximations, disable unwanted Material tint. Layer order base0, sticky10, navigation20, popover30, scrim40, modal50, toast60, tooltip70; modal-owned popovers above their modal via scoped layer, no arbitrary z-index. Toasts never cover focused controls; critical errors inline, not toast-only.

## 9. Icons and motion
Use [50 Lucide core icons](ICON-SYSTEM.md), nominal 24 grid/2 stroke, 16 inline,20 navigation,24 action,32 feature. Current semantic foreground, decorative aria-hidden/exclude semantics, icon-only Spanish accessible name and optional tooltip. Flutter compatible licensed glyph mapping; verify exports/license/version before implementation. No emoji as functional icons, no official seals.
Motion durations 0/100/150/200/300/400ms; hover100, press100, focus immediate, menu150, drawer/modal200–300, page transition optional150, skeleton subtle <=1200ms cycle only while loading. Ease standard cubic-bezier(.2,0,0,1), enter (.16,1,.3,1), exit (.4,0,1,1); Flutter equivalent curves. Animate opacity/transform, no layout shifts or essential information conveyed only by animation. Reduced motion removes nonessential motion/parallax/skeleton shimmer, static loading text, immediate focus; no flashing >3/sec, pause/stop moving content where required. No artificial success animations before server confirmation.

## 10. Component token baseline
Primary button uses action.primary.*; secondary uses action.secondary.* + border.control; destructive action uses action.danger.* with explicit label; text link action.link; input surface.default + border.control, label text.primary, help text.secondary, error status.error.fg plus icon/text; selected row surface.subtle + indicator/text; card surface.default + border.decorative + radius16; modal surface.raised + elevation3 + scrim; badge status pair + icon; focus ring universal. States default/hover/pressed/focus/disabled/loading/error/success/read-only/selected; no hover-only interaction. Pending/unknown distinct from zero, offline and stale distinct, denied/revoked clears private content, no optimistic payment/authorization success. Full behavior and anatomy G1 UI-COMPONENTS pending.

## 11. WCAG 2.2 AA and native accessibility
Target all applicable A/AA criteria, not only contrast. Normal text >=4.5:1, large >=3:1 (18pt or 14pt bold), meaningful non-text controls/graphics >=3:1; decorative borders exempt only when not required to identify control. Keyboard all actions, logical focus, skip link, landmarks, no traps except managed modal with escape/restore, focus visible and not obscured (2.4.11); project 2px ring is stronger design target, not claim AA requires exact thickness. Drag alternatives (2.5.7), target size (2.5.8), pointer cancellation, labels in accessible names, no orientation lock unless essential. Form labels persistent, required indication, error identification/suggestions, error summary focus, status announcements polite/urgent appropriately, financial/legal review and correction (3.3.4), redundant entry avoided (3.3.7), accessible authentication (3.3.8) supports password managers/paste and accessible alternatives; consistent help (3.2.6). Text spacing 1.5 line, 2 paragraph, .12em letter, .16em word without loss; zoom/reflow; captions/transcripts and alt for meaningful images; no images of text except essential/logo. Tables headers/scope, charts data alternative, PDF accessibility where generated, original official evidence unchanged with accessible metadata. Screen readers NVDA/JAWS/VoiceOver/TalkBack as applicable; Flutter Semantics, focus traversal, text scaling, switch access, platform accessibility settings. WCAG web target and equivalent native testing, not certification. No real personal data in fixtures. Test automated axe plus manual keyboard, screen reader, contrast, zoom, reduced motion, forced colors, touch, both themes, 320/375/768/1024/1280/1440, native font scaling and orientation. Document failures and block affected release until resolved.

## 12. Platform mapping and approval
Next.js: CSS variables semantic aliases, Tailwind/shadcn proposed adapters, next/font Inter, Lucide, CSS motion or Motion if approved. Flutter: ColorScheme plus ThemeExtension for extra semantic colors, TextTheme, component themes, spacing/radius constants, ThemeMode, MediaQuery accessibility settings. No dependencies selected/installed by this document. Shared token version and parity test fixtures; native conventions for system controls preserved. Server authorization, tenant isolation, financial truth and domain states unchanged; no private offline cache by default.
Acceptance: DS01 primitive/semantic/component hierarchy; DS02 brand reconciliation; DS03 light/dark/system; DS04 no flash; DS05 preference privacy; DS06 contrast pairs; DS07 control borders; DS08 focus; DS09 semantic status; DS10 no false success; DS11 typography/locale; DS12 text scaling; DS13 spacing; DS14 responsive grid; DS15 shell geometry; DS16 touch targets; DS17 safe areas; DS18 elevation; DS19 modal layering; DS20 icon mapping; DS21 reduced motion; DS22 keyboard; DS23 screen reader; DS24 accessible authentication; DS25 financial error prevention; DS26 chart alternatives; DS27 forced colors; DS28 native parity; DS29 version governance; DS30 no implementation authorization. All criteria proposed, runtime verification pending.
G0 specification drafted; owner approval pending. R02 proposed resolution; R19 partially addressed by standards, runtime evidence pending. Next G1 UI-COMPONENTS.md. Do not mark all design or implementation ready.
