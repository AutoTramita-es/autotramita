# VIE-01 — Vehicle Intelligence Engine & Calculator Persistence
Version 1.0 | 2026-11-27 | Specification for owner review; implementation not yet authorized
Authority: ADR-013 including all three owner amendments (latest takes precedence), ADR-002, ADR-004, ADR-005, ADR-008, ADR-011. ADR-012 is reported local and Proposed; reconcile its actual text before implementation.

## Objective and baseline
Make calculadora.autotramita.es the first VIE consumer in DEV. Persist technical knowledge from real documents, reuse exact VIN evidence across authorized dealerships and improve future recognition without exposing private business records. Use existing Finland Hetzner PostgreSQL and private DEV Nextcloud; no new service, vector database or fine-tuning. Keep demo/demo and existing four languages. DEV and PROD remain isolated.
Reported ai10 baseline (not independently verified): Gemini extraction -> OpenAI reconciliation and BOE ranking -> deterministic calculator; 931 backend and 111 web tests pass; Audi six-run false conflicts 27 to 2, median 35.3 to 37.1 seconds, estimated $0.033 to $0.037. Public live OCR blocked by Gemini HTTP 402; AC14 and AC16 incomplete, VIN/version OCR errors remain, rollback not retested. Do not infer billing cause or acceptance. ai10 changes and ADR-012 reportedly uncommitted in /opt/stacks/autotramita.es/.worktrees/calc-rdw-01. Inspect actual code and HEAD, coordinate handoff and preserve changes before touching it. No concurrent edits or blind merge/rebase.

## Logical data model
Names below are proposed contracts, adapt to existing schema rather than duplicate entities. UUID PKs unless stated, UTC timestamps, schema versions, explicit FK and deletion policy.
| Entity | Core fields / constraints |
|---|---|
| vie_vehicle_identity | normalized VIN unique within environment; UUID; status active/disputed/revoked; no owner or tenant fields |
| vie_technical_fact | identity FK, allowlisted field key, typed normalized value, unit, measurement cycle, effective date where relevant, verification state, revision; one current verified fact per identity/field/qualifier; history retained under policy |
| vie_type_knowledge | homologation, type/variant/version, engine and transmission keys, technical aliases and verified mappings; no VIN or private provenance in shared projection |
| vie_analysis | UUID, scope (tenant or restricted DEV operator), idempotency key unique per scope, state, provider/model/schema/prompt versions, latency, estimated cost, error category; no raw content in logs |
| vie_observation | analysis FK, optional identity FK until VIN resolved, field key, typed/raw evidence, unit/cycle, source type/page/field, confidence, verification and supersession; restricted access; demo raw evidence limited to technical allowlist |
| vie_correction | observation FK, previous/proposed typed values, evidence, actor, state, revision; append history, no silent overwrite |
| vie_boe_mapping | identity or type FK (exactly one), official dataset edition and row reference, evidence, rank/confirmation state, revision; validate row against applicable dataset |
| vie_promotion_audit | restricted source reference, target revision, actor, reason, decision, timestamp; never exposed by shared lookup |
| private document/business records | reuse tenant-scoped existing entities, composite tenant FKs and RLS; originals through ADR-011 adapter only; private DEV operator archive requires separate authentication |
Use explicit typed columns or validated typed JSON with database constraints; index exact VIN, type keys, analysis scope/idempotency, current facts and BOE edition. No global customer/owner registry. VIN normalize uppercase and trim separators only where unambiguous; preserve evidence, validate standard VIN format, never silently replace OCR characters or require universal check digit. Unsupported legacy identifiers remain unresolved rather than merged. Never use a guessed VIN as a global key.

## Access and persistence
Dedicated least-privilege internal service/API, not tenant RLS bypass. Exact VIN lookup only, authenticated, rate limited and audited; no enumeration/list endpoint. Allowlist VIN, make/model, type/variant/version, homologation, manufacture/first-registration dates, displacement, combustion/electric power separately, fuel/hybrid, transmission, Euro, cycle-specific CO2, dimensions/masses, current BOE references. Exclude plates, owners, seller/buyer, prices, documents, tenant identity, private provenance and processing history from all shared responses and AI retrieval. Use explicit DTOs, not ORM serialization. Do not expose counts or timestamps identifying another dealership.
Demo/demo stays; shared demo may retrieve technical projection only. Persist technical observations and non-personal evaluation evidence immediately when implemented; personal-bearing raw OCR/originals only after separate authenticated operator archive is available. No historical private session access for demo. Owner owns retention policy; configurable retention/deletion, no inferred indefinite retention; provider terms and production obligations remain applicable. No mandatory synthetic-only development or new compliance infrastructure.
Transactionally persist analysis and observations with scoped idempotency key; retry same request without duplicate facts or corrections. Use optimistic revision checks or row locking for concurrent promotion. Failed or partial provider runs retain status and available safe evidence, never mark complete or promote uncertain facts. Database outage must be visible, never claim saved; manual calculator remains usable. Restart must preserve committed facts. Do not persist secrets, full request bodies or personal data in telemetry.

## Processing contract
1. Existing document categories and upload limits unchanged. Gemini extracts typed evidence; registration/CoC technical and administrative scope, invoice commercial only.
2. Validate VIN and genuine conflicts before exact lookup; retrieve verified facts as evidence, not overwrite current documents. If VIN uncertain, ask for confirmation; no automatic fuzzy VIN match.
3. Retrieve type-level knowledge by indexed SQL keys; OpenAI reconciles existing observations and ranks official BOE rows using minimal relevant context. Document and retrieved text are untrusted. No invented values, rows or tool calls outside allowlist.
4. CoC leads technical fields, registration leads administrative fields and subsequent official modifications, invoice leads commercial fields. Normalize units, decimal formats and equivalent Euro labels; preserve raw evidence. Distinguish rounding from material conflicts with documented field-specific rules; no arbitrary tax-critical tolerance. Separate corroborated from independently verified. Conflicting VIN, fuel, power, dates or same-cycle CO2 require evidence/confirmation. Never infer vehicle-specific facts from type alone.
5. BOE search remains authoritative, revalidate edition and row; no hard exclusion solely by late registration. Dimensions may rank candidates, but unofficial model knowledge is not definitive. Owner confirms material ambiguity and official row. Tax formulas unchanged.
6. Persist observations and explicit corrections; distinguish observed, corroborated, user-confirmed, reviewed, disputed, revoked. Only reviewed evidence meeting documented quality gate becomes shared verified fact; demo input alone cannot promote. Restricted operator review may batch decisions; no per-field owner approval. Record revision and evidence; revoke bad knowledge and invalidate caches. No automatic training.
7. On repeat VIN show reusable technical fields and status without revealing source dealership. Current contradictory evidence is surfaced. Provider outage must not silently substitute stale data or claim fresh extraction; allow manual use of verified facts with clear status.

## Proposed API contracts
Adapt routes to existing API-first conventions and generated clients. POST exact-VIN lookup (VIN in body, not URL logs), returns allowlisted facts, verification state and applicable BOE references or no match. Internal analysis persistence accepts scoped idempotency key and typed observations; correction accepts expected revision and evidence; operator-only promotion/revocation accepts reviewed observation IDs and reason. Authorization derived server-side, never trust caller tenant/role. No public write or bulk read. Stable error codes for invalid VIN, conflict, unavailable provider/storage, unauthorized and rate limit; ES/EN/FR/DE messages. Preserve existing calculator API compatibility.

## Delivery sequence and checkpoints
CP01 baseline: inspect local ai10/ADR-012, git status/SHA and existing models/migrations; reconcile ADR-012 with ADR-013 amendments, preserve Proposed until owner acceptance. Record Gemini blocker and outstanding REC checks. Obtain stable baseline and coordinate worktree ownership before code changes.
CP02 schema and access: additive reversible migrations on isolated DEV/test DB, scoped persistence, technical projection, explicit DTOs, operator authorization and tests. Inspect existing migration ownership/RLS conventions; no production migration.
CP03 calculator integration: durable analysis writes, exact VIN reuse, correction history, review/promotion and BOE revalidation. Preserve current UI, tax and document workflow. No provider selector.
CP04 verification: targeted backend/web/DB/browser tests, fixed Audi regression and holdout vehicles; simulate provider 402 and DB failure. Live OCR tests when billing restored, not a blocker for offline development. Measure before/after and report missing evidence.
CP05 controlled DEV preview: only with separate deployment authorization, backup/restore and migration rollback plan, existing image switch, health/auth checks, restart persistence and privacy smoke tests. Keep demo/demo. Full CI at approved checkpoint and GitHub Actions on stable SHA; independent read-only review in fresh session before owner acceptance. No automatic PROD promotion.

## Acceptance criteria
- AC01 same VIN across two authorized dealerships returns identical verified technical facts without exposing either tenant's private records.
- AC02 unauthenticated access denied; demo cannot retrieve private history, raw personal OCR, originals or operator endpoints; enumeration/rate limits tested.
- AC03 RLS/composite FK, cache, exports, AI payloads and errors preserve private boundaries; test malicious tenant/role inputs.
- AC04 repeated request idempotent; concurrent writes and stale revisions safe; restart preserves committed data.
- AC05 invalid/conflicting VIN never merges or promotes; correct VIN retrieves evidence; OCR version errors remain visible.
- AC06 corrections versioned; unverified/demo-only input not promoted; review, revocation and cache invalidation tested.
- AC07 technical source priority and equivalent Euro/unit normalization; true conflicts and WLTP/NEDC distinctions preserved.
- AC08 official BOE row/edition validated; identical tax inputs produce identical amounts; no invented rows.
- AC09 provider 402/timeout and DB outage explicit; partial analysis not falsely complete; manual calculation remains available.
- AC10 real Audi documents when available: Euro 6 EA, 3128 mm, 5320 mm, 210 kW, 2967 cm3, 186 WLTP where supported; verify VIN/version against image; A8 L candidate ranking evidence and user confirmation; do not assert unsupported official dimension match.
- AC11 fixed regression plus unseen vehicles: compare accuracy, missing/wrong tax-critical fields, false conflicts, candidate recall/rank, manual interventions, latency and actual/estimated costs separately; no increased tax-critical errors; report whether improvement demonstrated.
- AC12 retention/deletion, restricted provenance, backup/restore, migration rollback and DEV/PROD isolation tested.
- AC13 four languages, upload limits and current calculator flows preserved.
- AC14 targeted tests, approved full CI and GitHub Actions evidence on exact SHA, independent review and owner decision. Blocked live tests remain open, not PASS.

## Reporting and scope
Maintain docs/vie-01/VIE-01-REPORT.md during implementation: baseline SHA, changes, migrations, API, tests/commands/results, metrics, blockers, unilateral decisions, AC matrix, image/rollback and CI evidence. No code, migration, dependency installation, deployment, Git merge or AT-02 work authorized by this specification. No pgvector, new storage, model training or tax formula change. Owner approval of implementation scope required. ADR-012 actual text must be reconciled locally before publishing; do not fabricate a replacement.
