# AutoTramita.es — DESIGN ROADMAP
2026-11-24 | AT-18 G4 | v1.0 proposed for owner review
Authority: [Master Blueprint](../MASTER-BLUEPRINT.md), [Master Design Blueprint](MASTER-DESIGN-BLUEPRINT.md), [ADR register](../adr/ADR-REGISTER.md), [design index](README.md). All nine ADRs and confirmed decisions prevail. No implementation, migration, dependency installation or deployment authorized. Roadmap is dependency-based, not a calendar or budget estimate.

## 1. Evidence and precedence
Reviewed current master/index and retrieved nine ADRs plus all 23 indexed design specifications, examining scope and relevant gates; prior source audit covers 85 indexed SVGs, G3 rechecked 18. No fresh full rendered QA or raster recovery. Status: 27 AT-03 business decisions confirmed, AT-04 D01–25 proposed, AT-08 approved in principle; all five portals and public web designed for review, not implemented. G0–G4 documentation drafted, owner approval pending. G3 asset release gate open. No readiness percentage inferred from document count. Accepted ADR > confirmed domain decision consistent with ADR > approved domain contract > shared DS/components/responsive > portal draft/wireframe. Conflicts stop affected packet; explicit amendment if necessary.

## 2. ADR traceability
| ADR | Binding rule | Gate |
|---|---|---|
| [001](../adr/ADR-001-technology-stack.md) | FastAPI modular monolith, PostgreSQL, SQLAlchemy, Alembic, Redis/Celery, S3, Next.js, Flutter, Docker | hosting, versions, environments, OIDC |
| [002](../adr/ADR-002-multi-tenancy-rls.md) | non-null tenant UUID, forced RLS USING/WITH CHECK, transaction-local context same connection, composite FKs, non-owner/non-bypass runtime role | negative tests, worker/cache/storage/admin isolation |
| [003](../adr/ADR-003-identity-customer-membership.md) | global identity, tenant-local CRM, independent customer entitlement, secure single-use claim | merge, routing, claim, roles |
| [004](../adr/ADR-004-api-contracts.md) | /api/v1, OpenAPI generated TS/Dart, idempotency, signed webhooks | errors, pagination, limits, contracts |
| [005](../adr/ADR-005-document-storage.md) | private objects, case/tenant authorization, audit | storage, quarantine, retention, verification evidence scope |
| [006](../adr/ADR-006-service-catalog-case-workflows.md) | versioned catalog, case snapshots, authorized gestor, integrated outsourced Ficha | service legality, state machine, partner scope |
| [007](../adr/ADR-007-pricing-credit-payments.md) | unified public tariff, dealer-funded discount, central credit/card collection, 3 applicable business days overdue blocks new credit only | PSP, funds flow, tax, calendar, SEPA, ledger |
| [008](../adr/ADR-008-delivery-governance.md) | approved bounded packets, PR/test review, explicit authorization | G5/G6 and every packet |
| [009](../adr/ADR-009-tenant-organization-membership-verification.md) | one legal entity/tenant, branches, manual final verification | reconcile 27 decisions, last owner, invitation/branch constraints |

## 3. Module dependency register
Dependencies below refer to minimum approved slices, not full completion of entire modules. AT-20 security/legal and AT-18 UX apply throughout; AT-17 central permission slice required before privileged operations. Avoid circular dependency by defining shared contracts first, then adapters; no placeholder bypasses.
| Module | Priority | Required upstream slices | Deliverable / open gate |
|---|---|---|---|
| AT-01 Foundation | P0 | AT-20 baseline | local dev/CI, DB roles, migrations, API conventions, observability; versions/hosting/restore |
| AT-02 Identity | P0 | 01 | OIDC, global User, sessions, recovery, scoped authorization; MFA and provider |
| AT-03 Organization | P0 | 01/02,09 verification evidence contract,17 reviewer grant | tenant/branch/membership, manual approval; reconcile D01–27 |
| AT-04 Customers | P1 | 02/03 | tenant CRM, representation, entitlement; approve D01–25, guest ownership/merge |
| AT-05 Vehicles | P1 | 03/04 | VIN/plate history, ownership evidence; legacy IDs and snapshots |
| AT-06 Catalog | P1 | 01/17, legal service review | versioned requirements/eligibility; publish approved services only |
| AT-07 Cases | P1 | 03/04/05/06 | case snapshot, tasks, assignment, transition matrix; reopen/cancel/claim |
| AT-08 Deadlines | P1 | 07,16 event contract | verified rules/calendar, legal review, alerts; test vectors |
| AT-09 Documents | P0/P1 | 01/02/03 entitlement contract;07 for case evidence | separate verification scope before onboarding, then case files; scan/limits/retention/signatures |
| AT-10 Gestor | P1/P2 | 07/08/09/17 | manual Tramisur handoff first; future verified partner portal |
| AT-11 Engineer | P1/P2 | 05/07/08/09/17 | central Ficha procurement first; future portal/editor; qualification/QA/fees |
| AT-12 Pricing | P1 | 06/03/17 | versioned public tariff/quotes, dealer discount; allocation/tax/caps |
| AT-13 Credit | P2 | 03/12/14 ledger,08 calendar | central facility, atomic reservations, grace; ledger/calendar/SEPA |
| AT-14 Payments | P1/P2 | 12/07/17,20 financial review | prepaid card, invoice/reconciliation/refund first; later credit/SEPA; PSP/funds flow |
| AT-15 Institutions | P3 | 07/08/09/10/11 as relevant | verified official access, adapters, uncertain outcome handling; no assumed APIs |
| AT-16 Communication | P1 | 02/03, event contracts | in-app/email, scoped threads, outbox; recipients/privacy/provider |
| AT-17 Central admin | P0–P3 | 01/02 then each domain | narrow reviewer grants first, operations/finance later; role/dual approval matrix |
| AT-18 UX | P0–P3 | DS/G1/G2 approved per slice, API contracts | shell then dealer/admin/customer/public, later professionals/native; visual QA |
| AT-19 Analytics | P1–P3 | 07/08/14/13 as relevant | basic operational counts first, finance/advanced metrics later; dictionary |
| AT-20 Compliance | P0–P3 | none; continuous | threat model, privacy, audit, contracts, incident/restore, legal/tax release evidence |

## 4. Design specification register (23 inputs)
| Specification | Delivery use |
|---|---|
| [BRAND-IDENTITY.md](BRAND-IDENTITY.md) | approved direction; final logo release |
| [WEBSITE-STRUCTURE.md](WEBSITE-STRUCTURE.md) | public landing |
| [SERVICE-PAGES.md](SERVICE-PAGES.md) | catalog and guest intake |
| [B2B-PAGES.md](B2B-PAGES.md) | partner onboarding |
| [PUBLIC-AUTH-SUPPORT-LEGAL.md](PUBLIC-AUTH-SUPPORT-LEGAL.md) | auth/support/legal |
| [SAAS-APPLICATION-SHELL.md](SAAS-APPLICATION-SHELL.md) | shared navigation/context |
| [DEALER-DASHBOARD.md](DEALER-DASHBOARD.md) | operational KPIs |
| [CASE-MANAGEMENT.md](CASE-MANAGEMENT.md) | case workflow |
| [DEALER-CRM-VEHICLES.md](DEALER-CRM-VEHICLES.md) | CRM/vehicle |
| [DOCUMENTS-DIGITAL-SIGNATURES.md](DOCUMENTS-DIGITAL-SIGNATURES.md) | private evidence |
| [FINANCE-CREDIT-MANAGEMENT.md](FINANCE-CREDIT-MANAGEMENT.md) | quotes/payments/credit |
| [ORGANIZATION-EMPLOYEE-MANAGEMENT.md](ORGANIZATION-EMPLOYEE-MANAGEMENT.md) | tenant/branch/staff |
| [CUSTOMER-PORTAL.md](CUSTOMER-PORTAL.md) | mobile web first |
| [GESTOR-PORTAL.md](GESTOR-PORTAL.md) | future portal; manual first |
| [ENGINEER-PORTAL.md](ENGINEER-PORTAL.md) | future portal; procurement first |
| [CENTRAL-ADMIN-PORTAL.md](CENTRAL-ADMIN-PORTAL.md) | incremental privileged operations |
| [ICON-SYSTEM.md](ICON-SYSTEM.md) | licensed icon mapping |
| [BACKGROUND-PATTERNS.md](BACKGROUND-PATTERNS.md) | decorative assets |
| [HERO-BANNERS.md](HERO-BANNERS.md) | raster recovery |
| [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md) | semantic tokens |
| [UI-COMPONENTS.md](UI-COMPONENTS.md) | 90 component contracts (82 originally; 8 added in G1 review) |
| [RESPONSIVE-DESIGN.md](RESPONSIVE-DESIGN.md) | web/native parity |
| [IMAGE-ASSETS.md](IMAGE-ASSETS.md) | manifest/rights/QA |
All detailed designs review drafts unless explicitly inherited approved decisions. DS supersedes schematic geometry only after owner approval; resolve B2B mobile spacing40 vs DS48–64, icon touch preference44 vs project48, customer header64 vs56, professional sidebar240 vs256/rail. No silent business changes.

## 5. Proposed development phases and checkpoints
| Packet | Scope | Prerequisite | Exit evidence |
|---|---|---|---|
| F0 | G5 foundation spec and G6 execution order | G4 review | approved bounded packet, explicit authorization |
| F1 | AT-01 local skeleton, CI, migration baseline, RLS test harness, shared API conventions | F0 | reproducible local tests, non-bypass role, migration rollback |
| F2 | AT-02 global identity/session/context; AT-17 minimal reviewer grants | F1 | auth/revoke/negative tests, scoped audit |
| F3a | AT-03 tenant/branch/membership schema and pending onboarding; AT-09 private verification evidence slice | F2 | composite constraints, scoped evidence, no production access before approval |
| F3b | manual verification, invitations, branch grants, owner protection, reassignment queue; shared shell | F3a | all27 mapped tests, concurrency/last owner, central review, UI access tests |
| F4 | AT-04/05 CRM and vehicles | F3b | tenant-local records, no auto merge/ownership, evidence and snapshots |
| F5 | AT-06 catalog + AT-07 case/task core | F4, legal service scope | version pin, authorized transitions, idempotent create, guest routing contract |
| F6 | AT-09 case docs + AT-08 deadlines + AT-16 notifications | F5 | quarantine/entitlement, verified calendar fixtures, dedup and receipt exceptions |
| F7 | AT-10 manual Tramisur + AT-11 manual integrated procurement + AT-17 operations | F6, professional contracts | evidence manifest, authorized handoff, receipt/QA/closure; no automatic official filing |
| F8 | AT-12 quotes + AT-14 prepaid payments/invoices/refunds | F5–7, financial approval | price snapshots, PSP sandbox, webhook/reconciliation, refund/rectification tests |
| F9 | AT-18 public/dealer/customer/admin complete MVP journeys + AT-19 basic metrics | F3–8 | secure guest claim, responsive/accessibility, full E2E, asset/legal approval |
| F10 | AT-13 credit + AT-14 deferred/SEPA | F8, separate finance gates | atomic exposure, grace calendar, confirmed settlement, no double count |
| F11 | AT-10/11 professional portals, honoraria, technical editor/signatures | F7, qualification/security/fee gates | scoped assignments, signed hash/QA, no unqualified certification |
| F12 | AT-15 official integrations | relevant F7/F11 and authority/provider approvals | sandbox/contract tests, uncertain outcome reconciliation |
| F13 | Flutter customer first, later authorized workspaces; AT-19 advanced analytics | stable API, mobile security/store gates, metrics | native device tests, no private offline cache, verified deep links |
F10–13 can be reordered or parallelized after relevant gates; no date commitment. F3a/F3b split avoids tenant verification/document/central reviewer circularity. F5/F6 split case shell from document processing; no live intake until required evidence and deadlines ready. AT-20 release controls at every checkpoint. No deployment included in any packet authorization.

## 6. MVP definition
Proposed commercial MVP = F1–F9 approved slices, limited verified services only. Public service discovery, guest intake with non-null approved tenant/branch routing, secure claim, dealer onboarding/branches/staff, CRM/vehicle, versioned case, checklist, private upload/review, verified deadlines, central task/quality, manual Tramisur regulated handoff, AutoTramita-procured Ficha where offered, versioned quote, central prepaid card payment, lawful invoice/refund/reconciliation, customer responsive web, scoped communication, basic operational counts. Professional work remains external and qualified; no partner portal needed for phase 1. Candidate pilot service list must be selected by owner/legal review, not inferred from illustrations. Internal synthetic-data pilot may precede PSP/legal approval but no real customer/payment/regulated action. Commercial release requires actual PSP/funds flow/tax/legal/professional approvals, not fake paid status or manual workaround. Credit/SEPA, advanced OCR/signature automation, direct institutional APIs, native apps, professional portals and advanced analytics deferred unless necessary for chosen service; required legal signature/evidence cannot be deferred, use approved lawful manual process or exclude service. No automatic migration of old case terms.

## 7. Open findings and owners
| Finding | Priority / accountable workstream | Required resolution |
|---|---|---|
| R01 | P0 AT-18 | five missing docs now drafted incl this; approve applicable docs |
| R02 | P0 AT-18 | approve brand vs semantic dark tokens; rendered contrast |
| R03 | P0 AT-03 | reconcile D11–13/22–23 with ADR/drafts; owner/manager/reassignment/closure |
| R04 | P1 AT-04/07 | guest tenant/branch routing and independent entitlement |
| R05 | P1 AT-07 | canonical transitions and orthogonal blockers |
| R06 | P1 AT-10/17 | preserve manual Tramisur, future portal gated |
| R07 | P0 AT-02/20 | dealer optional MFA, central/professional assurance separately approved |
| R08 | P0/P1 AT-09 | separate verification and case grants; standalone CRM docs deferred until approved |
| R09 | P1/P2 AT-12/13/14/20 | PSP, merchant/funds flow, tax, ledger, discounts, calendar/SEPA |
| R10 | P2 AT-19 | one aging dictionary, calendar vs business grace |
| R11 | P0 AT-17 | central permission matrix, separation of duties and audit |
| R12 | P0/P1 AT-18 | route registry below, approve exact paths/redirects |
| R13 | P3 AT-18/20 | G2 proposal exists; native security/device evidence pending |
| R14 | P1 AT-18 | geometry/typography, rendered QA |
| R15 | P1/P3 AT-15/20 | official authority, legal copy, CSV verification; no assumed API |
| R16 | P1/P3 AT-19 | metric definitions and fixtures |
| R17 | P0 AT-18 | update indexes, preserve historical baseline |
| R18 | P1 AT-18 | recover28 rasters, rights, exports, durable interaction specs |
| R19 | P0–P3 AT-18 | actual accessibility evidence per release |
| R20 | P0 AT-01/02 | API error/pagination/idempotency/auth contracts |
No finding closed solely by drafting. Owners are workstreams, named human approvers assigned in G5. P0 blocks affected foundation packet; P1 blocks affected MVP slice; P2/P3 blocks expansion. Additional open gates: OIDC, hosting, backups, retention, provider contracts, service legal requirements, fiscal treatment, operational SLA, platform versions. Product owner approves business decisions; qualified legal/tax/security review where required.

## 8. Candidate canonical registries (not approved API/enums)
Routes: public /, /servicios, /servicios/[slug], /tramites/nuevo, /profesionales, /profesionales/concesionarios, /profesionales/importadores, /profesionales/colaboradores, /contacto, /acceder; recovery/claim/legal exact slugs pending. Workspaces /empresa, /cliente, /gestoria, /ingenieria, /administracion. Dealer /empresa/expedientes, /empresa/clientes, /empresa/vehiculos, /empresa/centros, /empresa/equipo, /empresa/configuracion/empresa, /empresa/finanzas/{pagos,facturas,credito}; quotes path approval pending. Child detail /[id], new /nuevo where applicable. Canonical remaining child routes must be enumerated per portal packet; no unapproved alias. Route registry fields path, actor, permission, tenant/branch requirement, resource grant, feature flag, safe return, mobile mapping, redirect. Every deep link reauthorizes; no sensitive URL data; claim token exception scoped/scrubbed.
State registry: preserve tenant DRAFT/PENDING_VERIFICATION/ACTIVE/SUSPENDED/CLOSED; review PENDING/MORE_INFO_REQUIRED/APPROVED/REJECTED; membership INVITED/ACTIVE/SUSPENDED/REVOKED subject AT-03 reconciliation. Case UI groups Borrador/Documentación/En revisión/En trámite/Finalizado are display groups only; canonical enum/transition table AT-07 pending. Separate task, assignment, deadline, document ingestion/OCR/review/signature/official verification, payment attempt/settlement/refund, credit restriction, partner order and receipt states. Each transition actor/grant, preconditions, effects, idempotency, audit, version, reason, failure/retry; no drag filing, no OCR authenticity, no redirect settlement, no auto closure on payment. Legal review blocks dependent action only. No invented enum accepted.
Metric registry candidates: active distinct nonterminal cases excluding drafts; completed distinct case IDs with completion event in period (reopen policy pending); outstanding docs distinct active cases with required unvalidated docs; overdue distinct active cases with verified applicable overdue deadline; provisional separate. Snapshot vs period, timezone Europe/Madrid candidate subject legal calendar, scope and denominator explicit. Revenue vs collections vs fees vs receivables separate, aging buckets pending, credit available vs usable distinct. Every metric ID/formula/source/event timestamp/timezone/scope/filter/denominator/null policy/reopen policy/drilldown/test fixture. No fake zero or unauthorized aggregate.

## 9. G5 definition of ready (per bounded packet)
Required: owner-approved scope/non-goals; exact source revisions and ADRs; resolved relevant blockers; actor/permission matrix and tenant/branch/resource grants; data dictionary, constraints, state transitions, concurrency; OpenAPI request/response/error/pagination/idempotency contracts; UX states and accessibility; threat/privacy/retention and audit; dependencies verified; test vectors including negative/cross-tenant and rollback; migration/rollback strategy; explicit authorization with branch/scope. Unknowns listed and deferred features gated. G5 first AT-01/02/03 foundation only, plus minimal AT-09/17/20 contracts; no need to finalize future features. G6 execution order then separately approve F1.

## 10. Claude Code execution and definition of done
Before each packet read pinned docs and repo status, report discrepancies, no assumptions or ADR changes. Create bounded branch/PR only when authorized; list allowed paths and non-goals. Implement contracts/tests/migrations in approved order, generated clients from OpenAPI, no hand-coded duplicate API, no real secrets or production fixtures. Stop on unresolved decision, failing security test, unexpected schema change, external credential requirement or scope expansion. Report files changed, migrations, commands/test results, failures, evidence, risks, rollback and next dependency. Review diff and tests; owner acceptance distinct from merge and deployment. No automatic merge/deploy, no production access or external payment/filing. Tests: unit/domain, integration real PostgreSQL RLS (not SQLite substitute), worker/cache/storage isolation, API contract, concurrency/idempotency, E2E, accessibility/visual, dependency/secret scanning, backup/restore as applicable. Financial/professional release requires independent approval and sandbox evidence. DoD: all scoped ACs passed or explicitly approved deferral with feature disabled; no unresolved critical/high security defects; traceable audit; docs updated; reviewer signoff; rollback tested where applicable. No claimed PASS without evidence.

## 11. Release gates
Internal synthetic pilot -> approved limited commercial MVP -> credit/professional expansion -> integrations/native. Separate deployment authorization and runbook required at each live release: environment/secrets, least privilege, backup restore drill, monitoring/alerts, incident response, migration/rollback, legal/privacy terms, professional contracts, PSP reconciliation, support escalation, accessibility and asset rights. No production launch on draft specs. No fixed delivery duration until estimates based on approved packets.

## 12. Acceptance criteria
- DR-01: All20 modules mapped.
- DR-02: All9 ADRs traced.
- DR-03: All23 input designs indexed.
- DR-04: Status distinction.
- DR-05: Dependency slices avoid circularity.
- DR-06: MVP scope explicit.
- DR-07: Manual Tramisur preserved.
- DR-08: Integrated Ficha procurement.
- DR-09: Prepaid proposal not ADR amendment.
- DR-10: Credit gate separate.
- DR-11: Official API not assumed.
- DR-12: Native deferred.
- DR-13: R01–R20 tracked.
- DR-14: Route registry candidate.
- DR-15: State registry candidate.
- DR-16: Metric registry candidate.
- DR-17: AT-20 continuous.
- DR-18: Central grants before privileged actions.
- DR-19: Verification evidence scope.
- DR-20: Guest tenant routing.
- DR-21: RLS negative tests.
- DR-22: Last owner concurrency.
- DR-23: Versioned catalog.
- DR-24: Private document quarantine.
- DR-25: Verified deadlines.
- DR-26: PSP/funds flow approval.
- DR-27: Confirmed settlement only.
- DR-28: No automatic case cancellation.
- DR-29: Accessibility evidence.
- DR-30: Asset rights and raster recovery.
- DR-31: G5 readiness checklist.
- DR-32: G6 execution order gate.
- DR-33: Bounded PR scope.
- DR-34: Stop on unresolved decisions.
- DR-35: Migration rollback.
- DR-36: Generated API clients.
- DR-37: No production fixtures.
- DR-38: Independent review.
- DR-39: Separate deployment authorization.
- DR-40: No implementation in this document.

## 13. Next action
G5: prepare and approve technical foundation specifications for AT-01/02/03 with minimal AT-09/17/20 dependencies, reconcile AT-03 decisions, data model, permission matrix, OpenAPI, RLS and test vectors. G6: Claude Code execution order for first bounded packet. G0–G4 approval and G3 asset work remain open. No ADR amended.