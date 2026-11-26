# AutoTramita — DGT representation and shared logistics concept

Date: 2026-11-26
Status: IDEA / DISCOVERY ONLY — not an approved implementation specification or ADR.

## Business objective
Serve dealerships and vehicle importers across Spain through a centralized platform. Minimize outsourced administrative work while respecting professional licensing and representation rules.

## DGT and representation
- Prefer approved direct DGT API integration, then electronic submission under valid authority, then physical attendance where legally permitted.
- Use Tramitasur only for procedures requiring professional intervention or unavailable channels. Tramitasur has no API according to the owner; initial exchange is by email, with appropriate privacy and security controls.
- One central integration operated by AutoTramita, not separate API accounts for dealerships.
- Standardized reusable mandate to the same authorized representative, separately granted by each dealership. Verify scope, expiry, revocation, electronic acceptance and authority for each vehicle. A dealership cannot automatically authorize representation of a separate vehicle owner.
- Investigate green temporary registrations (placas verdes) first, then permanent registration, ownership transfers, deregistration, reports, duplicates and other DGT services.
- DGT issues permits; physical plates are manufactured separately. Investigate electronic permit delivery, postal delivery to dealerships and collection requirements for imported vehicles.
- No confirmed direct API access or authorization for paid professional representation by an ordinary S.L. Do not assume either from a general power of attorney.

## Staffing and operations
Initially outsource reserved work to Tramitasur. When volume justifies it, recruit a suitably qualified administrative employee in Málaga, support their path to Gestor Administrativo qualification and professional registration, then progressively internalize permitted work. Prefer remote work near the provincial traffic office for necessary collection and physical errands. Verify professional office, employment, telework, data security and company structure requirements. Keep Tramitasur as a potential fallback. Never share personal professional credentials or bypass authorization.

## Shared Logistics Gateway
Apply to every business module, not only placas verdes.
- Integrate InPost España, Correos Citypaq and SEUR Pickup through central AutoTramita business accounts, subject to provider approval.
- Parcel lockers are the primary delivery channel; address delivery is an optional fallback proposal.
- Dealership chooses its preferred operator and locker on a unified map; save defaults per dealership/branch and allow per-order overrides.
- Bidirectional shipments: plates, permits, technical sheets and other original documents to dealerships; original registration documents, COC and mandates back to AutoTramita when needed.
- Central shipment creation, label generation, tracking, notifications, returns and provider adapters. Use webhooks where supported.
- Málaga employee can collect permits if required, obtain plates from an authorized manufacturer, pack shipments and deposit them at the chosen carrier's permitted drop-off point. Prefer direct fulfillment to dealerships where possible.
- Verify package dimensions (target 55–60 cm length, 1–2 kg), locker-to-locker availability, coverage, B2B tariffs, original-document restrictions, insurance, proof of delivery and loss handling for each provider.
- Protect originals and personal data with secure storage, chain of custody, access controls and audit records.
- Proposed pricing options: actual carrier price, unified locker price, or shipping included in selected services. Unified pricing was recommended but not approved.

## Open discovery questions
1. DGT API eligibility, supported procedures, sandbox, credentials and central access.
2. Legal limits of paid representation without a licensed gestor; ordinary S.L. employing a gestor versus professional company requirements.
3. REA reusable mandates and authority for future vehicles; foreign owners and electronic signatures.
4. Delivery/collection of imported-vehicle temporary permits, permitted delivery addresses and nationwide centralized submission.
5. Professional qualification routes and remote office requirements in Málaga.
6. Carrier APIs, contracts, actual locker dimensions and acceptance of plates and original documents.
7. Plate manufacturing partners near DGT or direct fulfillment.

## Reference starting points (not independently verified in this note)
- https://sede.dgt.gob.es/
- https://www.dgt.es/
- https://www.boe.es/buscar/act.php?id=BOE-A-2015-10565#a5
- https://www.boe.es/diario_boe/txt.php?id=BOE-A-2024-11657
- https://www.juntadeandalucia.es/boja/2012/147/26
- https://www.inpost.es/
- https://www.correos.es/
- https://www.seur.com/

## Scope boundary
Preserve this concept for future planning. No implementation, deployment, infrastructure changes, acceptance decision, or modification of existing development phases is authorized by this note.
