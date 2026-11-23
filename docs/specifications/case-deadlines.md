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

## Central governance of statutory deadline rules (Step 42 — approved A)
- Only explicitly authorized AutoTramita platform administrators may create, revise, approve and publish statutory deadline calculation rules. Tenant OWNER, ADMIN, MANAGER and EMPLOYEE roles cannot manage those rules.
- Rules are shared across all Tenants for the applicable Spanish administrative procedure and must be grounded in verified official legal sources.
- Each approved rule version records its legal source/reference, approval and change history, effective-from date and, when applicable, effective-to date.
- Preserve historical versions and the rule version used for each case's deadline calculation so results remain traceable and auditable.
- Publishing a new rule version must not silently or indiscriminately recalculate existing cases. Applicability and any required controlled recalculation of open cases must be specified separately.
- The rule governance model does not itself assert that any particular Spanish legal deadline has been verified.

## Controlled applicability of statutory rule changes (Step 43 — approved A)
- Publish each change as a new, traceable approved rule version with its official legal source, effective date, and applicable transitional provisions.
- Determine whether the new version applies to new cases, already-open cases, or both, based on the verified legal text and relevant case facts; do not assume all existing cases are grandfathered or all must be recalculated.
- Recalculate an existing case deadline automatically only when applicability is unambiguous under an approved rule. Audit old and new deadlines, the applied rule version, legal basis, timestamp and reason.
- When transitional provisions or case applicability are ambiguous, preserve the existing recorded deadline pending review and flag the case LEGAL_REVIEW_REQUIRED for authorized review rather than silently recalculating it.
- Maintain historical rule versions and case-level calculation provenance. Ensure recalculation and notifications remain Tenant/branch access-controlled and avoid duplicate alerts.
- This design does not itself validate any specific statutory deadline or transitional provision.

## Central legal review of ambiguous deadlines (Step 44 — approved A)
- Cases marked LEGAL_REVIEW_REQUIRED are routed to an explicitly authorized AutoTramita platform reviewer, with qualified legal expertise consulted when necessary.
- Tenant staff may report incorrect case facts and submit supporting documents for correction under existing case permissions, but cannot interpret or change centrally governed statutory rules on their own.
- The platform reviewer records a reasoned determination, the applicable legal source and rule version, evidence considered, reviewer identity, timestamp and any authorized correction or recalculation in an audit trail.
- Until review is resolved, the disputed deadline must not be represented as legally verified; preserve the previously recorded value as provisional and clearly flag uncertainty.
- Review outcomes affecting shared rules follow central rule version governance. Case-specific factual corrections do not silently alter the global rule.
- Access to case evidence and reviewer actions must respect Tenant isolation and confidentiality.

## Case operations during legal review (Step 45 — approved A)
- A case marked LEGAL_REVIEW_REQUIRED remains accessible to currently authorized Tenant/branch users for work that does not depend on the unresolved legal question, including document collection, factual data entry, and unrelated administrative actions.
- Block only actions whose legal validity or timing directly depends on the unresolved question; enforce the restriction server-side, not merely in the user interface.
- Clearly display the pending legal review and provisional/unverified deadline status; do not imply that a disputed deadline is confirmed.
- Once an authorized central reviewer resolves the issue, reassess the blocked actions under the approved rule and current case facts. Do not automatically execute previously blocked actions.
- Audit review-related restrictions, attempted blocked actions as appropriate, resolution, and subsequent permission/state changes. Maintain Tenant and branch access controls.
- This design does not authorize bypassing any independent mandatory legal or regulatory hold.

## Legal review resolution updates and notifications (Step 46 — approved A)
- Upon a recorded resolution by an authorized central legal reviewer, update the case's legal-review status and confirmed statutory deadline if the determination requires a change.
- Notify the currently responsible employee and authorized OWNER, ADMIN and affected-branch MANAGER through both in-app notifications and email, subject to active membership and current Tenant/branch access.
- Where a deadline changes, the notification and case audit history identify the prior and new deadlines, reason, and applicable legal source/rule version. Email may summarize these details while requiring authenticated access for sensitive case information.
- Re-evaluate previously restricted actions against the confirmed rule and current case facts, but do not automatically execute them.
- Audit the reviewer, determination, status transition, deadline changes, notification events and any subsequent permissions changes. Notification delivery failure does not block the recorded review resolution.
- Do not describe a deadline as confirmed until the authorized review is complete.

## Official Spanish calendars and business-day computation (Step 47 — approved A)
- Distinguish calendar days (días naturales) from legally applicable business days (días hábiles) for each procedure and deadline rule.
- Use verified official Spanish national, autonomous-community and local holiday/non-working-day calendars where relevant to the competent authority and procedure.
- Apply approved procedure-specific rules for the triggering event, start of counting, included/excluded days, deadline end, and any extension when the final day is non-working. Do not assume that every deadline uses the same counting convention.
- Preserve the legal rule version, official calendar source/version, relevant jurisdiction and calculation inputs/outputs for audit and reproducibility.
- If a required authoritative calendar or applicable jurisdiction cannot be established reliably, mark the deadline provisional and route for review rather than presenting it as legally confirmed.
- Calendar updates must be versioned and assessed under controlled rule applicability; no silent bulk changes to existing confirmed case deadlines.

## Official calendar acquisition and approval (Step 48 — approved A)
- Periodically fetch available official Spanish calendar publications from verified authoritative sources, including BOE and competent autonomous-community and local authorities as applicable.
- Store fetched or changed calendar datasets as PENDING_REVIEW, including source URL/reference, jurisdiction, year, retrieval time, publication date when known, and detected differences.
- Only explicitly authorized AutoTramita platform administrators may verify and approve datasets. Approved versions become ACTIVE and eligible for statutory deadline calculation; unapproved data must never silently affect legal deadlines.
- Preserve previously approved calendar versions and a complete approval/change audit trail so historical calculations remain reproducible.
- On acquisition or verification failure, retain existing approved data but flag possible staleness and prevent unverified or inapplicable calendar data from being treated as authoritative for a new calculation.
- Calendar approval is distinct from rule applicability: activation does not indiscriminately recalculate existing case deadlines. Any required updates follow controlled applicability and audit procedures.
- The design does not assume that every authority exposes a machine-readable feed; source-specific acquisition methods require separate validation.

## Open design questions
- Escalation recipients and severity for overdue deadlines.
- Specific source connectors, calendar polling cadence, and mapping between procedure/competent authority and applicable jurisdiction.
- Operational workflow and service-level targets for central legal review.
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
12. Only authorized platform administrators can manage centrally shared statutory deadline rules; Tenant staff cannot edit them.
13. Each approved rule version preserves its official legal source, effective date and change history.
14. Existing case deadlines are not silently or indiscriminately changed by publishing a new rule version.
15. A new statutory rule version applies to existing cases only when verified transitional provisions and case facts establish applicability.
16. Any controlled deadline recalculation records previous/new values, rule version, legal source and reason.
17. Ambiguous transitional applicability preserves the recorded deadline and flags LEGAL_REVIEW_REQUIRED pending authorized review.
18. Only an authorized platform reviewer can resolve legal-rule ambiguity, recording legal basis, evidence and audit history.
19. Tenant staff can submit case-fact corrections and evidence but cannot independently change statutory rules.
20. Pending review, disputed deadlines remain clearly provisional rather than presented as legally verified.
21. LEGAL_REVIEW_REQUIRED cases permit authorized work independent of the unresolved legal question.
22. Legally dependent actions are blocked server-side until authorized review resolves the issue.
23. Review resolution re-evaluates blocked actions without automatically executing them; relevant restrictions and outcomes are audited.
24. Authorized review resolution updates case review status and any applicable confirmed statutory deadline.
25. Responsible staff and authorized supervisors receive in-app and email notifications of resolution, including prior/new deadline, legal basis and reason when changed.
26. Previously blocked actions are re-evaluated but never automatically executed, and review resolution is audited.
27. Deadline calculations distinguish días naturales from días hábiles and apply the relevant verified official national, regional and local calendars.
28. Calculation honors procedure-specific counting and final-day extension rules, with rule and calendar provenance retained.
29. Missing or unverified applicable calendar data prevents a deadline from being presented as legally confirmed.
30. Official calendars are periodically retrieved from verified BOE, regional or local sources where available, with new/changed datasets held as PENDING_REVIEW.
31. Only authorized platform administrators may approve calendar versions for ACTIVE legal deadline calculations; provenance and prior versions remain auditable.
32. Failed calendar retrieval preserves existing approved data while signaling staleness; unapproved data cannot affect statutory deadlines.
