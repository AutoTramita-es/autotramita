# AutoTramita.es — UI Component Library v1.0
2026-11-24 | AT-18 G1 | Review draft; no implementation authorization.
Sources: [Design System](DESIGN-SYSTEM.md), [Master Design Blueprint](MASTER-DESIGN-BLUEPRINT.md), [design index](README.md), all portal and public UX specifications linked therein. Accepted ADRs 001–009 and confirmed domain decisions prevail. G0 approved 2026-11-24 (tokens/themes). 90 component contracts after G1 review, not implemented widgets.

## 1. Architecture
Primitive -> composite -> business presentation. Shared semantic tokens and behavioral contracts; separate Next.js/Flutter implementations. Primitive components never fetch business data or infer permission; composite accepts explicit view state; business adapters consume generated API clients (ADR-004) and server-authorized capabilities. No new API schemas, canonical status enums, provider selection or domain approval implied. Proposed names are logical identifiers, not package paths. No portal forks unless documented accessibility/platform need. Composition slots label/icon/help/action; controlled value and change intent; stable IDs; async action lifecycle; locale/theme/density; no arbitrary CSS overrides bypassing tokens. Domain adapters own validation and authorization; backend authoritative.

## 2. Universal contract (applies to every applicable catalog row)
Hit areas: a visually smaller control (Chip remove, Checkbox, Radio, Switch, Tab) keeps a hit area of at least 44 px desktop / 48 touch without overlapping neighbors. Time: deadlines and audit show explicit timezone, default Europe/Madrid; DatePicker is date-only unless a catalog rule requires time entry; legal deadline calculation stays server-side (AT-08).
Geometry: DS radius8 controls,16 cards/dialogs,12 table, full chips; primary min48, compact desktop36 only pointer-dense, touch48, nav44 desktop/48 touch; 16/24 body,14/20 table,12/16 caption. Grow for text scaling. Use semantic surface/text/action/status/border tokens, 2px focus plus offset, no decorative border as sole control boundary. Light/Dark/System, reduced motion, es-ES, EUR, tabular amounts. All actionable components keyboard/touch operable, visible focus, accessible name/role/value, logical order, screen reader announcements, no color-only meaning; native semantics preferred. Disabled is not permission; hide unauthorized actions, explain permitted unavailable ones. Tooltips never sole label or error. Read-only values selectable when authorized; masked data never revealed by tooltip or export without separate grant.
State matrix:
| State | Presentation | Behavior |
|---|---|---|
| Default/hover/pressed/focus | DS tokens | hover optional; focus immediate; no hover-only action |
| Selected/expanded | indicator + text/semantics | keyboard and touch parity |
| Disabled/read-only | explicit reason where applicable | no mutation; no fake permission |
| Loading | skeleton for reads, labeled busy for writes | preserve safe layout; suppress duplicate submit; no fake progress |
| Empty | first-use or filtered-empty message | only authorized CTA; never substitute zero for unknown |
| Validation error | field message + summary | preserve safe input; focus summary on submit; correct and retry |
| Network/server error | redacted message, retry if safe | uncertain mutation reconcile before retry |
| Stale/conflict | version warning, refresh/review | no silent overwrite; compare authorized versions |
| Offline | explicit unavailable state | no private offline cache by default; no queued regulated/financial writes |
| Denied/revoked | generic safe landing | clear private content, cancel requests, reauthorize links |
| Success | authoritative confirmed result | no optimistic financial/legal/identity success |
| Partial success | per-item outcome | retry only eligible failed items; no duplicate effects |
Validation: client format hints only; server authoritative, localized safe error mapping, no raw stack traces or secrets. Required conditional fields derive from versioned catalog. Never silently trim identifiers beyond approved normalization. Preserve draft only in authorized scope; no private browser storage by default. Idempotency for consequential writes, version preconditions, reconcile timeout; no fabricated API error codes. Confirmation shows exact target, consequence and amount/version where relevant; cancel safe, no preselected destructive choice. Focus restoration and live status after updates. No personal data in demos.

## 3. Component catalog (90 contracts)
Each row inherits section 2, including loading/empty/error/accessibility where applicable. Noninteractive primitives do not invent interactive states. Domain-specific states are display examples, not canonical enums.
### 1. Actions and primitives
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C1.01 Button | label, optional leading/trailing icon, busy indicator | primary/secondary/ghost/danger; 48 standard, 36 compact desktop | Enter/Space; pending locks duplicate submit; keep label; disabled reason outside control |
| C1.02 IconButton | icon, accessible name, tooltip | 44 desktop/48 touch; toggle variant | pressed state announced; tooltip supplemental |
| C1.03 Link | label, optional external indicator | inline/navigation | real href for navigation; underline prose; warn before new context if needed |
| C1.04 Badge | icon and text | neutral/info/success/warning/error; 24 min visual | noninteractive; domain state mapping, never color alone |
| C1.05 Chip | label, optional remove button | filter/selection | remove has own accessible name; keyboard reachable |
| C1.06 Avatar | initials or authorized image | 24/32/40/48 | fallback initials; no sensitive image in public cache |
| C1.07 Divider | line or section label | horizontal/vertical | decorative unless semantic separator |
| C1.08 Tooltip | short supplemental text | hover/focus | dismiss Escape without moving focus; pointer can enter it; stays until blur or dismiss (WCAG 1.4.13); persistent essential instructions elsewhere |
| C1.09 SkipLink | visible-on-focus link | first focusable element | targets main landmark; visible focus; one per shell |
| C1.10 StatusAnnouncer | polite/assertive live region | one per shell | announces authoritative outcomes only; no sensitive text; no duplicate announcements |
| C1.11 CopyValue | value, copy button, confirmation | VIN/reference/code | accessible name states what is copied; confirmation announced; masked values not copyable without grant |

### 2. Forms and selection
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C2.01 Field | label, required marker, control, help, error | stacked; 48 control | persistent label; associate help/error; required not color only |
| C2.02 TextInput | field, text, optional clear | text/email/tel/search/password | preserve input on error; appropriate autocomplete; password reveal accessible |
| C2.03 TextArea | field, multiline, optional count | min 3 lines; grows | count only if real limit; no silent truncation |
| C2.04 NumberMoneyInput | field, unit/currency, value | integer/decimal/EUR/percentage | es-ES parsing; exact decimal backend; reject ambiguous input; no float money; display always groups thousands for currency (es-ES omits grouping for 4 digits by default), never groups identifiers |
| C2.05 IdentifierInput | field, identifier, format help | VIN/NIF/NIE/plate/reference | preserve original, normalize only approved rules; legacy exception review; format not identity proof |
| C2.06 Select | label, trigger, options | single/multi | native when suitable; keyboard selection; no unauthorized options |
| C2.07 Combobox | input, results, loading, empty | remote search/single/multi | debounce; cancel stale query; scoped results; no enumeration |
| C2.08 Checkbox | control, label | unchecked/checked/mixed | Space; mixed for partial selection, not consent |
| C2.09 RadioGroup | legend, choices | vertical/horizontal | arrow navigation; explicit choice for consequential decisions |
| C2.10 Switch | label, on/off | immediate preference | server-confirmed if remote; revert on failure; not consent |
| C2.11 DatePicker | label, input, calendar | date/range | typed alternative; locale; min/max from domain; date-only distinct from timestamp |
| C2.12 FilePicker | label, constraints, select/drop | single/multiple | keyboard alternative; validate client hints and server; camera fallback |
| C2.13 FormSummary | heading, error links | inline/top | focus on failed submit; preserve safe values; server errors mapped or general |
| C2.14 Stepper | steps, current, completed, controls | horizontal/vertical | no fake completion; back preserves authorized draft; review before commit |
| C2.15 AddressInput | calle, número, piso/puerta, código postal, municipio, provincia | Spanish structure; foreign address variant | postal code 5 digits with province consistency hint only; server validation authoritative; no silent normalization; autocomplete attributes |
| C2.16 PhoneInput | country code, number | +34 default; international allowed | store E.164 and original; format hint only; not proof of ownership; verification is separate |
| C2.17 OtpInput | code field(s), resend, recovery | MFA/email verification | single field semantics, paste and password manager supported; no auto-advance trap; rate-limit message generic; accessible alternative to code entry (AT-02 MFA decisions pending) |

### 3. Navigation and overlays
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C3.01 AppShell | sidebar, topbar, main, context | desktop/tablet/mobile | skip link, landmarks, active route; context server validated |
| C3.02 ContextSwitcher | workspace, tenant, branch, confirmation | single/aggregate read | unsaved guard; cancel stale requests; clear private state; no unauthorized context |
| C3.03 Breadcrumb | ordered path, current page | responsive collapse | current page announced; authorized links only |
| C3.04 Tabs | tablist, panels | horizontal/vertical | arrow keys; lazy panels if needed; hidden unauthorized tabs |
| C3.05 Pagination | page controls, range, count | cursor/page as API permits | server pagination; no invented total; announce updates |
| C3.06 Menu | trigger, items, separators | action/context | Escape restore focus; disabled reason; no bulk regulated actions |
| C3.07 Dialog | title, description, body, actions | confirmation/form; 16 radius | modal focus containment, Escape when safe, restore; explicit destructive label |
| C3.08 Drawer | title, content, close | side/bottom/fullscreen | modal semantics when blocking; safe area; no hidden focus |
| C3.09 Accordion | heading button, panel | single/multiple | expanded state; keyboard; no required content hidden without cue |
| C3.10 Toast | icon, message, optional action | info/success/error | polite announcement; non-critical only, at least 8 s plus time by length, pause on hover and focus (WCAG 2.2.1); always reachable in NotificationList; errors never auto-dismiss; critical errors persistent inline; no sensitive preview |
| C3.11 Banner | icon, heading, explanation, action | warning/error/info | persistent for blocking issues; dismiss only noncritical |
| C3.12 NotificationList | count, items, read state, link | popover/page | scoped count; reauthorize deep link; read not task completion |
| C3.13 Popover | trigger, anchored content | non-modal; mobile sheet | Escape restores focus; not for essential content; no hover-only open; scoped layer above owning modal |
| C3.14 SessionTimeoutDialog | warning, remaining time, extend/sign out | idle/expiry/reauth | warns before expiry, extend by keyboard, preserve safe draft in authorized scope, clear private content on expiry; session policy pending AT-02 |

### 4. Data and feedback
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C4.01 Card | heading, content, actions | standard/interactive; radius16 | only actionable regions focusable; avoid nested buttons |
| C4.02 DataTable | caption, headers, rows, sort, filters, pagination | 48 rows/40 compact; radius12 | native table semantics; keyboard sort; scoped server query; mobile labeled scroll/cards; currency columns group thousands consistently |
| C4.03 FilterBar | search, filters, chips, reset | inline/drawer | AND across groups OR within; applied vs draft; reset page; no sensitive persisted query |
| C4.04 BulkSelection | count, selected scope, actions | page/explicit server set | clear on context/filter change; server recheck each record; partial outcome |
| C4.05 KpiCard | label, value, period, trend, link | snapshot/period | unknown distinct zero; authorized drilldown parity |
| C4.06 Chart | title, units, legend, plot, data alternative | line/bar/donut | no color-only series; accessible table; denominator/source; no fake data |
| C4.07 Timeline | ordered events, time, actor, evidence | public/internal/audit views | allowlisted visibility; no invented progress; timestamp timezone |
| C4.08 Kanban | columns, cards, allowed actions | desktop board/mobile list | keyboard move alternative; server transitions; no filing by drag |
| C4.09 Calendar | period, events, legend, list alternative | month/week/list | legal vs internal; provisional label; no local statutory calculation |
| C4.10 Skeleton | placeholder geometry, busy label | page/card/row | no stale private data; reduced motion static |
| C4.11 EmptyState | heading, explanation, permitted action | first use/no results | differentiate empty from error/denied; clear filters option |
| C4.12 ErrorState | message, recovery, reference | inline/page | redacted errors; retry safe reads; uncertain writes reconcile |
| C4.13 Progress | label, value or indeterminate | upload/task progress | real measured percent only; announce meaningful changes |
| C4.14 OfflineStale | state, last confirmed time, recovery | offline/stale/maintenance | default no private offline cache; no queued regulated/financial writes |

### 5. Case, identity and professional workflows
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C5.01 CaseSummary | reference, service, branch, status, next action | card/detail header | authorized fields only; versioned status mapping |
| C5.02 CaseWizard | stepper, service, parties, vehicle, docs, quote, review | six steps/dynamic catalog | draft not filing; idempotent create; version pin; branch required |
| C5.03 PartySelector | customer, role, representation | person/company/representative | tenant-local; distinct owner/payer/applicant; no automatic merge |
| C5.04 VehicleSummary | masked VIN, plate, technical data, provenance | card/detail | unknown not zero; ownership claim not transfer |
| C5.05 EvidenceField | value, unit, source, review state | manual/OCR/official | suggestion not verified; conflicts reviewed; immutable snapshot |
| C5.06 DeadlineCard | date, type, source, risk, action | legal/internal/provisional | no tenant statutory override; authoritative calendar; selective block |
| C5.07 TaskAssignment | assignee, scope, deadline, action | offer/accept/decline/reassign | atomic accept; revoke prior access; no deadline reset |
| C5.08 VerificationPanel | identity, qualification, evidence, decision | tenant/professional | manual review; scope/expiry; no automatic approval |
| C5.09 FilingReview | manifest, mandate, professional scope, confirmation | manual/approved integration | recheck gates at action time; uncertain outcome reconcile; Phase 1 manual Tramisur |
| C5.10 QualityReview | checklist, findings, artifact version, decision | operational/qualified technical | separate reviewers where required; no automatic certification |
| C5.11 GuestClaim | verified login, token, entitlement, outcome | guest/customer | single use token plus independent entitlement; generic errors; no bulk grant |

### 6. Documents and signatures
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C6.01 DocumentChecklist | requirement, conditionality, file, review state | required/optional/conditional | catalog version; upload != acceptance |
| C6.02 UploadQueue | file, size, progress, cancel/retry | multi-file/camera | private scoped transfer; idempotent finalize; quarantine |
| C6.03 CaptureReview | page thumbnails, crop/rotate/reorder/retake | camera/file | permission fallback; accessible reorder; no gallery autosave |
| C6.04 DocumentViewer | toolbar, pages, zoom, download | PDF/image | authorize every access; quarantine blocked; original unchanged; accessible metadata |
| C6.05 DocumentVersion | version, hash, source, history | current/pinned/obsolete | immutable bytes; concurrent conflict; no silent replacement |
| C6.06 OcrReview | suggested value, confidence, source, correction | field comparison | no overwrite or authenticity claim; manual fallback |
| C6.07 MandatePanel | principal, representative, scope, expiry, artifact | draft/valid/revoked | mandate separate from portal entitlement; recheck at action |
| C6.08 SignatureReview | exact version, signers, intent, provider status | pending/valid/declined/expired | no private keys; changed bytes re-sign; callback not redirect confirms |
| C6.09 CsvVerification | issuer, code, match, result, evidence | verified/mismatch/unavailable/manual | allowlisted issuer; no arbitrary URL; outage not invalid; existence not match |

### 7. Finance, communications and administration
| ID / component | Anatomy | Variants / geometry | Interaction, validation and domain guard |
|---|---|---|---|
| C7.01 PriceBreakdown | service, fees, taxes, discount, total, version | estimate/final | unified public tariff; dealer-funded discount; no internal margin to customer |
| C7.02 QuoteReview | version, expiry, breakdown, acceptance | draft/accepted/expired | exact version; stale blocked; review before acceptance |
| C7.03 CreditMeter | limit, reserved, utilized, headroom, usable | active/blocked/prepaid/overlimit | tenant-wide; disjoint R/U; blocked usable zero; prepaid preserved |
| C7.04 PaymentPanel | amount, method, provider status, receipt | card/SEPA/deferred if allowed | hosted PSP; no PAN/CVV; redirect not settlement; reconcile uncertain retry |
| C7.05 InvoiceRow | issuer, number, amount, status, PDF | invoice/rectification/receipt distinct | immutable issued invoice; recipient scope; tax policy pending |
| C7.06 RefundReview | original payment, eligible amount, reason, approval | partial/full | bounded amount; approval not settlement; separate fee/credit note |
| C7.07 ProfessionalFee | contract version, work, amount, payable state | gestor/engineer | no retail leakage; no automatic payout; confirmed settlement |
| C7.08 MessageThread | participants, messages, composer, attachments | case/internal/customer | explicit audience; scoped attachments; send failure retry without duplicates |
| C7.09 AuditLog | event, actor, time, scope, redacted details | table/timeline | append-only; no edit/delete; export separate permission |
| C7.10 PermissionMatrix | role, grant, scope, effective state | read/edit/review | no self elevation; last owner protected; server authority; separate finance/export |
| C7.11 ApprovalReview | request, before/after, reason, decision | maker-checker when approved | no self approval where required; stale version recheck; central policy pending |
| C7.12 IntegrationHealth | service, status, timestamp, recovery | healthy/degraded/unknown | sanitized diagnostics; no secrets; no arbitrary commands |
| C7.13 PublicServiceCard | title, description, eligibility, CTA | public/B2B | catalog-driven; no guaranteed times or official affiliation |
| C7.14 ConsentPanel | purpose, options, policy version | cookie/privacy/terms distinct | equal accept/reject nonessential; no preselected consent; withdrawal path |

## 4. Portal composition matrix
| Surface | Required families |
|---|---|
| Public | primitives, forms, service cards, guest wizard/claim, consent, support, quote disclosure |
| Dealer | shell/context, CRM, vehicles, case table/board/wizard, docs, finance, team, reports |
| Customer | mobile action-first cards, claim, timeline, vehicles, capture, quote/signature/payment, messages |
| Gestor | future gated shell, assignment, mandate, filing, deadlines, receipt/CSV, fees; Phase 1 manual handoff |
| Engineer | gated assignment, technical evidence, Ficha authoring via forms/versioning, signature, QA, fees |
| Central | scoped cross-tenant queues, verification, approval, catalog, credit, finance, QA, audit, integrations |
All use same token and component contracts. Role/context-specific configuration only; no shared global CRM, no broad partner access. Central access explicitly scoped and audited. Public guest intake ownership remains AT-04/07 gate.

## 5. Interaction recipes
Table: query/filter/sort -> cancel previous read -> loading -> authorized results -> announce count if known -> select -> action-time authorization -> per-item outcome. Filter reset clears selection and page. URL only non-sensitive approved filters; no personal search telemetry. Cursor vs page determined by API.
Form: label/help -> client hints -> server validation -> error summary or review -> explicit submit -> busy -> authoritative result; on conflict show refresh/compare, on timeout reconcile. Password manager/paste supported. No cognitive puzzle as only authentication path.
Modal: trigger -> focus heading/first safe control -> contain focus -> cancel/confirm -> restore trigger or logical successor; Escape unless unsafe in-flight, provide explanation and recovery. Nested overlays scoped; mobile fullscreen if needed.
Document: select/capture -> preview local authorized draft -> scoped upload -> quarantine -> scan -> OCR suggestion -> review -> immutable version -> authorized access. Original not altered. CSV issuer verification independent of signature and OCR.
Financial: exact quote version -> authorized method -> review amount/fees -> PSP or approved credit -> pending -> reconciliation -> confirmed settlement or failure. Credit reservation atomic; 3 applicable business days overdue rule preserved; no guessed calendar; credit block not tenant suspension. Refund and invoice rectification independent.
Professional: minimal offer -> atomic acceptance -> scoped evidence -> professional eligibility and mandate check -> exact filing/delivery manifest -> confirmed evidence -> central closure; no automatic deadline reset or ownership transfer. Ficha Reducida ordered by AutoTramita; qualified technical QA separate.
Context: unsaved guard -> server validation -> clear old queries/selection/notifications/transfers -> new safe landing; on revoke lock/clear immediately. No old data under new heading.

## 6. Platform mapping
| Contract | Next.js candidate | Flutter candidate |
|---|---|---|
| Buttons/fields | native button/input/label, shadcn adapters | ButtonStyle, TextFormField, Form |
| Select/combobox | native select or accessible combobox | DropdownMenu/Autocomplete or accessible custom |
| Dialog/drawer/menu | accessible dialog/popover primitives | Dialog/ModalBottomSheet/MenuAnchor |
| Table/list | semantic HTML table, responsive list | DataTable/list/slivers with Semantics |
| Tabs/navigation | links/tab semantics, shell | NavigationRail/NavigationBar/TabBar |
| Calendar | accessible date input/calendar | DatePicker with typed alternative |
| Documents | safe viewer and file input | platform picker/camera, safe viewer |
| Feedback | live regions, aria-busy | Semantics live region, focus management |
| Charts | accessible chart + table | chart + semantic data alternative |
Libraries and exact versions pending. No dependencies installed. Flutter respects safe areas, keyboard, text scaling, lifecycle and native back; web respects zoom, forced colors and reduced motion. No requirement for pixel-identical native widgets. Responsive detailed contract G2 pending.

## 7. Acceptance and QA
- UI-01: Token-only styling.
- UI-02: Light/Dark/System parity.
- UI-03: No theme flash or lost form values.
- UI-04: Touch targets and scalable geometry.
- UI-05: Visible focus and keyboard operation.
- UI-06: Accessible name/role/value.
- UI-07: Screen reader status announcements.
- UI-08: Reduced motion.
- UI-09: 320px reflow and 200% zoom.
- UI-10: Native text scaling and safe areas.
- UI-11: Persistent labels and error association.
- UI-12: Server validation authoritative.
- UI-13: Error summary and preserved safe input.
- UI-14: Accessible authentication.
- UI-15: Explicit consequential review.
- UI-16: Idempotent writes and uncertain reconciliation.
- UI-17: Loading distinct from empty.
- UI-18: Unknown distinct from zero.
- UI-19: Partial success explicit.
- UI-20: Stale version conflict.
- UI-21: Revocation clears data.
- UI-22: Context switch clears old scope.
- UI-23: No private offline cache default.
- UI-24: Server-scoped search and pagination.
- UI-25: Bulk reauthorization.
- UI-26: Keyboard Kanban alternative.
- UI-27: Legal deadline provenance.
- UI-28: Guest claim independent entitlement.
- UI-29: Private document transfer/quarantine.
- UI-30: OCR not proof.
- UI-31: Exact signature version.
- UI-32: CSV outage distinct from invalid.
- UI-33: Unified tariff and discount privacy.
- UI-34: Credit disjoint balances and blocked usable.
- UI-35: Pending payment not settled.
- UI-36: Refund approval not settlement.
- UI-37: Professional scope and manual Phase 1.
- UI-38: Audit redaction and export permissions.
- UI-39: Portal composition and platform parity.
- UI-40: No implementation/deployment authorization.
- UI-41: Spanish address and phone structure preserved, server-validated.
- UI-42: OTP and session timeout accessible, no data retained after expiry.
- UI-43: Tooltip, popover and toast timing and dismissal rules.
- UI-44: Consistent currency grouping and hit-area minimums.
Test every applicable component in both themes, keyboard/touch, default/focus/disabled/loading/empty/error/stale/denied states, Spanish long labels, 320/375/768/1024/1280/1440, screen readers, reduced motion, forced colors and native scaling. Automated axe plus manual testing; cross-tenant negative tests and API contract tests per module. Fixtures fictional, no production data. Runtime evidence pending. WCAG 2.2 AA target not certification.

## 8. Delivery governance
Future component catalog/story fixtures per platform, visual regression snapshots and shared token version; no executable catalog committed in this phase. Proposed order primitives/forms -> navigation/feedback -> data -> cases/docs -> finance/professional/admin. Each implementation packet requires approved scope, API and permissions, tests and explicit authorization ADR-008. G1 approved by the product owner on 2026-11-24 after [G1 review](UI-COMPONENTS-G1-REVIEW.md) (E1–E4 applied: 8 added contracts, money grouping, tooltip/toast/hit-area rules, Europe/Madrid display); approval covers the component specification only, not implementation, runtime accessibility evidence or the open AT-02 MFA/session decisions. R01 component document gap addressed; R19 runtime evidence and domain gates remain open. Next G2 RESPONSIVE-DESIGN.md.