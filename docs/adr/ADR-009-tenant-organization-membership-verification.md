# ADR-009: Tenant organization, memberships and verification

- **Status:** Accepted
- **Date:** 2026-11-23
- **Project:** AutoTramita.es
- **Depends on:** ADR-002, ADR-003, ADR-007, ADR-008

## Context
AutoTramita.es serves Spanish vehicle dealerships and sole traders, some with multiple branches and staff working across locations. Tenant activation requires platform-controlled identity and business verification. Tenant membership must not weaken database tenant isolation.

## Decisions

### Tenant and legal entity
- One `Tenant` represents **one business/legal entity**, with one or more `TenantBranch` records.
- Tenant may be `COMPANY` (e.g. S.L., S.A.) or `SELF_EMPLOYED` (autónomo). Store appropriate legal name, entity type, legal form where applicable, Spanish tax identifier (NIF), contact details and registered/billing addresses.
- Branches are operational subdivisions, not separate tenants or credit facilities. A tenant has one centrally managed contractual and financial responsibility; the credit limit is set only by AutoTramita.
- Credit accounts, payment terms, balances and receivables are separate financial models, not direct fields on `Tenant`.

### Users, memberships and branches
- `User` is a global login identity; one user can hold memberships in several tenants.
- `TenantMembership` connects one user to one tenant with role and lifecycle status.
- `MembershipBranch` assigns a membership to multiple branches of the same tenant. Composite tenant-aware foreign keys prevent cross-tenant branch assignments.
- Roles: `OWNER`, `ADMIN`, `MANAGER`, `EMPLOYEE`, `VIEWER`.
- `OWNER` and `ADMIN` have access to **all current and future branches** of their tenant; `MANAGER`, `EMPLOYEE` and `VIEWER` have access only to assigned branches.
- Branch visibility is not permission for every action. `VIEWER` has read-only access. Financial authority such as changing dealership credit limits remains exclusively with AutoTramita.
- Membership lifecycle: `INVITED`, `ACTIVE`, `SUSPENDED`, `REVOKED`. Invitations are single-use, expiring, bound to the intended email and grant no access until accepted.
- `OWNER` and `ADMIN` may invite, suspend and revoke `MANAGER`, `EMPLOYEE`, `VIEWER` memberships. Only `OWNER` may add/remove `ADMIN` memberships. No one may elevate their own role.
- Multiple `OWNER` memberships are allowed. At least one active `OWNER` must remain; the last active owner cannot be suspended or removed. Granting a new owner role requires confirmation by an existing owner. Owner-role changes are audited; AutoTramita provides a separately controlled access-recovery procedure.
- An application `OWNER` role is **not** proof of legal ownership of the company.
- Authorization checks must be enforced server-side in addition to PostgreSQL RLS, and membership revocation must prevent new authorized actions promptly.

### Tenant onboarding and verification
- Tenant status lifecycle: `DRAFT`, `PENDING_VERIFICATION`, `ACTIVE`, `SUSPENDED`, `CLOSED`.
- New tenants can register and submit documentation, but cannot start production case processing until an authorized AutoTramita administrator approves activation.
- `TenantVerification` is a separate, historically retained review record associated with the tenant. Review statuses: `PENDING`, `MORE_INFO_REQUIRED`, `APPROVED`, `REJECTED`.
- Gather relevant identity, NIF, tax/business registration and representative authority evidence appropriate to companies and autónomos, minimizing unnecessary personal data.
- Automated checks may validate NIF structure/check digits, required fields, duplicates and available official-register evidence; their availability and accuracy are not assumed. **Final approval is always manual** by an authorized AutoTramita administrator.
- Requests for more information allow applicants to supplement an existing application. Rejection records include reason, reviewer and time.
- A rejected tenant may submit a **new verification request**; previous review decisions remain in the audit history. AutoTramita can block abusive resubmissions.
- Credit suspension for overdue receivables is separate from tenant administrative/security suspension; it blocks new credit usage only, preserving prepaid service access under ADR-007.

### Audit and security
- Audit invitation, acceptance, membership/role/branch changes, owner confirmations, verification reviews, activation, suspension, closure and resubmission blocks.
- Enforce tenant isolation for branch assignments and tenant-scoped documents. Sensitive verification documents require limited access, retention and deletion policies.
- Admin recovery and cross-tenant actions require distinct privileged, auditable authorization.

## Conceptual entities
`User` (global); `Tenant`; `TenantBranch`; `TenantMembership`; `MembershipBranch`; `TenantVerification`; `TenantVerificationDocument` (metadata/link to private document storage); `AuditEvent`.

## Consequences
One company can centrally manage many branches and shared credit exposure while limiting operational access by role and branch. Review and membership histories remain traceable. Branch authorization is separate from tenant RLS.

## Open design questions (not approved by this ADR)
- Detailed fields, unique constraints, address normalization, NIF change process and duplicate resolution.
- Whether branch creation automatically creates a default branch at onboarding.
- Exact invitation expiration and owner-confirmation method, concurrency controls protecting the last owner, and recovery verification.
- Verification document matrix and retention periods; authoritative sources for automated checks.
- Fine-grained role permissions and branch reassignment of in-progress cases.
- Tenant suspension/closure behavior and data export/retention.

## Scope
**Architecture decision only.** No models, migrations, endpoints, frontend or deployment authorized.
