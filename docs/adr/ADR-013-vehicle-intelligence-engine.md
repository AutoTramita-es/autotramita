# ADR-013: Vehicle Intelligence Engine (VIE)

- **Status:** Accepted — owner confirmed 2026-11-27
- **Date:** 2026-11-27
- **Project:** AutoTramita.es
- **Depends on:** ADR-001, ADR-002, ADR-003, ADR-004, ADR-005, ADR-008, ADR-011
- **Related:** CALC-AI-01 and its reported proposed ADR-012 (not present in the inspected dev ADR register).

## Context

Repeated document analysis currently starts without durable vehicle knowledge. The owner wants to retain scanned information and VINs on AutoTramita-controlled EU infrastructure and improve recognition for both returning vehicles and future vehicles. The calculator preview currently has a non-persistence constraint; this decision does not lift it. The existing Gemini-to-OpenAI workflow and authoritative BOE valuation engine should be reused, not duplicated.

## Decision

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

- Owner acceptance recorded on 2026-11-27. Explicit amendment of the calculator non-persistence constraint remains pending.
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

Accepted architecture decision only. No code, migration, dependency, storage provisioning, deployment, live persistence or changes to CALC-AI-01/AT-02 are authorized. Existing accepted ADRs prevail until an explicit amendment is approved.

## Owner amendment — 2026-11-27: hosting and retention responsibility

The owner confirms that AutoTramita assumes responsibility for its data retention policy and that persistent application data, including VINs, structured OCR results, interpretations, corrections and authorized original documents, is to be hosted on its Hetzner server in Finland, using the existing PostgreSQL and ADR-011 Nextcloud architecture. The owner reports having GDPR-related hosting arrangements in place; their scope has not been independently verified. Hosting arrangements alone do not establish compliance of application processing or external AI providers.

Persistent storage is approved as a design requirement for the authenticated VIE. Do not impose blanket anonymization of authorized tenant-local operational records, synthetic-only development, a new storage service, or repeated owner approvals for routine fields within approved scope. Preserve existing RLS, authorization, audit, secure storage and tenant isolation. Shared technical knowledge remains non-personal and curated. Implement configurable retention and deletion capabilities within the existing architecture; the owner remains responsible for determining applicable retention periods, lawful purposes and provider arrangements. These policy details may be developed alongside technical design rather than blocking routine development. No indefinite retention period is inferred. Production processing must satisfy applicable obligations.

This amendment does not authorize code changes, migrations or deployment, nor persistent personal-data storage behind shared demo/demo credentials. The separate implementation package must establish authenticated access before enabling persistence. External AI processing remains subject to applicable provider terms and data protection requirements. No new compliance service or infrastructure is mandated.

## Owner amendment — 2026-11-27: shared VIN technical lookup

Accepted by owner. Supersedes the earlier same-tenant-only VIN lookup restriction and the prohibition on cross-tenant VIN existence inference insofar as an authorized global technical lookup necessarily returns a technical match. Tenant-local vehicle, customer, ownership, case and document records remain protected by ADR-002. The shared type-level knowledge base remains separate from a new logical global VIN-indexed technical projection.

Authenticated authorized dealerships may submit an exact VIN and retrieve previously verified technical facts about that specific vehicle regardless of which dealership originally processed it. Allowlisted fields include VIN, make, model, type/variant/version, homologation, manufacture and first-registration dates, engine displacement and power, fuel/hybrid type, transmission, Euro standard, cycle-specific CO2, dimensions, masses and BOE classification references (revalidated for the applicable edition). Distinguish stable facts from mutable or disputed observations; current evidence prevails where appropriate. No automatic identity merge on conflicting VINs.

The shared response must never expose current or previous owner, customer, seller or buyer identities, contact details, tax identifiers, registration plates, originating dealership, tenant IDs, purchase prices, invoices, contracts, original documents, raw OCR, private provenance links, case history, or processing history identifying another dealership. No indirect disclosure through errors, counts, timestamps, metadata, search indexes, cache, AI context or exports. Restricted provenance and promotion audit remain separately authorized. Global technical lookup is exact-VIN only, authenticated, rate-limited and audited; no bulk VIN enumeration or public lookup. VIN-linked technical records may themselves be personal data and remain subject to the owner retention and lawful-processing policy.

Implement the shared projection through a dedicated least-privilege service/API contract with explicit field allowlist, not by bypassing tenant RLS or granting access to other tenants' vehicle tables. Verified technical observations may be promoted to this projection through the existing quality gate. Tenant-local business records remain independent even when linked to the same global technical identity. Deletion/correction and provenance lifecycle must account for the shared projection without exposing another tenant's records.

Future acceptance tests replace the earlier blanket cross-tenant VIN existence test: dealership A processes a vehicle; dealership B submits the same VIN and receives only allowlisted verified technical data; B cannot discover A, its owners, documents, prices, cases or private provenance through any API, search, cache, AI or export path. Unauthorized callers cannot access the projection. Conflicting VIN evidence, stale observations, revocation and rate limits are tested. This amendment authorizes architecture only, not implementation or deployment.
