# AutoTramita.es — Architecture Decision Register

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-technology-stack.md) | Technology stack and modular monolith | Accepted | 2026-11-23 |
| [ADR-002](ADR-002-multi-tenancy-rls.md) | Shared PostgreSQL database with tenant isolation and RLS | Accepted | 2026-11-23 |
| [ADR-003](ADR-003-identity-customer-membership.md) | Global user identity, tenant-local customers and memberships | Accepted | 2026-11-23 |
| [ADR-004](ADR-004-api-contracts.md) | API-first contracts and client generation | Accepted | 2026-11-23 |
| [ADR-005](ADR-005-document-storage.md) | Document storage and tenant isolation | Accepted | 2026-11-23 |
| [ADR-006](ADR-006-service-catalog-case-workflows.md) | Configurable service catalog and case workflows | Accepted | 2026-11-23 |
| [ADR-007](ADR-007-pricing-credit-payments.md) | Unified pricing, dealership credit and central payment collection | Accepted | 2026-11-23 |
| [ADR-008](ADR-008-delivery-governance.md) | Architecture-first, module-by-module delivery with Claude Code | Accepted | 2026-11-23 |
| [ADR-009](ADR-009-tenant-organization-membership-verification.md) | Tenant organization, memberships and verification | Accepted | 2026-11-23 |
| [ADR-010](ADR-010-identity-provider-keycloak.md) | Keycloak as identity provider | Accepted | 2026-11-24 |
| [ADR-011](ADR-011-documents-on-shared-nextcloud.md) | Document content on the shared Nextcloud | Accepted | 2026-11-24 |

| [ADR-013](ADR-013-vehicle-intelligence-engine.md) | Vehicle Intelligence Engine and verified learning | Proposed | 2026-11-27 |

## Conventions
- `Accepted` means the documented core decision has been approved. Items explicitly marked **Open decisions** remain unresolved and must not be treated as implementation instructions.
- Each ADR describes context, decision, consequences and outstanding questions.
- Accepted ADRs are not silently rewritten when decisions change; use a superseding ADR or explicit documented amendment.
- The product owner and ChatGPT define architecture and specifications; Claude Code implements approved tasks.
- The repository currently contains directory placeholders and architectural documents only; no application implementation is authorized by these ADRs.
