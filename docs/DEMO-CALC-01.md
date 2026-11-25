# AutoTramita.es — DEMO-CALC-01 — Vehicle Registration Calculator

## 0. Controlling revision — owner approval, 2026-11-25

This revision supersedes the original brief and the earlier architecture decision wherever they conflict. The reported preflight is not independently verified; preserve its scratchpad report in the feature worktree. Review accepted ADRs and AT-05/BOE-01/AC12 before coding.

Owner approves feature/demo-calc-01, worktree /opt/stacks/autotramita.es-worktrees/demo-calc-01, and isolated database autotramita_calc_dev on the existing PostgreSQL service. BOE-01 and only the AT-05 model subset required for this demo are approved for development; no general AT-05 acceptance or production authorization. Use Next.js under ADR-001. Preserve passenger and commercial vehicle scope, both reference calculations and PDF. No public tax estimates before gestor validation and AC12. Unvalidated fiscal calculations and PDFs are permitted only in a controlled, access-restricted demonstration, explicitly marked as unvalidated simulations, not tax advice. Enforce this restriction server-side, including API and PDF endpoints; a disclaimer alone is insufficient. If existing ADRs prohibit even controlled simulations, stop that portion and report the conflict; do not silently override accepted ADRs.

Deployment is a separate owner approval gate after review of image, Compose, Traefik, Cloudflare ingress, access protection, rollback and resource impact. No live routing, DNS, shared configuration or production changes until approved. Coordinate migration numbering and importer least-privilege role with F2-T10; no concurrent migrations or changes to existing application databases. Use an isolated development migration plan; do not assume migration 0011 is available. No merge or push of implementation without separate authorization. Documentation save on dev is owner-authorized. Preserve all acceptance criteria; blocked deployment or legal validation must be reported honestly.

## 1. Owner authorization and priority

The owner authorizes implementation of the integrated AutoTramita.es vehicle registration calculator. Demonstration deployment requires separate approval under section 0.

Target demonstration date: 2026-11-26.

Target URL:

https://calculadora.autotramita.es

The objective is to deliver a functional Spanish-language calculator using real official BOE vehicle valuation data and applicable Spanish tax rules.

This is a high-priority demonstration deliverable.

Do not wait for completion of AT-02 or F2.

Do not interrupt, modify or interfere with ongoing F2-T10-REC implementation.

The owner explicitly requires ONE calculator, ONE user interface and ONE calculation engine.

Do not create separate Gestoría and AutoTramita calculation modes.

The existing gestoría calculations are reference test cases, not separate business logic.

## 2. Isolation and working environment

Existing main project:

- Repository: `AutoTramita-es/autotramita`
- Working directory: `/opt/stacks/autotramita.es`
- Branch: `dev`

Approved feature worktree: `/opt/stacks/autotramita.es-worktrees/demo-calc-01`, branch `feature/demo-calc-01`, in the same repository. Inspect current Git status, HEAD, ADRs, available resources, ports, Compose, routing and TLS before creating it. Do not touch the active F2-T10-REC working tree. Use the existing Docker stack and PostgreSQL service, with isolated database `autotramita_calc_dev` and least-privilege roles. Coordinate migrations and shared configuration; do not modify existing application databases, active Keycloak realms or live infrastructure. No separate stack or remote repository. Keep all source in the same repository and do not merge or push implementation without separate approval.

## 3. Technology

Prefer compatibility with the existing AutoTramita technology stack.

Recommended implementation:

- Python 3.12.
- FastAPI.
- SQLAlchemy 2.x.
- psycopg 3.
- PostgreSQL.
- uv.
- Docker Compose.
- Responsive Spanish-language Next.js frontend according to ADR-001.
- Server-side authoritative calculation engine.
- PDF generation.

Use the existing AutoTramita visual design system where available.

Use the existing approved Next.js architecture and avoid unrelated frontend scope.

Keep the calculation engine independent of the web framework and persistence layer.

Do not implement authentication, tenant management, payments, document management or unrelated SaaS features.

## 4. Official BOE integration

Official API documentation:

https://www.boe.es/datosabiertos/api/api.php

Reference regulation for 2026:

https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-26357

Expected regulation:

Orden HAC/1501/2025.

Verify the regulation identifier, publication date, effective date, applicable annexes and any subsequent corrections or amendments directly against official sources.

Implement a BOE data importer that:

- Uses documented official BOE API endpoints to discover relevant publications.
- Retrieves the authoritative document and applicable annexes.
- Imports the complete applicable 2026 vehicle valuation catalogue.
- Imports official age-based depreciation percentages.
- Preserves the original source document.
- Records source URL, BOE identifier, publication date, effective dates and document checksum.
- Supports repeatable and idempotent imports.
- Detects updated or corrected official documents.
- Validates parsed records before activating a dataset.
- Preserves previous dataset versions.
- Reports malformed, incomplete or ambiguous records.

Do not invent a BOE vehicle search endpoint.

If the API provides publication metadata but the valuation tables are available only through official PDF or other document formats, implement the necessary document retrieval and parsing.

Use the official source format that provides the most reliable complete extraction.

Do not silently discard unparsed vehicle records.

A partial catalogue must be clearly identified as incomplete and must not be reported as a complete successful import.

## 5. Vehicle catalogue

Store all relevant official catalogue fields, including where available:

- Manufacturer.
- Model.
- Commercial variant.
- Commercial production period.
- Engine displacement.
- Cylinder count.
- Fuel or engine type.
- Power in kW.
- Power in CV.
- Fiscal horsepower.
- Official valuation in EUR.
- Applicable valuation year.
- Source document identifier.
- Source page or table reference.
- Original source row.

Implement efficient indexed searches and filters.

Support:

- Manufacturer selection.
- Model selection.
- Variant selection.
- Engine displacement filtering.
- Fuel filtering.
- Power filtering.
- Commercial period filtering.

Normalize search terms without altering original official source values.

Support vehicles registered after the commercial period of a candidate catalogue entry, but display a warning rather than silently rejecting or accepting the match.

Do not automatically select an ambiguous vehicle variant.

Allow the operator to select the correct official row.

## 6. Calculator input fields

Create one Spanish-language calculator interface.

### Vehicle identification

- Marca.
- Modelo.
- Versión.
- Fecha de primera matriculación.
- Fecha de cálculo.
- País de procedencia.
- País de compra.
- Categoría del vehículo.
- Tipo de carrocería.
- Combustible.
- Cilindrada.
- Potencia kW/CV.
- Potencia fiscal.
- Emisiones CO₂.
- Número de plazas.
- Masa máxima autorizada.
- Norma Euro.
- Kilometraje.

VIN and registration number may be optional inputs if useful, but must not be required for a calculation.

### Transaction and registration

- Precio de compra.
- Tipo de vendedor.
- Tipo de comprador.
- Tratamiento fiscal de la compraventa.
- Comunidad autónoma.
- Provincia.
- Municipio de matriculación.
- Uso particular or professional/business use.
- Relevant evidence for tax non-subjection, exemption or reduction.

### Calculation parameters

- Official BOE valuation.
- Age-based valuation percentage.
- Market valuation.
- Historical indirect-tax adjustment.
- Adjustment coefficient.
- Applicable IEDMT rate.
- Taxable base.
- Applicable tax treatment.
- Configurable registration and service charges.

Automatically derive parameters where authoritative rules and sufficient input data are available.

Allow manual overrides in the same calculator.

Manual overrides must:

- Be explicitly visible.
- Preserve the automatically proposed value.
- Require a reason.
- Be included in the calculation breakdown.
- Never silently replace the authoritative source data.

## 7. Calculation engine

Implement one reusable calculation engine.

Use Decimal arithmetic for financial calculations.

Do not use binary floating-point arithmetic for monetary amounts.

Define explicit rounding rules and test monetary boundary cases.

### Vehicle age

Calculate vehicle age using:

- First registration date.
- Calculation date.
- Exact anniversary boundaries.
- Applicable official depreciation table.

Reference depreciation percentages:

| Vehicle age | Remaining value |
|---|---:|
| Up to 1 year | 100% |
| Over 1 up to 2 years | 84% |
| Over 2 up to 3 years | 67% |
| Over 3 up to 4 years | 56% |
| Over 4 up to 5 years | 47% |
| Over 5 up to 6 years | 39% |
| Over 6 up to 7 years | 34% |
| Over 7 up to 8 years | 28% |
| Over 8 up to 9 years | 24% |
| Over 9 up to 10 years | 19% |
| Over 10 up to 11 years | 17% |
| Over 11 up to 12 years | 13% |
| Over 12 years | 10% |

Verify these percentages against the applicable official regulation before activation.

### Market valuation

Market valuation = official BOE valuation × applicable remaining-value percentage.

### Historical indirect-tax adjustment

Implement the applicable official rules for adjustment of the taxable base of previously registered imported vehicles.

Verify Article 5 of Orden HAC/1501/2025 and related legislation.

Do not hardcode 1.25 as a universal adjustment coefficient.

Derive the coefficient from the applicable historical tax rules when sufficient verified information is available.

Allow an explicit manual coefficient override for reference calculations.

### IEDMT

Implement applicable registration-tax rules using authoritative legal sources.

Consider:

- Vehicle category.
- CO₂ emissions.
- Relevant territorial tax rates.
- Vehicle characteristics.
- Applicable non-subjection.
- Exemptions.
- Reductions.
- Business-use requirements.
- Required supporting evidence.

Distinguish:

- No tax liability.
- Tax exemption.
- Zero tax rate.
- Positive tax liability.
- Insufficient information to determine tax liability.

These are not interchangeable statuses.

Do not assume that all N1 vehicles are automatically exempt.

Do not apply passenger-car CO₂ tax rates to every vehicle category without verifying the applicable legal classification.

### Other taxes and charges

Support applicable:

- ITP.
- IVA.
- IVTM.
- DGT charges.
- ITV charges.
- Ficha reducida.
- Registration plates.
- Administrative service charges.
- Other configurable charges.

Avoid double counting.

Separate statutory taxes, third-party charges and AutoTramita service fees.

For the demonstration, unverified third-party charges may be manually configured and clearly marked as estimates.

Do not present unknown amounts as zero.

Do not claim complete nationwide automatic tax coverage unless the relevant territorial rules and source data have actually been implemented and verified.

Prioritize mainland Spain and Andalusia for the initial demonstration.

## 8. Mandatory reference case — FIAT Fiorino

The owner provided two real gestoría calculations and vehicle documentation.

Use the following extracted reference data.

### Gestoría-selected BOE catalogue row

- Manufacturer: FIAT.
- Model: FIORINO Combi 1,3Mjt Adventure.
- Commercial period: 2016–2019.
- Displacement: 1248 cc.
- Cylinders: 4.
- Fuel: Diesel.
- Power: 59 kW.
- Power: 80 CV.
- Fiscal horsepower: 10.04 CVF.
- Official valuation for 2026: EUR 16,300.00.
- BOE reference: BOE-A-2025-26357.
- Printed BOE page: 171990.

Verify this exact row against the imported official catalogue.

### Reference calculation A

Inputs:

- BOE valuation: 16300.00 EUR.
- Remaining value percentage: 34%.
- Historical tax adjustment: disabled.
- IEDMT rate: 4.75%.
- FTR: 89.54 EUR.
- PV: 150.00 EUR.
- Matriculación: 480.00 EUR.

Expected results:

- Market valuation: 5542.00 EUR.
- Taxable base: 5542.00 EUR.
- IEDMT: 263.24 EUR.
- Other charges: 719.54 EUR.
- TOTAL: 982.78 EUR.

### Reference calculation B

Use the same inputs, with:

- Historical tax adjustment: enabled.
- Adjustment coefficient: 1.25.

Expected results:

- Market valuation: 5542.00 EUR.
- Taxable base: 4433.60 EUR.
- IEDMT: 210.59 EUR.
- Other charges: 719.54 EUR.
- TOTAL: 930.13 EUR.

Both reference calculations must use the same production calculation engine and the same user interface.

Do not implement special-case formulas for this vehicle.

Do not hardcode the expected totals into application behavior.

Treat the labels FTR and PV as unverified charge descriptions until their meaning is confirmed.

Do not invent their legal or commercial meaning.

## 9. Mandatory independent calculation from vehicle documents

The same calculator must support calculation using the actual vehicle documentation rather than blindly reproducing the gestoría's assumptions.

Actual vehicle data extracted from the supplied documents:

- Manufacturer: FIAT.
- Model: FIORINO.
- Engine: 1.3 JTD Multijet.
- First registration: 2020-09-18.
- Mileage: 53000 km.
- Engine displacement: 1248 cc.
- Power: 59 kW.
- Fuel: Diesel.
- CO₂: 137 g/km.
- Euro standard: Euro 6.
- Category: N1.
- French national classification: CTTE.
- EU bodywork code: BB.
- Bodywork description: FOURGON.
- Seats: 2.
- Maximum authorized mass: 1820 kg.
- Type/variant/version: 225BXL1AD6.
- CNIT: N10FATCT1923171.
- EU type approval: e3*2007/46*0011*28.
- Country of purchase: France.
- Registration destination: Estepona, Málaga, Spain.
- Seller: professional vehicle dealer.
- Invoice date: 2026-09-11.
- Net purchase price: 4166.67 EUR.
- French VAT shown on invoice: 833.33 EUR.
- Total purchase price: 5000.00 EUR.

Do not include actual buyer names, addresses, VINs, registration numbers, signatures or other unnecessary personal identifiers in public demo data, fixtures or logs.

Use a fixed calculation date of 2026-11-25 for the reference age test.

Expected remaining-value percentage on that date: 34%.

Investigate:

- Whether the gestoría-selected Combi Adventure catalogue row is the correct valuation reference for the actual N1 FOURGON.
- Whether another official catalogue row provides a more accurate match.
- Whether the vehicle qualifies for IEDMT non-subjection or another applicable tax treatment.
- Whether the historical adjustment coefficient of 1.25 is legally applicable.
- Whether the transaction requires additional tax treatment in Spain.
- Whether the applicable municipal IVTM can be established from official Estepona rules.

Do not infer the buyer's business-use status from the N1 classification alone.

Where required facts are missing, display a clear request for the missing information.

If no exact official catalogue match can be established, provide candidate rows and require operator confirmation.

Do not silently substitute the closest model.

The owner expects the same calculator to reproduce the gestoría results when the same parameters are supplied and to produce a legally supported calculation when verified actual vehicle data is supplied.

The correct independent result must not be forced to equal either gestoría total.

## 10. User interface

Create a professional, responsive Spanish-language interface.

Use AutoTramita.es branding and existing approved visual assets where available.

Suggested page title:

Calculadora de matriculación de vehículos

Suggested interface sections:

1. Datos del vehículo.
2. Selección del vehículo en tablas BOE.
3. Datos de compra y matriculación.
4. Cálculo fiscal.
5. Gastos y honorarios.
6. Presupuesto estimado.

Provide:

- Searchable manufacturer and model selectors.
- Technical filtering.
- Clear selected BOE source row.
- Automatic age calculation.
- Editable calculation parameters.
- Visible warnings for manual overrides.
- Clear validation errors.
- Detailed calculation breakdown.
- Source references.
- Prominent total estimated cost.
- Mobile-friendly layout.
- Reset calculation action.
- Recalculate action.
- PDF export.

The user must be able to reproduce both reference calculations without navigating to another calculator or selecting a special Gestoría mode.

Provide an optional button to load the anonymized Fiat Fiorino demonstration inputs.

Do not expose internal implementation terminology unnecessarily.

## 11. PDF quotation

Generate a professional Spanish-language PDF containing:

- AutoTramita.es branding.
- Calculation date.
- Vehicle identification and technical characteristics.
- Selected official BOE catalogue entry.
- Official valuation year and source.
- Age-based percentage.
- Market valuation.
- Tax adjustment and taxable base.
- Applied tax rates and treatment.
- Itemized taxes and charges.
- Service fees.
- Total estimated amount.
- Relevant warnings and missing information.
- Manual overrides and their reasons.
- Legal and official source references.

Clearly label the document:

Presupuesto estimado — sujeto a verificación fiscal y documental.

Do not present the PDF as an official tax assessment or invoice.

## 12. Data updates and traceability

Provide a documented command to import or refresh BOE data.

Maintain versioned source datasets.

Existing calculations must remain reproducible using the original source version.

Do not silently recalculate historical quotations using a newly imported catalogue.

Implement a safe, bounded update-check mechanism.

Do not automatically activate a newly parsed dataset until validation succeeds.

Do not require a live BOE API request for every user calculation.

The calculator must remain functional with the last successfully validated local dataset if BOE is temporarily unavailable.

Display the active valuation year and dataset status.

## 13. Demonstration deployment

The target for a separately authorized controlled demonstration deployment is:

https://calculadora.autotramita.es

Prepare additive deployment configuration for the existing Docker Compose project; do not apply it before separate owner approval.

Requirements:

- HTTPS with a valid certificate.
- Dedicated application container.
- Isolated calculator database on the existing PostgreSQL service; no new PostgreSQL container.
- No publicly exposed database port.
- No conflicting host ports.
- Non-root application execution where supported.
- Secure secret handling.
- Resource limits appropriate to the available server capacity.
- Health checks.
- Restart policy.
- Bounded request sizes and execution times.
- Rate limiting.
- Safe error responses.
- No public administrative endpoints.
- No exposed BOE importer or dataset-management controls.
- No debug mode.
- No unnecessary retention of visitor data.
- No real customer document uploads in the demonstration.

Prefer existing approved reverse proxy and certificate management mechanisms.

Only make additive routing changes required for the new calculator hostname.

Do not replace or disrupt existing reverse proxy routes, DNS records or certificates.

Do not restart unrelated services.

The controlled demonstration should be accessible through a normal browser using approved access protection, without requiring SaaS account registration.

Access protection is mandatory for unvalidated fiscal calculations and must cover UI, API and PDF endpoints. Use the simplest approved existing mechanism and provide access instructions securely.

Do not introduce a new identity system.

If DNS or reverse proxy permissions are unavailable, report the exact blocker and required action.

Do not claim that the target URL is operational until it has been verified through an actual HTTPS request.

## 14. Testing and acceptance criteria

Additionally verify server-side access restrictions for unvalidated tax calculations and PDFs, least-privilege database roles, and the separate deployment and AC12 gates. A blocked gate is not a PASS.

Use focused tests for this isolated calculator.

Mandatory acceptance criteria:

- CALC-AC01: Official BOE 2026 source verified.
- CALC-AC02: Complete applicable vehicle catalogue imported and validated.
- CALC-AC03: Import is repeatable and idempotent.
- CALC-AC04: Fiat Fiorino reference row is searchable.
- CALC-AC05: Vehicle age percentages and anniversary boundaries are correct.
- CALC-AC06: Reference calculation A returns exactly EUR 982.78.
- CALC-AC07: Reference calculation B returns exactly EUR 930.13.
- CALC-AC08: Both calculations use the same calculation engine.
- CALC-AC09: Actual N1 vehicle data can be entered and evaluated independently.
- CALC-AC10: Unverified tax assumptions and ambiguous vehicle matches are clearly identified.
- CALC-AC11: Manual overrides are visible and traceable.
- CALC-AC12: PDF export reproduces the displayed calculation.
- CALC-AC13: The interface works on desktop and mobile.
- CALC-AC14: The calculator is accessible through the authorized HTTPS hostname.
- CALC-AC15: No interference with ongoing AT-02 development or existing infrastructure.
- CALC-AC16: No real customer personal data is exposed through the demonstration.
- CALC-AC17: Calculator source and deployment instructions are documented.
- CALC-AC18: Invalid inputs, negative amounts, missing required values and unsupported tax scenarios are handled safely.

Test the actual deployed application, not only the calculation functions.

Do not repeat the main AutoTramita FULL CI during isolated development; required GitHub Actions gates remain mandatory for later integration.

Run the calculator's own targeted test suite and deployment smoke tests.

Record all test results.

## 15. Execution priorities

Prioritize the working demonstration in this order:

1. Official BOE retrieval and catalogue import.
2. Calculation engine and exact reference tests.
3. Vehicle search and calculator interface.
4. Actual vehicle tax-rule validation.
5. PDF quotation.
6. Isolated HTTPS deployment.
7. Final smoke tests and documentation.

Complete routine technical decisions autonomously.

Do not request owner approval for every intermediate step.

If the complete catalogue import encounters a technical problem, continue developing and testing the calculation engine using verified official reference rows while resolving the importer.

Do not misrepresent temporary reference data as a complete catalogue.

If a legal rule cannot be verified, expose the uncertainty rather than inventing a rule.

Do not delay the entire demonstration for optional features outside the authorized scope.

## 16. Prohibited operations

- Modifying the active working tree at `/opt/stacks/autotramita.es` during concurrent development.
- Interrupting F2-T10-REC.
- Modifying the active F2-T10-REC working tree.
- Modifying existing application databases.
- Modifying active Keycloak realms.
- Changing existing SaaS security policies.
- Starting T11, T12 or T13.
- Implementing unrelated SaaS modules.
- Creating competing calculation engines.
- Creating a separate Gestoría calculator.
- Hardcoding expected reference totals.
- Inventing official BOE records or tax rules.
- Publishing real customer documents or personal information.
- Exposing PostgreSQL publicly.
- Changing unrelated DNS records.
- Disabling existing infrastructure security controls.
- Pushing implementation into the main repository without separate authorization.
- Merging or force pushing.
- Creating a new remote repository without authorization.

## 17. Final deliverables

Deliver:

- Functional calculator application.
- Official BOE importer.
- Validated local vehicle catalogue.
- Reusable calculation engine.
- Spanish-language responsive interface.
- PDF quotation generation.
- Automated reference tests.
- Additive deployment configuration for the existing Docker Compose stack, pending approval.
- Deployment and maintenance documentation.
- Working HTTPS demonstration URL.

Save the technical completion report in:

`docs/DEMO-CALC-01-REPORT.md`

Provide the owner-facing summary in Croatian.

Include:

- Actual working URL.
- Deployment status.
- Official BOE sources.
- Imported record count and validation results.
- Active dataset version.
- Both Fiat Fiorino reference results.
- Independent calculation using actual vehicle data.
- Missing information and unresolved tax questions.
- Test results.
- Acceptance criteria matrix.
- PDF export verification.
- Security and isolation verification.
- Significant autonomous decisions.
- Remaining limitations.
- Confirmation that AT-02 was not interrupted.
- Instructions for updating BOE data.
- Recommendations for later integration into the main AutoTramita SaaS.

Return one final status:

**DEMO-CALC-01 — DEPLOYED / READY FOR DEMONSTRATION**

or

**DEMO-CALC-01 — PARTIALLY COMPLETED / BLOCKERS REMAIN**

or

**DEMO-CALC-01 — BLOCKED / OWNER ACTION REQUIRED**

Do not claim completion if mandatory acceptance criteria remain unmet.

Stop after delivering the report.