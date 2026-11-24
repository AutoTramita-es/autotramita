# AutoTramita.es — G1 UI Components Review
2026-11-24 | AT-18 G1 | review notes for product-owner decision | Reviews [UI-COMPONENTS.md](UI-COMPONENTS.md) v1.0 against the approved G0 [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) and the portal specifications. Product owner approved E1–E4 and G1 on 2026-11-24; all findings except G1-07 were applied in UI-COMPONENTS.md (now 90 contracts, 44 acceptance criteria).

## 1. Verified
- Catalog has 82 contracts (C1 8, C2 14, C3 12, C4 14, C5 11, C6 9, C7 14) and 40 acceptance criteria, as claimed.
- Universal contract and state matrix are consistent with DESIGN-SYSTEM.md (radii, 48/36/44 targets, focus, themes, reduced motion, no color-only meaning).
- Domain guards match accepted ADRs and decisions: tenant-local parties, guest claim with independent entitlement, upload is not acceptance, OCR is not proof, pending payment is not settled, blocked credit is not tenant suspension, Phase 1 manual Tramisur.

## 2. Findings
| ID | Severity | Finding | Proposed resolution |
|---|---|---|---|
| G1-01 | Medium | Header still says "G0 approval remains pending" (§ intro) and §8 repeats it. G0 was approved 2026-11-24. | Update both lines. |
| G1-02 | High | Components the approved specs need are missing: **AddressInput** (calle, nº, CP, municipio, provincia; Spanish structure), **PhoneInput** (+34 default, international allowed), **OtpInput / MfaChallenge** (central/partner MFA is proposed, R07), **SessionTimeoutDialog / ReauthPrompt**, **Popover** (referenced by Menu and NotificationList but never defined), **SkipLink**, **StatusAnnouncer** (live region used by many rows), **CopyValue** (VIN, references). | Add C1.09 to C7.x contracts for these 8 (90 total), same row format; acceptance criteria extended, not renumbered. |
| G1-03 | Medium | Money display: `Intl` es-ES omits thousands grouping for 4-digit numbers (1234,50 € vs 12.345,67 €). Mixed grouping in right-aligned table columns reads as an error and invites misreading. | Rule for C2.04, C4.02, C7.01, C7.05: always group thousands for currency (`useGrouping: always` on web; matching NumberFormat setting in Flutter); never group identifiers. |
| G1-04 | Medium | Tooltip row lacks WCAG 1.4.13 behavior (dismissible, hoverable, persistent until dismissed). Toast row has no timing rule (WCAG 2.2.1). | Tooltip: dismiss with Escape without moving focus, pointer can enter it, stays until blur/dismiss. Toast: non-critical only, minimum 8 s plus time proportional to length, pause on hover and focus, always reachable via NotificationList, errors never auto-dismiss. |
| G1-05 | Low | Target sizes not stated for Chip remove button, Checkbox/Radio/Switch hit areas and Tabs. Universal rule says 48 touch, but small visual controls are where this fails. | Add: visual control may be smaller, hit area at least 44 px desktop / 48 touch, with no overlap between adjacent hit areas. |
| G1-06 | Low | DatePicker covers dates and ranges only; case deadlines (C5.06) and audit use timestamps with explicit timezone. | State that timestamps are display-only unless a catalog rule needs time entry; default timezone Europe/Madrid, shown explicitly. |
| G1-07 | Low | Chart row (C4.06) still lists no tested color rule after G0-06. | Keep as pending; resolve when first chart contract is written. |

## 3. Decisions needed
| # | Decision | Recommendation |
|---|---|---|
| E1 | Add the 8 missing components (G1-02) to the catalog. | Approve. |
| E2 | Adopt the money-grouping rule (G1-03). | Approve. |
| E3 | Adopt tooltip and toast timing rules (G1-04) and hit-area rule (G1-05). | Approve. |
| E4 | Default timezone Europe/Madrid for deadline display (G1-06). | Approve; legal deadline calculation stays server-side per AT-08. |

## 4. Not covered
No rendered components exist, so state compositing, keyboard flows and screen-reader behavior are unverified. Responsive behavior is G2. No implementation, dependencies or deployment are authorized.
