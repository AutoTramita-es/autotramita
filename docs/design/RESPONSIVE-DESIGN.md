# AutoTramita.es — Responsive & Mobile Design
2026-11-24 | AT-18 G2 | v1.0 review draft
Sources: [Design System](DESIGN-SYSTEM.md), [UI Components](UI-COMPONENTS.md), [Master Design Blueprint](MASTER-DESIGN-BLUEPRINT.md), [Application Shell](SAAS-APPLICATION-SHELL.md), [Customer Portal](CUSTOMER-PORTAL.md), [design index](README.md). All nine accepted ADRs and approved domain decisions prevail. No code, deployment, dependency or provider approval.

## 1. Platform scope and release boundaries
Next.js responsive public website and all five authorized workspaces; Flutter Android/iOS including tablets, customer-first proposed release, other workspaces only after respective authorization and release gates. Same API, identity, RLS, domain state and permissions; no native-only mandatory step. Desktop remains preferred for dense administration, but mobile must offer accessible alternatives for released functions. Gestor Phase 1 manual Tramisur handoff remains; no premature partner login. Engineer procurement integrated, professional portal gated. Native OS versions, browser support, distribution, app identifiers and store accounts pending AT-01/20. No separate native business logic. Public web remains accessible without installing app. No forced app-install interstitial.

## 2. Breakpoints and geometry
Widths are CSS px on web and available logical dp on Flutter, not physical pixels. Use viewport for shell and actual remaining content width for component adaptation.
| Width | Shell | Grid | Padding/gap |
|---|---|---|---|
| 320–479 | 56 topbar, modal drawer; customer bottom nav | 4, normally single card | 16/16 |
| 480–767 | same compact shell, optional two cards if content fits | 4 | 16/16 |
| 768–1023 | overlay or 72 rail if content fits | 8 | 20/20 |
| 1024–1279 | 72 rail or overlay | 8 | 20/20 |
| 1280–1599 | 256 sidebar or 72 collapsed, topbar64 | 12 | 24/24 |
| >=1600 | same desktop shell, wider tables, bounded reading panels | 12 | 24/24 |
Public max content1280, margins32/24/16, header72 desktop and56 compact, H1 48/56 desktop and32/40 compact, section spacing80–96/48–64. Tablet header64 proposed. Workspace customer reading content max1280; operational tables fluid. No global horizontal overflow at320. Content thresholds proposed: <560 single column; 560–839 two summary cards if each fits; >=840 detail split only if main >=520 and secondary >=280 plus gap; >=960 four KPIs if each fits. Use container queries/LayoutBuilder; text scaling and intrinsic sizes can force earlier collapse. At 1280 with expanded sidebar, content976; split 8/4 feasible if minima met. Do not force split based on device name. Preserve form values, scroll anchor and selected record on resize; no duplicate mounted sensitive views. Foldable hinge and split-screen avoid occlusion; orientation unlocked except documented essential capture constraint, provide alternative. Safe areas and keyboard insets included.

## 3. Navigation and route parity
Public header links collapse into accessible drawer; service CTA in flow, no sticky overlay blocking consent or focus. Customer mobile bottom destinations Inicio / Trámites / Avisos / Cuenta, 48 touch targets, labels visible, other sections in Cuenta or contextual links. No duplicate navigation landmarks; drawer if bottom navigation cannot fit at large text. Other portals compact drawer, tablet rail, desktop sidebar; optional native shortcuts not separate authorization. Customer detail back to list preserves safe filter state; native back closes overlay then page, unsaved guard before leaving. Browser back/forward and deep links preserve route semantics. Context selector explicit tenant/branch; aggregate read only if authorized; mutation specific branch. Switch server validated, cancel old requests, clear old private data, transfers, selection, search and notifications; no old content under new heading. Multiple tabs/windows independently validate context. Customer cross-dealer case grants separate, no global CRM. Routes follow portal specifications; final registry G4.
| Workspace | Mobile first | Tablet/desktop enhancement |
|---|---|---|
| Public | service discovery, guest intake, contact | comparison, hero and B2B sections |
| Dealer | urgent tasks, cases, capture, messages | CRM, board, finance, team, reports |
| Customer | next action, case timeline, capture, quote, signature, pay | detail plus action panel |
| Gestor | assigned queue, deadlines, evidence, messages | manifest, document comparison, official filing review |
| Engineer | orders, supplements, capture, deadline | technical field comparison, Ficha authoring, QA |
| Central | alerts, scoped queues, review | cross-tenant operations, reconciliation, configuration |
All released actions remain reachable with appropriate authorization; no hiding required functions solely due to viewport. Dense or external official workflows may require supported browser/device if justified, with explicit handoff and no false completion.

## 4. Adaptive components
Dashboard: urgent actions before analytics; 1/2/4 KPI columns by available width; no invented metrics; charts responsive with data table alternative. Table: desktop semantic headers, server sort/filter/page; tablet priority columns and labeled internal scroll; compact cards with reference, service, status, next action, deadline and authorized actions; secondary fields in detail, not lost. Numeric reconciliation tables may retain horizontal region with caption, keyboard focus and sticky header if not obscuring; no page overflow. Filters compact drawer with applied count, reset, apply; clear selection on scope/filter change; preserve server query parity. Kanban mobile grouped list with allowed transition menu; no drag-only action or filing via drag. Calendar agenda default compact, month optional, legal/internal/provisional explicit. Detail 8/4 when minima met, otherwise summary then action-required, documents, timeline and remaining tabs; tab overflow via accessible menu, no clipped labels. Forms one column compact, related pairs wide, label above, 48 controls, error summary and scroll/focus into view; keyboard appropriate input type, paste/password manager allowed; no silent truncation. Wizard six steps per case spec, compact current step and progress text, full review before consequential action; save server-authorized draft only, no private persistent local draft. Dialog compact fullscreen for complex forms, bottom sheet for short choices, desktop modal; safe area, focus trap/restore, escape/back and explicit cancel. Sticky actions only when space permits; keyboard and zoom must not obscure focused control. Document viewer fit width, zoom/pan and page navigation accessible without pinch; original colors preserved; compare versions stacked on compact, split wide. Financial review shows full amount, fee, version and payer; no collapsed mandatory terms. Audit export and bulk actions separately authorized.

## 5. Camera and document capture
Entry from authorized case checklist or scoped guest intake, select camera/file, explain purpose before OS permission. Request camera only on action; no microphone/location/broad gallery permission; platform photo picker preferred. Denied/restricted/no camera -> file picker and instructions, settings link only when appropriate. Capture sequence: document type -> camera framing -> capture -> blur/glare/crop hints -> review -> rotate/crop/retake/reorder/delete page -> confirm -> scoped upload -> quarantine -> scan -> OCR suggestion -> human review. Multi-page count and limits server configured, no guessed limits; no auto-submit, no mandatory automatic edge detection, manual accessible alternative. Web file input capture hint not guaranteed, desktop file picker. Keep original where required; derivatives remove location EXIF, do not modify signed/official originals; preserve checksum and provenance. No automatic gallery save or cloud backup. Temporary files in app-private non-backup storage only while active capture/upload, encrypted where platform permits; no durable offline document vault. Clear on cancel, logout, revocation, expiry and crash recovery; startup cleanup, bounded TTL policy pending AT-09/20. Browser memory/blob URLs revoked, no IndexedDB/localStorage private files. Upload scoped short-lived authorization, validate server MIME/size/page limits, per-file progress, cancel/retry, idempotent finalize; resumable protocol only if approved and reauthorized. No background upload by default; interruption reconciles server status before retry. Quarantine blocks preview/download/OCR until safe pipeline permits. OCR not identity/authenticity proof; CSV verification independent. PDF viewer no active scripts/external fetch; accessible metadata and text where available. Explicit authorized download/share warns external copy leaves platform control; no broad OS share by default for restricted evidence.

## 6. Native identity and security
One global identity, server session and per-action authorization. Native authentication via approved system browser flow (authorization code + PKCE if selected), verified redirect, state/nonce as applicable; no embedded credential capture, no client secret in app. Web secure HttpOnly cookies and CSRF controls per AT-02; native refresh credentials only OS Keychain/Keystore-backed secure storage, access token memory where feasible, rotation/revocation per approved session policy. No tokens in URLs/logs/analytics/clipboard; claim token exception narrowly scoped, scrub URL/history and logs, single-use plus verified login and independent entitlement. Biometric local unlock optional proposal, not server identity verification, signature or MFA substitute; device passcode/reauth fallback, enrollment change invalidates local unlock where supported. No mandatory biometrics. Sensitive action step-up per approved AT-02/20; dealership MFA remains optional per AT-03, central/professional policy pending. App switcher privacy overlay on background; Android secure-window policy and iOS capture detection/obscuring where feasible, never promise universal screenshot prevention; accessibility and legitimate export reviewed. Root/jailbreak signals risk input only, enforcement pending. TLS, no trust bypass; pinning policy pending. No private data in crash reports, analytics, notifications or app backups. Session/device list and revoke, logout clears credentials/private state and detaches push registration; offline logout clears locally immediately, server revocation when possible via approved mechanism, do not claim remote revocation until confirmed. No impersonation.

## 7. Push, notifications and deep links
In-app inbox authoritative; optional push APNs/FCM candidates, web push optional separate gate, email per AT-16. Ask OS permission after contextual explanation, denial does not block service; settings by channel/category, legal/security communications distinct from marketing. Register installation token authenticated, bind account and authorized context server-side; rotate on token change, detach on logout/account switch/revoke, handle invalid tokens; no shared-device leakage. Payload generic Spanish text e.g. 'Tienes una nueva actualización', opaque notification identifier only, no name/VIN/NIF/amount/document/claim token. Lock screen minimal, badge count authorized or absent, no sensitive action buttons. Deduplicate event/recipient/channel, retry and delivery state separate from business outcome; push not guaranteed, no legal deadline reliance on delivery. Read != task completion.
HTTPS verified Android App Links/iOS Universal Links, web fallback; allowlisted host/path, reject arbitrary redirects, malformed IDs and untrusted schemes; association files and signing identifiers pending deployment approval. Cold/warm link: parse -> safe route -> authenticate -> server entitlement -> authorized context switch if needed -> fetch fresh resource -> render or generic denied. Never reveal target details before authorization; expired/revoked links generic recovery. Guest claim token consumed only explicit claim after verification, not link preview/scanner GET; payment/signature return only correlation and reconciliation, never success. No private payload in route state; safe return path allowlist, no open redirect. Notification tap while editing triggers unsaved guard; account mismatch generic switch option. Test duplicate/reordered links and callback replay.

## 8. Offline and lifecycle
Default no private offline cache; public static assets and non-sensitive theme preference only may persist. No offline regulated filing, signature, payment, credit, refund, assignment, ownership or message queue. Offline screen 'Sin conexión' with retry, no fake zero; hide private data when authorization freshness cannot be established, no stale private view after revocation. In-memory form/capture may survive brief foreground interruption within authorized session only; no durable offline draft. Network restored -> validate session/context -> reconcile uncertain mutations/uploads -> fetch fresh -> render. Server draft saved only on confirmed response. Retry reads with bounded backoff; writes use idempotency and reconciliation, never blindly repeat. Connectivity indicator is hint, not proof of server reachability.
| Lifecycle | Required behavior |
|---|---|
| Cold start | safe splash, theme, session check, context check, route authorization, no private flash |
| Foreground active | authorized data, bounded session freshness, cancellation on context change |
| Inactive/background | obscure snapshot, stop camera, pause sensitive work, cancel or safely suspend transfers |
| Resume | lock if policy requires, revalidate session/context/entitlement, refresh data, reconcile pending |
| OS kill/crash | no reliance on final callback; startup cleanup, recover only confirmed server drafts/status |
| Logout/revoke | clear protected state, temporary files, credentials, notification binding; generic landing |
| Upgrade | compatible API check, safe migration of non-sensitive preferences, no private cache migration |
| Maintenance/API mismatch | safe blocking or read-only public help, no unsupported mutations |
Session timeout, background grace, cleanup TTL, min supported version and forced update policy pending security/product approval. No background worker assumed reliable on iOS/Android. Web visibilitychange/page restore/bfcache revalidate before showing private content; private responses no-store, service worker excludes authenticated API/documents, no sensitive prefetch. PWA install optional future gate.

## 9. Accessibility and platform parity
WCAG 2.2 AA web target, equivalent native testing; DS contrast normal4.5:1, large3:1, meaningful controls3:1; text+icon status. 48 logical touch targets, desktop compact36 only where pointer dense and accessible. 320 CSS reflow, 200% zoom, text spacing, native dynamic text scaling without clipping; orientation and keyboard support, external keyboard on tablet, VoiceOver/TalkBack, NVDA/JAWS as applicable. Semantic headings/landmarks, labels, focus order, visible non-obscured focus, error summary, live status, reduced motion, high contrast/forced colors, accessible authentication, no gesture-only actions. Camera manual/file alternative; document accessible metadata; charts table; no color-only or sound-only alert. Native back and system bars adapt to theme; safe areas/notches/hinges; no forced portrait. Spanish long labels and international names, locale es-ES/EUR, timezone explicit; no mandatory second surname. Test actual controls, not just palette. No claim of certification.

## 10. Threat and test matrix
| Threat | Control/test |
|---|---|
| Cross-tenant stale response | context version, cancel/ignore, RLS negative tests |
| Lost/shared device | secure storage, revoke, minimal push, no private backup |
| Link hijack/replay | verified domains, allowlist, reauth, single-use claim, callback reconciliation |
| Malicious file | quarantine, server validation, safe viewer, no external fetch |
| Temporary file leakage | private non-backup storage, cleanup, crash recovery |
| Duplicate financial/official write | idempotency, authoritative reconciliation, no offline queue |
| Background snapshot | privacy overlay, platform capability tests |
| Accessibility regression | keyboard, screen reader, zoom, scaling, contrast, reduced motion |
Test widths 320/375/390/480/767/768/1024/1279/1280/1440/1920, portrait/landscape, split-screen, foldable, keyboard open, 200% zoom and large native text, light/dark/system. Real Android/iOS phone/tablet plus browser matrix (versions pending), camera denied/restricted, low storage, network loss mid-upload, slow network, process kill, revoked session, expired link, payment callback, context switch, notification permission denied, screen reader and external keyboard. Measure performance on representative low-end devices; budgets proposed at AT-01/20, no invented benchmarks. Use fictional fixtures, no production data. Native store privacy disclosures, permissions strings, accessibility and security review before release.

## 11. Acceptance criteria
- RD-01: Platform scope and release gates.
- RD-02: Shared API and identity.
- RD-03: Public web without install.
- RD-04: Breakpoint boundaries.
- RD-05: Content-width adaptation.
- RD-06: 320 reflow.
- RD-07: Desktop shell geometry.
- RD-08: Tablet rail/overlay.
- RD-09: Customer bottom navigation.
- RD-10: Other portal drawer.
- RD-11: Safe area and keyboard.
- RD-12: Orientation and foldable.
- RD-13: Resize preserves safe state.
- RD-14: Context switch authorization.
- RD-15: No stale cross-tenant data.
- RD-16: Route/back parity.
- RD-17: Unsaved guard.
- RD-18: Action-first dashboard.
- RD-19: Table/card parity.
- RD-20: Accessible filter drawer.
- RD-21: Kanban keyboard alternative.
- RD-22: Calendar agenda.
- RD-23: Adaptive detail.
- RD-24: Form labels and errors.
- RD-25: Wizard review.
- RD-26: Modal focus restoration.
- RD-27: Sticky action non-obscuration.
- RD-28: Document zoom alternative.
- RD-29: Financial review completeness.
- RD-30: Just-in-time camera permission.
- RD-31: File picker fallback.
- RD-32: No broad permissions.
- RD-33: Multi-page capture.
- RD-34: Manual crop/reorder alternative.
- RD-35: Original preservation.
- RD-36: No gallery autosave.
- RD-37: Temporary file protection.
- RD-38: Crash cleanup.
- RD-39: Scoped upload.
- RD-40: Idempotent finalize.
- RD-41: Quarantine.
- RD-42: OCR distinct from verification.
- RD-43: Safe PDF viewer.
- RD-44: Secure native authentication.
- RD-45: OS secure credential storage.
- RD-46: No token logging.
- RD-47: Optional biometric fallback.
- RD-48: Biometric not MFA/signature.
- RD-49: Snapshot privacy limitations.
- RD-50: Session revocation.
- RD-51: Local logout vs remote confirmation.
- RD-52: Push opt-in.
- RD-53: Minimal payload.
- RD-54: Token lifecycle.
- RD-55: Inbox authoritative.
- RD-56: Delivery not legal proof.
- RD-57: Verified deep links.
- RD-58: Allowlisted return path.
- RD-59: Cold/warm link reauthorization.
- RD-60: Claim explicit single use.
- RD-61: Callback not success.
- RD-62: No private offline cache.
- RD-63: No offline mutation queue.
- RD-64: Reconnect reconciliation.
- RD-65: Cold start no private flash.
- RD-66: Background camera stop.
- RD-67: Resume revalidation.
- RD-68: OS kill recovery.
- RD-69: Web bfcache revalidation.
- RD-70: Service worker excludes private data.
- RD-71: WCAG contrast and semantics.
- RD-72: Touch targets.
- RD-73: Text scaling and zoom.
- RD-74: Screen reader and keyboard.
- RD-75: Reduced motion and forced colors.
- RD-76: Native/web parity tests.
- RD-77: Threat negative tests.
- RD-78: No production fixtures.
- RD-79: Open security and release gates.
- RD-80: No implementation/deployment.

## 12. Governance
G2 specification drafted, owner approval pending alongside G0/G1. R13 design gap addressed by proposal, runtime/security validation pending; R19 remains open for evidence. No ADR amended. AT-02 session/MFA, AT-09 retention/capture/upload, AT-14 PSP callback, AT-16 notification taxonomy/provider, AT-20 threat/security policy, platform versions and distribution remain gates. Next G3 IMAGE-ASSETS.md, then G4 roadmap, G5 bounded foundation review, G6 execution order. No implementation authorization.