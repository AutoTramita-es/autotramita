# TenantMembership and active workspace context — design specification

Status: DRAFT specification (confirmed decisions; no implementation authorized)

## Identity and membership
- A single global User identity can belong to multiple independent Tenants.
- Each Tenant has a separate TenantMembership for the User, with its own role, status, and branch assignments.
- Tenant roles: OWNER, ADMIN, MANAGER, EMPLOYEE, VIEWER.
- Membership statuses: INVITED, ACTIVE, SUSPENDED, REVOKED.
- Tenant data and authorization must remain isolated; changing workspace never grants cross-tenant access.
- An invitation to a User who already has an account adds a separate membership upon acceptance; no new global account is required.

## Tenant selection on login
- If exactly one eligible ACTIVE membership exists, select its Tenant automatically.
- If multiple eligible memberships exist, automatically select the most recently used Tenant when its membership remains ACTIVE and the Tenant is operational; otherwise present a Tenant selector.
- If no eligible memberships exist, deny access to Tenant business data.
- A User can switch between authorized Tenants without signing in again. Recheck authorization and change the server-validated tenant context on every switch.
- Remember the last selected Tenant per User; this preference does not override membership or Tenant status.

## Branch selection and access
- At any time a user workspace has exactly one selected ACTIVE TenantBranch within the active Tenant.
- Remember the last selected branch separately for each User and Tenant; only reuse it if the branch is still ACTIVE and accessible.
- If the remembered branch is inactive or access is lost, apply the first-access branch selection rules below.
- On first access (or when a remembered branch is unavailable), select the Tenant's ACTIVE primary branch automatically if the User is authorized for it; otherwise select the sole other eligible ACTIVE branch automatically; if multiple eligible branches remain, prompt the User to choose; if none, do not enter a branch workspace.
- OWNER and ADMIN can select any ACTIVE branch of their Tenant; MANAGER and EMPLOYEE may select only explicitly assigned ACTIVE branches.
- VIEWER branch selection follows explicit branch assignment and read-only privileges; no case-processing privileges.
- A branch switch does not require reauthentication, but must revalidate membership, role, branch status, and assignment.
- Default case lists and case creation are scoped to the selected branch. A User cannot bypass server-side branch scope by changing client-supplied identifiers.
- A tenant may have several branches but one selected branch per user session; access to all branches for OWNER/ADMIN means they may switch to any branch, not automatically combine case lists.

## Acceptance criteria
1. One User can accept invitations and hold different roles in multiple Tenants.
2. Switching Tenants cannot expose records from another Tenant.
3. Login automatically selects the only eligible Tenant.
4. With multiple eligible Tenants, the most recently used eligible Tenant is selected; otherwise the User chooses.
5. A revoked or suspended membership cannot be restored through a saved preference.
6. The last branch preference is stored per User and Tenant, and revalidated on every use.
7. Exactly one branch is selected in the active workspace; case lists default to that branch.
8. OWNER/ADMIN can select any ACTIVE branch; MANAGER/EMPLOYEE only assigned ACTIVE branches.
9. Switching Tenant or branch revalidates authorization server-side.
10. A User without any eligible branch cannot process cases.
11. On first access, an accessible ACTIVE primary branch is selected automatically.
12. Without access to the primary branch, the only eligible ACTIVE branch is selected automatically; multiple eligible branches require user choice.

## Open design questions
- How long should an invitation remain valid, and how are invitations resent?
- How should concurrent browser sessions maintain separate active workspace context?
