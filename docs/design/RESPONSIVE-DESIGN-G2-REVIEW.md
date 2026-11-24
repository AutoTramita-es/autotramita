# AutoTramita.es — G2 Responsive Design Review
2026-11-24 | AT-18 G2 | review notes for product-owner decision | Reviews [RESPONSIVE-DESIGN.md](RESPONSIVE-DESIGN.md) v1.0 against approved G0 [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md), approved G1 [UI-COMPONENTS.md](UI-COMPONENTS.md), [SAAS-APPLICATION-SHELL.md](SAAS-APPLICATION-SHELL.md) and [CUSTOMER-PORTAL.md](CUSTOMER-PORTAL.md). Product owner approved F1–F5 and G2 on 2026-11-24; findings G2-01 to G2-05 were applied (G2-06 stays open by design).

## 1. Verified
- 80 acceptance criteria (RD-01 to RD-80), as claimed.
- Breakpoints agree with DESIGN-SYSTEM.md §7 and the shell: desktop ≥1280 with 256/72 sidebar and 64 topbar, tablet 768–1279 rail or overlay, mobile <768 with 56 topbar and 16 padding.
- Content width arithmetic is correct: 1280 with expanded sidebar leaves 976 px (1280 − 256 − 2×24), enough for an 8/4 split (520 + 280 + gap) and four KPIs (≥960); at 1024 with the 72 rail content is about 912, so two KPI columns, as the thresholds imply.
- Security-sensitive sections (native auth with PKCE, secure storage, no tokens in URLs/logs, push payload without personal data, verified deep links, claim token consumed only on explicit action, no private offline cache) are consistent with ADR-003/005 and the AT-02/09/20 gates they name as open.

## 2. Findings
| ID | Severity | Finding | Proposed resolution |
|---|---|---|---|
| G2-01 | Medium | Customer bottom navigation label conflict: SAAS-APPLICATION-SHELL.md says Inicio / **Expedientes** / Avisos / Cuenta; CUSTOMER-PORTAL.md and RESPONSIVE-DESIGN.md say Inicio / **Trámites** / Avisos / Cuenta. | Use **Trámites** everywhere (matches brand copy "Tus trámites", route /cliente/tramites, Badge/case wording); fix the shell text. |
| G2-02 | Medium | Breakpoint table says 480–767 may show "optional two cards if content fits", while the content thresholds say <560 is single column. Cards between 480 and 559 would break the threshold. | Content-width thresholds govern: single column below 560 of available content width; the table row is only the shell geometry. |
| G2-03 | Low | Tablet header 64 is "proposed" here, but DESIGN-SYSTEM.md and the shell give topbar 64 (desktop) and 56 (mobile) and say nothing for 768–1279. | Add to DESIGN-SYSTEM.md: topbar 64 on tablet and desktop, 56 below 768; public header 72 desktop, 64 tablet, 56 compact. |
| G2-04 | Medium | G1 added components (OtpInput, SessionTimeoutDialog, AddressInput, PhoneInput, SkipLink, StatusAnnouncer) that this document does not mention. Native details are missing: OTP autofill hints (`autocomplete=one-time-code`, iOS `oneTimeCode`, Android autofill), numeric keyboard types for phone/postal code, timeout behavior when backgrounded. | Add a short cross-reference paragraph (§9) listing these; timeout/session lengths stay pending AT-02. |
| G2-05 | Low | Governance lines are stale: "owner approval pending alongside G0/G1" and "Next G3 IMAGE-ASSETS.md". G0 and G1 are approved, G3 documentation is done. | Update §12. |
| G2-06 | Info | Browser/OS support matrix, performance budgets, session timeout, background grace, cleanup TTL, minimum app version and distribution identifiers are all explicitly pending AT-01/02/09/20. This is correct, but means G2 can only be approved as a specification, not as a release gate. | Keep as open gates; no change. |

## 3. Decisions needed
| # | Decision | Recommendation |
|---|---|---|
| F1 | Customer bottom nav label is **Trámites** (G2-01). | Approve. |
| F2 | Content-width thresholds override the shell breakpoint rows (G2-02). | Approve. |
| F3 | Topbar 64 on tablet and desktop, 56 on mobile; public header 72/64/56 (G2-03). | Approve. |
| F4 | Add the G1 cross-reference paragraph (G2-04). | Approve. |
| F5 | Approve G2 as a **specification only**; AT-01/02/09/14/16/20 gates and runtime evidence stay open (G2-06). | Approve. |

## 4. Not covered
No rendered layouts, devices or native builds exist, so resize behavior, safe areas, camera flow, lifecycle and accessibility are unverified. No implementation, dependencies or deployment are authorized.
