# ADR-013: Vehicle Intelligence Engine (VIE)

- **Status:** Proposed — owner review required
- **Date:** 2026-11-27
- **Project:** AutoTramita.es
- **Depends on:** ADR-001, ADR-002, ADR-003, ADR-004, ADR-005, ADR-008, ADR-011
- **Related:** CALC-AI-01 and its reported proposed ADR-012 (not present in the inspected dev ADR register).

## Context

Repeated document analysis currently starts without durable vehicle knowledge. The owner wants to retain scanned information and VINs on AutoTramita-controlled EU infrastructure and improve recognition for both returning vehicles and future vehicles. The calculator preview currently has a non-persistence constraint; this proposal does not lift it. The existing Gemini-to-OpenAI workflow and authoritative BOE valuation engine should be reused, not duplicated.

## Proposed decision

Create a shared logical Vehicle Intelligence Engine within the existing modular monolith and PostgreSQL architecture. No separate service or database is required by this decision. Provide authorized internal contracts to the calculator, vehicle registry, registration cases, Ficha Reducida and other business modules. Gemini reads and classifies documents; OpenAI interprets structured evidence, reconciles fields and ranks authoritative BOE candidates. Tax calculations remain deterministic.

### Data boundaries and conceptual model

- Tenant vehicle registry: tenant_id, internal vehicle UUID, normalized VIN, original VIN evidence, technical observations and registration history. VIN is not a public identifier. Tenant-local uniqueness and identity resolution must accommodate erroneous or disputed VINs; never merge conflicting identities automatically.
- Tenant document registry: document UUID, tenant and case/vehicle references, type, SHA-256, version, page references, scan status and retention. Original files, if retention is authorized, live in private Nextcloud through the ADR-011 adapter, not a new object store. Deduplication is tenant-scoped and must not reveal another tenant's files.
- Tenant extraction runs: document and model versions, schema/prompt versions, structured OCR and interpretation, confidence, timing and estimated cost. Raw text and original files may contain personal data; retain only for approved purposes and periods.
- Tenant field observations: raw and normalized values, units, measurement cycle, document/page/field provenance, observation date, verification status and supersession history. Separate manufacture, first registration and subsequent modifications; preserve WLTP/NEDC and combustion/electric power distinctions.
- Tenant feedback: proposed correction, previous value, evidence, reviewer identity, verification status and audit trail. A user correction is not automatically a globally trusted fact.
- Global technical knowledge: separately authorized, curated, non-personal vehicle type/variant/version, homologation, engine, transmission, dimensions, regulatory classifications, document field mappings and aliases. No VIN, registration, buyer/seller identifiers, prices paid, tenant references, raw OCR or source document links in shared retrieval projections. Rare combinations and free text require reidentification review before publication.
- BOE mapping knowledge: candidate official row identifiers, dataset edition/year, effective period, matching evidence, review status and version. Never treat a prior valuation as current; revalidate against the applicable authoritative dataset.
- Customer, owner, seller and transaction information remain in their existing tenant-scoped business domains. No new global customer registry.

All tenant tables and references follow ADR-002 RLS and composite tenant keys. Global knowledge has a distinct least-privilege read/write authorization path; promotion is a controlled audited operation, not a bypass of tenant RLS.

### Retrieval and improvement loop

1. Authorize the tenant and document operation; validate and scan uploads per ADR-011.
2. Extract and validate VIN and document fields. Look up the same VIN only within authorized tenant scope. Reuse confirmed stable observations as evidence, not as a substitute for current documents.
3. Retrieve technical knowledge using exact indexed SQL keys (homologation, type, variant, version, engine); broaden only with explicit evidence. Optional pgvector semantic retrieval for sanitized aliases and mappings requires separate dependency approval and measured benefit.
4. Supply relevant minimal evidence to OpenAI; preserve source provenance, field-level priority and genuine conflict handling. Retrieved data and document text are untrusted, not instructions.
5. Search authoritative BOE rows using controlled read-only tools; rank candidates and require confirmation where material ambiguity remains. Never invent rows or change vehicle facts to force a match.
6. Record observations and corrections only when persistence is authorized. Promote verified, non-personal technical knowledge through a review gate with evidence quality, conflict checks, versioning and rollback.
7. Evaluate new knowledge against a fixed regression corpus and holdout vehicles before promotion; measure extraction accuracy, tax-critical errors/missing values, candidate recall/rank, false conflicts, manual interventions, latency and cost. Quarantine regressions and revoke bad knowledge.

This is retrieval-augmented generation and controlled feedback, not automatic model training. No fine-tuning, provider training upload or autonomous global learning from unverified user input is authorized. Same-type evidence cannot establish vehicle-specific CO2, mileage, registration dates or condition without corroboration. New evidence may supersede old observations without destroying audit history.

## Security and privacy

VIN and document contents may be personal data. EU hosting alone does not establish GDPR compliance. Define controller/processor roles, lawful bases and purpose limitation separately for case processing, retention and knowledge improvement. Review provider DPAs, transfers, retention, training settings and applicable safeguards before live persistent processing. Use minimal provider payloads; avoid sending commercial identities to interpretation where unnecessary. Protect VIN and documents with access control, encryption in transit/at rest and approved key management; no raw identifiers or document content in logs. Cache, search, background jobs, backups and exports must preserve tenant isolation. No cross-tenant VIN lookup or existence oracle. Define deletion, correction, access/export, legal hold, backup expiry and derived-data removal procedures. Shared knowledge must not expose tenant/customer provenance; restricted promotion audit records remain separately protected. Demo/demo preview must not become a persistent personal-data store.

## Alternatives

- Stateless processing: simplest and current preview baseline; loses reuse and feedback.
- Global raw VIN/document corpus: rejected because it conflicts with tenant isolation and minimization.
- Controlled structured knowledge and retrieval: preferred; auditable, incremental, reversible.
- Fine-tuning or vector-first architecture: deferred until evidence justifies complexity.

## Consequences

Potentially fewer manual interventions and repeated API calls, improved BOE candidate recall and consistency; benefits must be measured, not assumed. Adds retention, review, data quality, security and lifecycle obligations. Existing ADR-011 Nextcloud decision supersedes earlier S3 proposals; no new storage provider is selected.

## Open decisions and implementation gates

- Owner acceptance of this ADR and explicit amendment of the calculator non-persistence constraint.
- Approved retention matrix, lawful bases, provider terms, EU infrastructure and security/privacy review.
- Exact schema, API contracts, VIN normalization/indexing, promotion authority and evidence thresholds.
- Whether raw OCR and original files are necessary for each purpose; default to minimization.
- Whether pgvector is justified; no installation authorized.
- Integration sequencing with vehicle and customer modules, and reconciliation with ADR-012 once available.
- Separate implementation package with migrations, rollback, tests and CI authorization.

## Acceptance criteria for future implementation

- Same-tenant repeat VIN retrieves verified evidence; different tenants cannot infer VIN existence or access records, files, caches or search results.
- Conflicting VINs and tax-critical facts remain unresolved until supported; source priority cannot conceal contradictions.
- Shared technical projections contain no personal or tenant-identifying data; promotion is reviewed, audited, versioned and reversible.
- BOE rows and values are revalidated for the applicable edition; deterministic tax results remain unchanged for identical inputs.
- Deletion/retention, access/export, backup restore and provider failure paths are tested.
- Regression and holdout evaluation demonstrates improvement without increased tax-critical errors; report actual latency/cost and limitations.
- Targeted tests, full CI at approved checkpoint, independent security review on stable SHA and owner acceptance are required.

## Scope

Architecture proposal only. No code, migration, dependency, storage provisioning, deployment, live persistence or changes to CALC-AI-01/AT-02 are authorized. Existing accepted ADRs prevail until an explicit amendment is approved.
