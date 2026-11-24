# AutoTramita.es — G0 Design System Review
2026-11-24 | AT-18 G0 | review notes for product-owner decision | Reviews [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) v1.0 against [BRAND-IDENTITY.md](BRAND-IDENTITY.md) and the [Master Design Blueprint](MASTER-DESIGN-BLUEPRINT.md). Product owner approved D1–D6 on 2026-11-24; fixes G0-01 to G0-05 were then applied in DESIGN-SYSTEM.md (G0-06/G0-07 remain notes for G1/brand export). Recalculated values are WCAG 2.2 relative-luminance arithmetic on the palette, not rendered conformance.

## 1. What was verified
- All 22 contrast ratios in DESIGN-SYSTEM.md §4 were recalculated and match to two decimals.
- Brand palette and typography agree between DESIGN-SYSTEM.md and BRAND-IDENTITY.md; R02 (brand midnight #0B1220 vs shell canvas #0B1728) is handled by keeping both as named tokens.
- Light-theme control boundary #64748B reaches 4.76 on white, 4.43 on canvas, 4.34 on ice, so the 3:1 non-text requirement holds on all light surfaces. Dark #94A3B8 reaches 4.36 on the selected surface.

## 2. Findings
| ID | Severity | Finding | Proposed resolution |
|---|---|---|---|
| G0-01 | High | Dark `action.link` #60A5FA on `surface.subtle`/`action.selected` #203C60 is **4.40:1**, below 4.5 for normal text. Links in selected rows or subtle panels fail in dark. | Use #93C5FD on those surfaces (6.21:1), or add a `action.link.onSubtle` token. |
| G0-02 | Medium | `text.muted` and `text.secondary` are the same #475569 in light, so there is no hierarchy; dark values differ. | Pick a lighter light muted that still passes: #586377 gives 6.06 on white, 5.65 on canvas, 5.52 on ice, 4.91 on #E2E8F0. |
| G0-03 | Medium | Primitive table (§2) lists 11 values, yet semantic tokens use many literals that are not primitives (#F5F7FA, #CBD5E1, #64748B, #12243A, #203C60, #F1F5F9, #B8C7DA and others). This contradicts DS01 (no hardcoded hex above the primitive layer). | Add a complete neutral/blue ramp as primitives and make every semantic value reference one. Brand file's `dark-text` #F1F5F9 should map the same way. |
| G0-04 | Medium | Primary button fill #005BCB against dark surface/canvas is **2.51 / 2.88**, below 3:1 for the control boundary. The spec already requires `border.control` in dark; make that mandatory, not conditional. | State that dark primary buttons always carry a 1px border.control or lighter outline. |
| G0-05 | Low | Accent success #16A34A (3.30), warning #D97706 (3.19) and white text on success green (3.30) fail normal-text contrast. §3 already forbids accent as text. | Add explicit rule: no white text on accent.success; fills use the status pairs. |
| G0-06 | Low | Chart categorical colors pass on white (5.0–5.7) and on dark surface (8.5–10.6), but only as swatches. Adjacent-series contrast and pattern/marker redundancy are untested. | Keep as candidates; verify in G1 chart contracts. |
| G0-07 | Low | Logo SVG wordmarks use live Inter/Arial text, 12 SVG sample wireframes use Arial. | Outline approved wordmark (already V01). Nothing to change in G0. |

## 3. Decisions needed from the product owner
| # | Decision | Recommendation |
|---|---|---|
| D1 | Default theme **Sistema** (follow OS), with Claro/Oscuro override per device. | Approve. |
| D2 | Keep brand midnight #0B1220/darkSurface #152238 for marketing only; operational dark follows #0B1728/#12243A. | Approve (resolves R02). |
| D3 | Default control height 48 px (compact 36 only on dense desktop with pointer), instead of the WCAG minimum 24. | Approve. |
| D4 | Inter variable, self-hosted (OFL), as the single typeface. | Approve; confirm license notice is kept. |
| D5 | Fix G0-01 and G0-02 values as proposed. | Approve both. |
| D6 | Whether theme preference may sync to the user account (currently device-only, sync optional). | Keep device-only until AT-02 decides. |

## 4. Not covered
No rendered pages exist, so focus rings, state compositing, gradients over images, forced-colors and Flutter parity are unverified. Component anatomy is G1, responsive behavior G2. No implementation, dependencies or deployment are authorized by this review.
