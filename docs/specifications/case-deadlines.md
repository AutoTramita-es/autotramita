# Case deadlines and priority — specification

Status: DESIGN APPROVED IN PRINCIPLE (Step 39, option A). No implementation or deployment authorized.

## Scope
Centralized deadline tracking across all AutoTramita administrative case types and Tenants.

## Requirements
- A case may carry a statutory/legal deadline, an internal operational deadline, and a priority.
- Track approaching deadlines and identify overdue cases automatically.
- Notify the responsible employee and authorized supervisors through in-app notifications and email before deadlines expire.
- Mark overdue cases distinctly in case lists and dashboards.
- Log changes to deadline values, their actor, timestamp, and reason where provided.
- Legal deadlines must be based on the applicable procedure's verified rules and effective dates; do not fabricate deadlines or treat defaults as legally authoritative.
- Enforce Tenant and branch permissions on deadline visibility, notifications and updates.
- Deadline alerts must not bypass membership suspension/revocation or case reassignment controls.

## Deadline notification schedule (Step 40 — approved A)
- Notify authorized case assignees and supervisors through both in-app notifications and email at 7 days, 3 days, and 1 day before the deadline, and on the due date.
- For unresolved overdue cases, send a reminder every day after the deadline until the case is resolved or that deadline is no longer applicable.
- When a deadline is created with less lead time, send only future applicable scheduled notifications; do not backfill missed milestones.
- Stop future alerts once the case is completed or the deadline no longer applies.
- Respect current Tenant, branch and membership permissions when selecting recipients. Deduplicate each scheduled alert for a given case/deadline and milestone; delivery failure must not block case processing.
- The schedule is a notification policy, not a statement of Spanish statutory deadline calculation; calendar/timezone and procedure-specific legal rules require separate specification.

## Deadline editing permissions (Step 41 — approved A)
- Statutory/legal deadlines are computed from approved, versioned procedure-specific rules and applicable case facts. Ordinary Tenant users, including OWNER, ADMIN, MANAGER and EMPLOYEE, cannot arbitrarily override these calculated deadlines.
- Internal deadlines may be changed by OWNER and ADMIN within their Tenant, MANAGER within authorized branches, and the responsible EMPLOYEE on their assigned case, subject to active membership, case and branch access.
- Changing an internal deadline never modifies the statutory deadline.
- Every internal deadline change records previous value, new value, actor, timestamp and case identity in an immutable audit trail.
- Any correction to a statutory deadline must follow a separately governed rule/fact correction process, not direct manual deadline editing; its authorization and workflow remain to be specified.

## Open design questions
- Escalation recipients and severity for overdue deadlines.
- Rule provenance, versioning, calendar and holiday calculations.
- Governance and approval workflow for statutory rule/fact corrections.
- Priority levels, defaults, and due-date recalculation.
- Alert deduplication, delivery failure, and audit details.

## Acceptance criteria
1. Every supported case type can represent statutory and internal deadlines separately and carry a priority.
2. Authorized staff see approaching and overdue deadlines within their Tenant and branch permissions.
3. Automated in-app and email warnings reach currently authorized case owners and supervisors.
4. Overdue status is clearly visible and changes are auditable.
5. No statutory deadline is inferred without an approved procedure-specific rule and source.
6. Notifications are scheduled at 7, 3, and 1 day before the due date and on the due date, through in-app and email channels.
7. Unresolved overdue cases trigger daily reminders, stopping when the deadline no longer applies or the case is completed.
8. Short-lead cases do not trigger past milestones, and notifications respect current authorization and deduplication.
9. Legal deadlines cannot be directly overridden by Tenant staff; they are calculated using approved procedure-specific rules.
10. OWNER/ADMIN, authorized MANAGER, and responsible EMPLOYEE can edit internal deadlines within their permitted scope, with a complete audit trail.
11. Changing an internal deadline does not alter the legal deadline.
