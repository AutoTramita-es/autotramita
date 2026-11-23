# TenantBranch — Functional and data-model specification

**Status:** Approved business rules; design specification (no implementation)
**Date:** 2026-11-23
**References:** ADR-002, ADR-003, ADR-007, ADR-009

## Purpose and ownership
A Tenant represents one company or autónomo. Each Tenant has one or more branches (TenantBranch); branches do not have separate legal or credit identity. Branches partition operational case visibility and staff assignments inside a tenant.

## Proposed TenantBranch fields
| Field | Proposed type | Constraint / meaning |
| --- | --- | --- |
| id | UUID | Immutable primary key |
| tenant_id | UUID | Required; references Tenant |
| code | varchar(20) | Required; unique within tenant; immutable after creation; normalize for comparison |
| name | varchar(150) | Required; editable, not unique |
| address_line1 | varchar(255) | Optional at creation; required before ACTIVE |
| address_line2 | varchar(255) | Optional |
| postal_code | varchar(10) | Optional at creation; required before ACTIVE |
| city | varchar(100) | Optional at creation; required before ACTIVE |
| province | varchar(100) | Optional at creation; required before ACTIVE |
| country_code | char(2) | ISO 3166-1 alpha-2; default ES; required before ACTIVE |
| email | varchar(254) | Optional |
| phone | varchar(30) | Optional |
| is_primary | boolean | Exactly one active primary branch per active tenant |
| status | enum | ACTIVE or INACTIVE |
| created_at | timestamptz | Required |
| updated_at | timestamptz | Required |

A branch must have a tenant-safe composite key/constraint to support cross-entity composite foreign keys. A tenant's branch codes are unique within that tenant; separate tenants may reuse codes. UUIDs remain stable across renaming. Branch codes are immutable after creation and may never be reused for another branch within the same Tenant, including after deactivation. Names, addresses, email and phone remain editable.

## Activation prerequisites
- A branch can be drafted/created with only tenant, immutable code and name, in addition to its generated identifiers and timestamps.
- Before first activation or reactivation, require complete physical address: street and house number (`address_line1`), postal code, city, province and country.
- Contact email and phone remain optional, since the Tenant may provide shared contact channels.
- No new case intake is permitted until the branch is ACTIVE and its activation prerequisites are satisfied.
- Draft creation is distinct from operational activation. The exact lifecycle representation of a not-yet-active branch (INACTIVE vs separate DRAFT status) remains to be decided.

## Primary branch
- Every ACTIVE Tenant must have exactly one ACTIVE primary branch.
- The first branch is designated primary during onboarding; a Tenant cannot transition to ACTIVE without satisfying this invariant.
- Only OWNER or ADMIN may switch primary branch, within the same Tenant, in an atomic operation.
- A primary branch cannot be deactivated until another ACTIVE branch is made primary.
- Primary branch is a default operational location, **not** a substitute for the tenant's registered address or financial identity.
- Creating a case or assigning a staff member to a default branch must still pass ordinary authorization checks; defaults cannot bypass branch permissions.

## Role and branch visibility
- OWNER and ADMIN have access to all current and future branches of their Tenant.
- MANAGER, EMPLOYEE and VIEWER are scoped to their explicitly assigned active branches through MembershipBranch.
- MANAGER may transfer cases only between branches to which they are assigned; OWNER and ADMIN may transfer cases across all branches of their Tenant.
- EMPLOYEE and VIEWER may not transfer cases between branches.
- Server-side authorization and tenant-isolation/RLS checks apply to all actions.

## Case transfer
- A case belongs to a Tenant and an operational branch. Transfer never changes its Tenant, case ID, documents or historical identity.
- Destination must be an ACTIVE branch of the same Tenant. The actor must have authority for both source and destination branches.
- Record source, destination, actor, time and reason/context where appropriate in immutable audit history.
- Review staff assignments/access when a case is transferred; ensure the next responsible staff have valid destination-branch access.
- Completed cases retain their original branch association and historical audit trail during branch closure.
- No unfinished case may remain assigned to a branch that is being deactivated.
- Deactivation is permitted only after all unfinished cases have been transferred to one or more ACTIVE branches, with authorization checks and complete auditability. Handle concurrent new cases/transfers atomically to avoid orphaned cases.

## Branch reactivation
- OWNER or ADMIN may reactivate an INACTIVE branch of their own Tenant.
- Reactivation preserves the branch UUID, code, name and complete historical records.
- Previous MembershipBranch assignments are **not** automatically restored; authorized OWNER/ADMIN users must explicitly assign staff again.
- Cases previously transferred away from this branch are **not** automatically moved back.
- Reactivation is audited with actor and timestamp.
- Reactivation must not violate the invariant that an ACTIVE Tenant has exactly one ACTIVE primary branch. A reactivated branch is not automatically made primary; changing the primary branch is a separate authorized operation.

## Branch deactivation and membership assignments
- Deactivation prevents new case intake and operational assignment to that branch.
- Remove or deactivate the branch's **active** MembershipBranch assignments without deleting their historical records.
- User accounts and TenantMemberships remain intact; members retain access to any other ACTIVE assigned branches.
- A MANAGER, EMPLOYEE or VIEWER left with no ACTIVE assigned branches cannot process branch-scoped cases until reassigned by an authorized OWNER or ADMIN.
- OWNER and ADMIN retain role-derived access to all other active branches; their access is not dependent on MembershipBranch assignments.
- Never hard-delete a branch with business history.
- Audit deactivation, case transfers, reassignment changes and primary-branch changes.

## Example
Tenant: Autocasa Marbella S.L.; branches MAR-01 (Marbella Centro, primary), MAR-02 (Marbella Este), EST-01 (Estepona).
Before deactivating MAR-02, move all unfinished cases to another active branch and remove its active staff assignments. Finished cases remain historically linked to MAR-02.

## Acceptance criteria for future implementation (not authorization to implement)
1. Two tenants may each use code MAR-01; the same tenant cannot use it twice.
2. Renaming a branch never changes its UUID or historical case linkage.
3. An ACTIVE Tenant cannot have zero or two primary active branches, including under concurrent updates.
4. Only OWNER/ADMIN can change primary branch.
5. MANAGER can transfer cases between two assigned active branches, but not to an unassigned branch.
6. EMPLOYEE/VIEWER cannot transfer cases.
7. Cross-tenant case transfer is always rejected.
8. Deactivation is rejected while unfinished cases remain, including under concurrency.
9. Deactivation retires branch assignments without disabling User/TenantMembership.
10. A non-admin member with no active branch assignment cannot process cases.
11. Historic completed cases and audit events remain accessible subject to authorization and retention rules.
12. Financial and credit identities remain Tenant-scoped, unaffected by branch changes.
13. OWNER/ADMIN can reactivate a branch without changing its UUID, code or history.
14. Reactivation does not restore previous staff assignments or reverse case transfers.
15. Branch code cannot be changed after creation or reused within a Tenant, including after deactivation.
16. Activation and reactivation require street/number, postal code, city, province and country; email/phone are optional.
17. A branch with incomplete physical address cannot receive new cases.

## Pending detail decisions
- Branch code format and normalization rules (code is immutable and never recycled).
- Definition of finished vs unfinished Case statuses and bulk transfer UX.
- Precise atomic transition mechanics and branch-assignment audit schema.

**No implementation, migrations, deployment or Claude Code execution is authorized by this document.**
