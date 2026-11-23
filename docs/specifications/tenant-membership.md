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

## Independent session workspace context
- Each authenticated session maintains its own active Tenant and active TenantBranch. Switching either in one session must not switch other existing sessions.
- A User may work in BR-0001 on a desktop and BR-0002 on a mobile device at the same time, provided both are authorized.
- The most recently used Tenant and last used branch per Tenant are User preferences used only to initialize new sessions, never to override active workspace contexts in other sessions.
- Every session independently revalidates Tenant membership, branch assignment, and status for protected requests; revocation or suspension takes effect across sessions regardless of saved preferences.
- Workspace context must be server-validated and session-bound, not trusted from a client-provided Tenant or branch identifier.

## Employee invitations
- An authorized OWNER or ADMIN may invite a User by email, subject to existing role-granting restrictions (only OWNER can grant ADMIN; OWNER elevation requires an existing OWNER's confirmation).
- Each invitation is valid for exactly 168 hours (7 days) from issuance, with expiry enforced server-side.
- Acceptance requires a valid, unexpired, single-use invitation token and the intended user's verified email identity; accepting creates or activates the appropriate TenantMembership.
- Once accepted, the invitation token cannot be reused.
- An authorized OWNER or ADMIN may resend an invitation, generating a new token with a fresh 168-hour lifetime; any earlier outstanding invitation link for that membership is immediately invalidated.
- Expired, superseded, or revoked invitations cannot be accepted; invitation issuance, resending, and acceptance are audited.

## Invitation identity verification
- An invitation can be accepted only by an authenticated User whose verified email address matches the invitation recipient email (using the platform's canonical email comparison rules).
- If the recipient has no User account, they must register and verify the invited email address before accepting.
- If authenticated as a different account or with an unverified/mismatched email, acceptance is denied without consuming the invitation token.
- Token expiry, single-use state, membership authorization, and email match must be checked atomically at acceptance; never grant TenantMembership solely from possession of an invitation link.
- The invitation's 168-hour expiry is not extended by account registration or email verification.

## Activation on invitation acceptance
- A valid invitation accepted by the authenticated User with the matching verified email activates the invited TenantMembership immediately: INVITED -> ACTIVE.
- The membership receives the role and branch assignments approved and recorded at invitation issuance, provided those grants remain authorized and applicable at acceptance time.
- No second OWNER/ADMIN approval is required for ordinary permitted role grants.
- Existing elevated-role safeguards remain in force: only OWNER may grant ADMIN; adding OWNER requires confirmation from an existing OWNER and must not be bypassed by invitation acceptance.
- Acceptance and activation are atomic, idempotency-safe, and recorded in the audit log with the inviter, accepting User, Tenant, role, assigned branches and timestamp.
- Membership activation does not override Tenant suspension, closed Tenant status, branch inactivity or other access controls.

## Immediate role changes
- Authorized OWNER or ADMIN may change an ACTIVE member's role within their permitted grant/revoke scope without issuing another invitation or requiring the member's acceptance.
- Only OWNER can grant or remove ADMIN. Adding an OWNER requires confirmation by an existing OWNER. Maintain at least one ACTIVE OWNER per Tenant.
- Role changes take effect immediately for all of the affected User's active sessions; each protected request must authorize against current server-side membership and role state, never a stale session role claim.
- A role downgrade revokes elevated permissions immediately. Any active branch context that is no longer authorized must be invalidated and reselected under the branch selection rules.
- Role changes must be audited with actor, Tenant, affected User, old/new roles and timestamp.

## Immediate branch assignment changes
- OWNER or ADMIN can add or remove explicit branch assignments for MANAGER, EMPLOYEE and VIEWER memberships in their Tenant.
- Changes take effect immediately in all active sessions without requiring a new login. Every protected request checks current branch authorization server-side.
- When an assignment is removed, any session using that branch loses operational access immediately and must select another eligible ACTIVE branch according to the branch selection rules. If none is available, no branch operations are permitted.
- New branch assignments become eligible immediately, subject to ACTIVE membership, ACTIVE Tenant and ACTIVE branch status.
- OWNER and ADMIN retain implicit access to all ACTIVE Tenant branches regardless of explicit MembershipBranch assignments.
- Assignment changes are audited with actor, affected User, Tenant, branch, operation and timestamp.

## Membership suspension and reactivation
- An authorized OWNER or ADMIN may suspend a TenantMembership within their existing role-management scope: ACTIVE -> SUSPENDED. Only OWNER may suspend or reactivate an ADMIN membership; OWNER changes require existing OWNER safeguards.
- Suspension immediately denies access to that Tenant across all active sessions; it does not disable the global User account or memberships in other Tenants.
- Preserve the suspended membership's role, branch assignments, and audit history.
- An authorized administrator may reactivate SUSPENDED -> ACTIVE without a new invitation after validating current authority, Tenant status, role constraints, and the validity of saved branch assignments. Invalid or inactive branch assignments must not grant access.
- Suspending or changing an OWNER must never leave the Tenant without at least one ACTIVE OWNER.
- Record actor, subject, Tenant, transition, reason if provided, and timestamp in the audit log.

## Membership revocation and historical retention
- An authorized OWNER or ADMIN may revoke a TenantMembership within their existing role-management authority: ACTIVE -> REVOKED or SUSPENDED -> REVOKED.
- Revocation immediately denies access to the affected Tenant across every session without affecting the global User identity or other Tenant memberships.
- REVOKED memberships are not directly reactivated. A returning employee must receive and accept a new invitation, with freshly approved role and branch assignments; no former grants are restored automatically.
- Preserve historical membership identifiers, actor references on cases, processing history, and audit records subject to applicable retention and privacy obligations; do not physically delete these links merely because membership was revoked.
- Only OWNER can revoke an ADMIN membership; OWNER changes follow OWNER safeguards. Never revoke the Tenant's last ACTIVE OWNER.
- Log revocation actor, affected User, Tenant, prior status, time and optional reason.

## Unfinished case ownership after membership suspension or revocation
- Suspending or revoking a membership never transfers or deletes the Tenant's cases. Every case remains linked to its original TenantBranch, with its documents, status and complete audit history preserved.
- Any unfinished case assigned to the affected member is flagged as requiring reassignment; it must not remain actionable by that member.
- An authorized OWNER or ADMIN may reassign these cases to an eligible active member. A MANAGER may reassign cases only within branches assigned to that MANAGER, subject to normal case permissions.
- Do not automatically assign these cases to an ADMIN or change their TenantBranch as a side effect of membership suspension or revocation.
- Reassignment records the former and new assignee, actor, time and affected case; completed cases retain historical authorship.

## Reassignment notifications and dashboard
- When a membership is suspended or revoked, identify unfinished cases assigned to that member and flag them for reassignment without changing the case's TenantBranch.
- Automatically notify the Tenant's active OWNER and ADMIN members, and active MANAGER members authorized for the affected case branches.
- Show a dashboard count and a filterable list of cases requiring reassignment, scoped by the viewer's Tenant and accessible branches.
- Authorized OWNER/ADMIN may bulk reassign eligible cases; MANAGER may bulk reassign only cases in assigned branches to eligible active assignees.
- Validate each case and target assignee server-side, preserve case history and documents, and audit each reassignment; do not disclose cases from other Tenants or unauthorized branches in notifications.
- Avoid duplicate notifications for the same membership status transition; delivery failures must not prevent immediate access revocation or case flagging.

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
13. Switching Tenant or branch in one session does not modify the active workspace of another session.
14. Last-used Tenant and branch preferences initialize new sessions only, subject to current authorization.
15. Revoked access is enforced in every session independently.
16. Invitations expire 168 hours after issuance and cannot be accepted thereafter.
17. Resending an invitation invalidates its predecessor and starts a new 168-hour window.
18. Invitation tokens are single-use and cannot be accepted twice.
19. Invitation acceptance requires an authenticated User with the matching verified email address.
20. A new recipient must register and verify their invited email before acceptance; a mismatched account cannot accept.
21. Identity verification does not extend the original invitation expiry.
22. Accepting a valid invitation automatically transitions the invited membership to ACTIVE with the authorized invited role and branch assignments.
23. No second approval is required for ordinary grants; OWNER/ADMIN elevated-role safeguards still apply.
24. Invitation acceptance and activation are atomic and audited; inactive Tenants or branches do not become accessible.
25. Authorized role changes take effect immediately across all active sessions without new invitations.
26. Downgrades revoke former permissions and inaccessible active branches immediately.
27. OWNER/ADMIN grant restrictions and the at-least-one-ACTIVE-OWNER invariant remain enforced; role changes are audited.
28. OWNER/ADMIN branch assignment additions and removals are enforced immediately across all sessions.
29. A removed active branch assignment prevents further operations in that branch and triggers eligible branch reselection.
30. Branch assignment changes are audited; OWNER/ADMIN retain implicit access to all ACTIVE branches.
31. Suspension immediately blocks the affected Tenant across every session without affecting other Tenant memberships or the global User.
32. Reactivation restores the membership without an invitation only after current role and branch permissions are validated.
33. Suspension cannot remove the last ACTIVE OWNER and both transitions are audited.
34. Authorized revocation of ACTIVE or SUSPENDED membership immediately blocks the Tenant across all sessions.
35. REVOKED membership cannot be directly reactivated; return requires a new invitation and newly approved grants.
36. Case authorship, history and audit references survive revocation subject to retention requirements.
37. Revocation cannot remove the last ACTIVE OWNER and does not affect other Tenants.
38. Suspension or revocation flags unfinished cases assigned to the member for reassignment without moving them from their branch.
39. OWNER/ADMIN or authorized branch MANAGER can reassign such cases; reassignment is audited.
40. Case documents, status and history remain intact, and no automatic assignment to ADMIN occurs.
41. Suspension or revocation automatically notifies authorized OWNER/ADMIN and affected-branch MANAGER users of cases requiring reassignment.
42. A tenant- and branch-scoped dashboard displays the count and list of cases awaiting reassignment.
43. Authorized bulk reassignment checks each case and new assignee, preserves history, and audits each change.
44. Notification failure does not delay revocation or reassignment flagging.

## Open design questions
