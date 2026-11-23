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

## Daily official calendar checks (Step 49 — approved A)
- Check each configured, available authoritative BOE, autonomous-community and local calendar source at least once every 24 hours, subject to source availability and responsible access limits.
- Detect newly published or changed calendar data and store it as PENDING_REVIEW with source, jurisdiction, year, retrieval timestamp and differences; notify authorized AutoTramita platform administrators.
- Continue using the last approved ACTIVE version until a replacement has been verified and approved; never automatically activate unreviewed data.
- Record each check time, source, outcome and errors for operational monitoring and audit.
- Retry failed checks with controlled backoff and alert administrators about persistent failures, without publishing unverified data or blocking other valid sources.
- Calendar polling frequency does not imply that a specific source guarantees daily publication or machine-readable access.

## Applicable calendar by competent authority and procedure (Step 50 — approved A)
- Select the legally applicable calendar according to the administrative procedure, competent authority, and verified jurisdictional rules, not automatically from the TenantBranch or dealership postal address.
- Consider national, autonomous-community and local non-working days only where they are applicable to that authority and procedure.
- Record the competent authority, selected jurisdiction/calendar identifier and version, applicable statutory rule version, and calculation inputs/outputs for each deadline.
- If competent authority or calendar applicability cannot be reliably established, mark the deadline provisional, flag LEGAL_REVIEW_REQUIRED, and route it to authorized central review instead of asserting a legally confirmed date.
- Preserve Tenant/branch access controls and audit any corrections to authority, jurisdiction or calendar selection.

## Competent authority suggestion and correction (Step 51 — approved A)
- On case creation, suggest the competent administrative authority from the procedure type, relevant location and other approved case facts using centrally governed authority/jurisdiction mappings.
- An authorized Tenant user with case-edit rights may correct the suggested authority, but must provide a reason; record old/new authority, actor, timestamp and justification in the audit trail.
- When an authority correction could change statutory deadlines, re-evaluate the applicable legal rule and official calendar under the controlled applicability process; never silently replace a confirmed deadline without traceability.
- If authority or deadline applicability cannot be reliably verified, flag LEGAL_REVIEW_REQUIRED and present the suggested authority and deadline as provisional pending central review.
- Server-side authorization, Tenant isolation and branch scope apply to authority changes. A user's correction does not itself modify shared legal rules or certify legal applicability.

## Central registry of competent administrative authorities (Step 52 — approved A)
- Maintain a single platform-wide registry of Spanish administrative authorities relevant to supported procedures, including DGT and other competent bodies.
- Each authority record includes official name, official identifier where available, jurisdiction/territorial competence, supported procedure types, source references, effective dates and status as applicable.
- All Tenants use the same approved registry; Tenant OWNER/ADMIN/MANAGER/EMPLOYEE users cannot edit centrally governed authority definitions.
- Only explicitly authorized AutoTramita platform administrators may approve and publish registry changes. Preserve version history, source provenance and audit records.
- Authority registry updates must not silently change existing case jurisdiction, legal deadline, or confirmed competent authority; assess effects through controlled applicability and review.
- Registry entries and mappings must not be treated as legally verified without authoritative source review.

## Monitoring official authority registry sources (Step 53 — approved A)
- Periodically monitor verified official sources, including DGT, BOE and other relevant competent authorities, using source-specific supported access methods.
- Detect candidate changes to authority name, official identifier, territorial jurisdiction, supported procedure types and other centrally governed registry metadata.
- Store candidate changes as PENDING_REVIEW with authoritative source reference, retrieval/publication timestamps where available, and a comparison of old versus proposed values.
- Notify authorized AutoTramita platform administrators; only their explicit approval may activate registry updates.
- Preserve historical versions, approvals, source provenance and an immutable audit trail.
- Never silently reassign competent authority or recalculate confirmed statutory deadlines for existing cases as a consequence of registry updates; assess applicability and route ambiguous impacts for legal review.
- Do not assume all official sources offer structured APIs or automated access; any connector must respect source terms and be validated separately.

## Daily monitoring of authority registry sources (Step 54 — approved A)
- Check each configured, available verified official authority source at least once every 24 hours, respecting access restrictions and rate limits.
- Detect candidate updates to competent authorities and their jurisdictions, preserving source reference, observed differences, check timestamp, result and any errors.
- Place changes in PENDING_REVIEW and notify authorized AutoTramita platform administrators; only explicit approval may activate them.
- Continue to use the last approved ACTIVE registry version until replacement approval, while clearly signaling possible staleness if checks fail.
- Retry failed checks with controlled backoff, escalate persistent failures and keep a monitoring audit trail.
- Daily monitoring does not authorize automated changes to existing case authority assignments or confirmed statutory deadlines.

## Urgent authority-jurisdiction changes (Step 55 — approved A)
- Detect potentially urgent official changes to authority competence, including changes with imminent effective dates, and flag the proposed registry update URGENT_REVIEW for priority handling.
- Promptly alert authorized AutoTramita platform administrators, including official source reference, claimed effective date, affected authority and jurisdiction, and the detected differences.
- Before approval or activation, an authorized platform reviewer must verify the legal basis, effective date, territorial/procedural scope, and any transitional provisions; retain the approval and evidence in the audit trail.
- Identify potentially affected existing cases for targeted review without silently reassigning authorities, changing confirmed statutory deadlines, or executing legally dependent actions.
- If applicability is unclear, flag affected cases LEGAL_REVIEW_REQUIRED and use existing controlled legal-review safeguards; urgency does not waive verification.
- Preserve prior approved registry versions and support an auditable distinction between detection, approval and legal effective date.

## Targeted Tenant notification of authority changes (Step 56 — approved A)
- Following approval of a competent-authority change, identify existing cases potentially affected by the change's legal and territorial applicability; do not treat possible impact as a confirmed change of each case's jurisdiction.
- Notify only affected Tenants, via in-app notifications and email, targeting responsible case employees and authorized supervisors within their permitted Tenant/branch scope.
- Include a concise change description, verified effective date, authoritative reference, and secure in-app links to potentially affected cases requiring review.
- Enforce Tenant isolation and branch-level access on notification recipients and linked case lists; avoid disclosing another Tenant's case information through emails or notifications.
- Record notification creation, recipients, delivery attempts/status where available and acknowledgment/read status where supported; do not equate a successful send with confirmed human receipt.
- Notification alone never modifies case authority or statutory deadlines and never automatically performs legally dependent actions.

## Mandatory review acknowledgment for affected cases (Step 57 — approved A)
- When an approved authority change potentially affects an existing case, mark that case AUTHORITY_REVIEW_REQUIRED until an authorized case user explicitly reviews its competent authority.
- The authorized reviewer must either confirm the existing authority is correct under the applicable rule or initiate a documented correction; record reviewer, timestamp, outcome and rationale/evidence in the audit trail.
- While authority review is outstanding, block only server-side actions legally dependent on the disputed authority; independent case work may continue.
- If authority applicability remains legally ambiguous, escalate to the established central LEGAL_REVIEW_REQUIRED process; a Tenant user's acknowledgment alone cannot certify or override disputed statutory rules.
- Review status and required actions are visible only within permitted Tenant and branch access scope. Completion does not automatically execute previously blocked actions or silently change statutory deadlines.

## Reminders and 48-hour escalation for authority review (Step 58 — approved A)
- For each case flagged AUTHORITY_REVIEW_REQUIRED, record the timestamp when review became required and track its outstanding status.
- Send daily in-app and email reminders to the responsible active, authorized case employee until review is completed; respect Tenant and branch visibility and avoid duplicate notifications for the same daily reminder cycle.
- If review remains incomplete 48 elapsed hours after the flag was set, escalate through in-app and email notices to authorized branch/tenant supervisors (relevant MANAGER where assigned, OWNER/ADMIN as permitted), without exposing case details outside authorized scope.
- Continue daily reminders and maintain the outstanding review flag until an authorized reviewer confirms competence or initiates an appropriate correction or legal-review path; merely sending or reading a notice does not count as completion.
- Keep legally authority-dependent actions blocked server-side during unresolved review while allowing independent work; do not automatically execute blocked actions upon resolution.
- Audit reminder and escalation schedules, attempted deliveries, recipients, and review completion. If the assigned employee is unavailable, use the existing reassignment safeguards rather than silently abandoning review.

## Critical statutory deadline risk during authority review (Step 59 — approved A)
- When a case remains AUTHORITY_REVIEW_REQUIRED and its legally confirmed statutory deadline is less than 24 elapsed hours away, flag CRITICAL_DEADLINE_RISK and give it the highest urgency on authorized case dashboards.
- Immediately send in-app and email alerts to the responsible authorized employee and relevant authorized MANAGER/OWNER/ADMIN within Tenant and branch permissions.
- Include the confirmed deadline, remaining time, reason for authority review, and secure case link; avoid leaking case details across Tenants or unauthorized branches.
- If the deadline is provisional or legally disputed, prominently disclose uncertainty and escalate urgent legal verification rather than representing a guessed deadline as confirmed.
- The critical flag does not change the legal deadline, waive mandatory authority review, lift server-side restrictions on legally dependent actions, or execute blocked actions.
- Audit trigger time, recipients, delivery attempts, urgency status and eventual review resolution; prevent duplicate alerts for the same trigger while allowing material changes to retrigger assessment.

## Statutory deadline exceeded: escalation and review (Step 60 — approved A)
- When a legally confirmed statutory deadline passes and the case remains unresolved, flag STATUTORY_DEADLINE_EXCEEDED and surface it in a dedicated overdue queue for authorized Tenant/branch users.
- Immediately notify the responsible authorized employee and relevant authorized supervisors through in-app and email channels, respecting Tenant and branch access boundaries.
- Record the confirmed due date, elapsed overdue duration, trigger timestamp, notifications, review actions and outcomes in the case audit trail.
- Do not infer that missing a deadline automatically makes the procedure irrecoverably lost, legally invalid or impossible to remedy; consequences depend on the specific procedure and applicable law.
- Require an authorized review of legal consequences and available next steps, escalating legal uncertainty to the central LEGAL_REVIEW_REQUIRED workflow as needed.
- Do not silently alter statutory dates, bypass existing legally dependent action restrictions, or execute actions automatically on escalation.
- If the deadline is unconfirmed or disputed, do not label it as a confirmed statutory breach; instead display uncertainty and escalate urgent verification.

## Controlled closure of statutory deadline overrun review (Step 61 — approved A)
- The responsible authorized employee may submit an explanation and supporting evidence for a case flagged STATUTORY_DEADLINE_EXCEEDED, but may not independently close the overrun review.
- Only an authorized Tenant OWNER/ADMIN or MANAGER with the relevant branch/case scope may approve closure after reviewing the explanation, evidence and applicable consequences.
- Where legal consequences or possible remedies remain ambiguous, route to the existing central LEGAL_REVIEW_REQUIRED process; Tenant supervisory approval cannot override unresolved central legal review.
- Closure marks the overrun review as resolved or dispositioned, not the historical breach as erased: retain the original due date, exceeded flag/history, explanation, evidence, approver, decision rationale and timestamps in immutable audit history.
- Closure must not silently alter statutory deadlines, remove independent legal restrictions, or automatically execute previously blocked actions. Enforce Tenant isolation and branch authorization server-side.

## Official proof of timely submission (Step 62 — approved A)
- Support attaching an official filing receipt (justificante de presentación) to a case, preserving the original document, issuer/competent authority, official registration or entry number where available, and the recorded submission date and time including timezone when available.
- Compare the verified official filing timestamp against the legally applicable statutory deadline and procedure-specific rules; document the comparison and source evidence.
- A responsible employee may upload and describe the receipt but cannot independently dismiss an exceeded-deadline alert. An authorized scoped OWNER/ADMIN/MANAGER may close the overrun review after validating evidence and applicability.
- If verified evidence establishes timely submission, distinguish an initial automated overrun alert from a legally confirmed missed filing; retain the alert and correction history without inaccurately preserving a disproven breach as fact.
- Inconsistent, incomplete, unauthenticated or legally ambiguous evidence requires review and, when necessary, escalation to LEGAL_REVIEW_REQUIRED rather than automatic clearance.
- Keep the original receipt, evidence metadata, verification outcome, approver, decision rationale, and complete audit trail; do not silently change statutory rules or execute blocked actions.

## Automated extraction and authenticity checks for filing receipts (Step 63 — approved A)
- For attached official filing receipts (justificante de presentación) in supported PDF or image formats, attempt automated extraction of submission date/time (including timezone when stated), registration number, issuing/competent authority, and available document verification identifiers.
- When a Código Seguro de Verificación (CSV) or another supported official validation mechanism is available, attempt authenticity verification against the relevant official source; do not assume every authority offers an automated validation endpoint.
- Track document verification status as VERIFIED, PENDING_REVIEW or VERIFICATION_FAILED, with provenance, validation method, timestamp, errors and extracted-field confidence or uncertainty as appropriate.
- Distinguish successful text extraction from official authenticity verification and from legal determination of timely filing. OCR or parsing alone never certifies authenticity or timeliness.
- Route unreadable, incomplete, contradictory, unverifiable or failed documents for authorized manual review; do not automatically dismiss statutory deadline alerts based on unverified extracted data.
- Preserve the original uploaded document, extracted values, verification evidence, manual corrections, reviewers, and full audit history, with Tenant/branch access control and appropriate handling of sensitive case information.

## Retry official CSV receipt verification on service unavailability (Step 64 — approved A)
- If an official CSV (Código Seguro de Verificación) validation service is temporarily unavailable, retain the receipt's PENDING_REVIEW status and explicitly distinguish service unavailability from a failed authenticity check.
- Automatically retry validation with bounded, progressively increasing delays and source-appropriate rate limits; log each attempt, timestamp, result and error without exposing sensitive tokens or receipt data in operational logs.
- Permit case work independent of receipt authenticity verification to continue; do not represent the document as VERIFIED or use unverified extraction alone to dismiss statutory deadline alerts.
- If a statutory deadline is near or uncertain, trigger the existing urgent deadline-risk notification and legal-review safeguards as applicable.
- After persistent service unavailability, notify authorized users and route to manual review while retaining scheduled retries when appropriate; manual review must document evidence and cannot claim an unavailable official check succeeded.
- When the service recovers, store the official verification result and evidence; any closure of an overrun review remains subject to authorized supervisory approval and audit.

## Official CSV verification failure and mandatory review (Step 65 — approved A)
- When a reachable official verification service affirmatively reports an invalid CSV code or a mismatch between the submitted receipt and its official record, set receipt verification status to VERIFICATION_FAILED, distinguishing this outcome from transient service unavailability.
- Immediately alert the responsible authorized employee and relevant authorized supervisor via in-app and email notifications within Tenant and branch scope.
- Do not treat the receipt as verified evidence of timely filing, automatically dismiss statutory deadline warnings, or permit legally dependent actions based on that unverified receipt.
- Require a documented manual review to distinguish transcription/format errors, incorrect document selection, official-record mismatch, and other explanations. Escalate unresolved legal ambiguity to LEGAL_REVIEW_REQUIRED.
- Preserve the original document, supplied CSV, official service response/evidence, timestamps, reviewer findings, corrections and full audit trail. Any subsequent successful verification must be recorded as a new result, not overwrite the failure history.
- An invalid or mismatched CSV alone is not proof of intentional fraud; do not automatically accuse the user or make a fraud determination.

## Manual correction of extracted CSV with official re-verification (Step 66 — approved A)
- An authorized case employee may correct an inaccurately extracted Código Seguro de Verificación (CSV) by comparing it against the unchanged original official receipt.
- Preserve the original extracted value, corrected value, actor, timestamp, reason and any prior official verification responses in the case audit history; do not alter the source document.
- After correction, automatically request a fresh verification from the relevant supported official service, subject to the existing unavailability/retry safeguards.
- Until official validation succeeds or an authorized alternative evidence review is completed, do not represent the receipt as VERIFIED or use it as authenticated proof of timely submission.
- A previous VERIFICATION_FAILED result remains in historical records even if a later verification succeeds; the current verification state may transition to PENDING_REVIEW during recheck and to VERIFIED only upon qualifying verification.
- A corrected CSV does not automatically dismiss deadline alerts, change statutory deadlines, unblock legally dependent actions, or close an overrun review without the established authorization and audit requirements.

## Alternative verification for official receipts without CSV (Step 67 — approved A)
- Accept filing receipts issued without a Código Seguro de Verificación (CSV); absence of CSV alone does not make an official receipt invalid.
- Attempt another supported official validation mechanism, if one exists for the issuing authority and document type.
- When no official electronic validation is available, allow an authorized case employee to provide the original receipt and supporting evidence for documented manual review by a properly scoped Tenant OWNER/ADMIN or MANAGER.
- Distinguish the evidence verification method/outcome OFFICIALLY_VERIFIED from MANUALLY_ACCEPTED; manual acceptance is not represented as an official authenticity confirmation. These evidence classifications are separate from the existing receipt workflow statuses VERIFIED, PENDING_REVIEW and VERIFICATION_FAILED.
- Where authenticity, applicability or legal validity remains ambiguous, escalate to LEGAL_REVIEW_REQUIRED; do not silently clear statutory deadline warnings or override legally dependent action blocks.
- Retain the original document, source, supporting evidence, method, reviewer, decision, rationale, timestamps and full audit history with Tenant/branch isolation.

## Match filing receipt to the correct case (Step 68 — approved A)
- Compare available filing-receipt identifiers against the associated case, including VIN, vehicle registration plate, applicant identity, procedure type and application/filing reference number, accounting for procedure-specific applicability and normalised representations.
- A material contradiction sets DOCUMENT_CASE_MISMATCH and prevents automatically accepting the receipt as evidence of filing for that case, even if the document itself is officially authentic.
- Missing or unreadable identifiers yield an explicitly incomplete/uncertain match assessment, not a falsely asserted mismatch or successful match.
- An authorized case employee may supply clarification and evidence; only a properly scoped OWNER/ADMIN or MANAGER may approve a documented resolution following review. Unresolved legal ambiguity follows LEGAL_REVIEW_REQUIRED.
- Preserve extracted and case-side comparison values, source document, comparison outcome, discrepancies, supporting evidence, reviewer decision and full audit history.
- Neither official document verification nor a case-match decision alone automatically clears statutory deadline alerts or overrides established legal blocks.

## Detect duplicate filing receipts safely (Step 69 — approved A)
- Detect potential reuse of filing receipts by comparing document cryptographic fingerprints, official CSV identifiers and official filing/registration references, with normalization and issuer scoping to avoid false positives.
- Mark candidate duplicates POSSIBLE_DUPLICATE_RECEIPT; a match is a review signal, not automatic proof of improper reuse or fraud.
- Allow one authentic receipt to support multiple related cases only where its scope and case identifiers substantiate that relationship and an authorized, appropriately scoped Tenant OWNER/ADMIN or MANAGER approves the association.
- For cross-Tenant matches, enforce strict non-disclosure: never reveal another Tenant's identity, client details, documents, case identifiers or other confidential metadata. Any platform-level deduplication must be access-controlled and privacy-reviewed, with a generic warning only.
- Record match basis, reviewer, decision, related-case justification within permitted Tenant scope, timestamps and audit history. Do not automatically clear deadline alerts or bypass document-case matching and authenticity checks.

## Recheck official receipts for subsequent revocation (Step 70 — approved A)
- For authorities and receipt types supporting repeat official validation, periodically revalidate previously verified receipts with rate limits, source-specific schedules and auditable outcomes.
- Only an affirmative official revocation or cancellation result sets RECEIPT_REVOKED; a service outage, timeout or unverifiable response must not be treated as revocation.
- Immediately alert the responsible authorized employee and appropriately scoped OWNER/ADMIN/MANAGER through in-app and email notifications, with Tenant and branch isolation.
- Prevent reliance on a revoked receipt as currently valid evidence of timely filing; reassess the case's statutory deadline and procedural consequences under centrally approved legal rules and applicable transitional provisions.
- If legal effects are uncertain, flag LEGAL_REVIEW_REQUIRED and block only legally dependent actions; never automatically declare a missed deadline or perform remediation.
- Preserve the original receipt, previous verification decisions, official revocation evidence, timestamps, affected-case assessments, notices and full audit history. Any subsequent restoration or correction requires a new documented official result or authorized review.

## Propagate revoked receipt review to all linked cases (Step 71 — approved A)
- On an officially confirmed receipt revocation, identify every case known to rely on the revoked receipt, including linked cases across separate Tenants when a privacy-safe document association exists.
- Flag each affected case REVOKED_RECEIPT_REVIEW_REQUIRED and separately assess procedure-specific consequences, statutory deadlines, evidentiary relevance and whether legally dependent actions require blocking or central legal review.
- Immediately notify only the responsible authorized employees and appropriately scoped supervisors for each affected Tenant and branch, via existing in-app and email channels.
- Cross-Tenant association and matching must be processed under platform-level access controls without disclosing other Tenants' identities, clients, cases, receipt content or other confidential information. Each Tenant sees only its own affected cases and permitted evidence.
- Do not automatically conclude that every related filing is legally invalid or that every deadline was missed. Retain the official revocation source, affected-case associations, assessments, notifications, decisions and audit trail.
- Maintain the existing LEGAL_REVIEW_REQUIRED and deadline escalation safeguards; no automatic execution of blocked actions or silent clearance of existing alerts.

## Post-closure review after official receipt revocation (Step 72 — approved A)
- If an officially revoked receipt was relied upon by a previously completed/closed case, create a distinct post-closure review flagged POST_CLOSURE_REVIEW_REQUIRED; do not silently change the original completed status or rewrite the case's historical outcome.
- Notify the responsible authorized Tenant supervisor and other relevant scoped case users, and assess whether the revocation affects the specific completed procedure, legal deadline, evidence or subsequent obligations.
- A properly scoped OWNER/ADMIN/MANAGER oversees the post-closure review; unresolved legal uncertainty escalates to LEGAL_REVIEW_REQUIRED and applicable legally dependent actions remain blocked.
- Preserve original completion evidence and timestamps, official revocation notice, post-closure review findings, approvals, resulting actions and immutable audit history.
- Do not automatically declare the completed procedure legally void or perform corrective filings; any remedy must follow approved procedure-specific legal and authorization controls.

## Controlled authorization of post-closure corrective actions (Step 73 — approved A)
- An authorized employee may prepare a proposed post-closure correction, supporting documents and rationale, but cannot independently execute the proposed corrective filing or action.
- A properly scoped Tenant OWNER/ADMIN or MANAGER must review and explicitly approve the proposed corrective action before execution; record approver, scope, decision, evidence and timestamps.
- Supervisor approval does not confer legal authority to represent a client or file with a competent body. If the procedure requires a duly authorized Gestor Administrativo or other legally empowered representative, only such an authorized actor may submit or execute it, subject to verified mandate and applicable legal requirements.
- If legal permissibility, required credentials, representation or consequences are uncertain, refer to LEGAL_REVIEW_REQUIRED and do not execute legally dependent steps until resolved.
- Preserve original case closure and completion evidence, correction proposal, approvals, execution identity, submission proof, outcomes and immutable audit history. No automatic filings or silent alteration of the completed-case record.

## Registry and authorization of professional representatives (Step 74 — approved A)
- Maintain a centrally governed registry of professional representatives, including Gestores Administrativos and other legally permitted representative categories; store verified identity, professional registration number and Colegio Oficial where applicable, professional status, scope and provenance of verification.
- Support linking a representative to one or more Tenants without granting cross-Tenant access to cases, clients or mandates.
- Maintain case/client/procedure-specific proof of representation (mandate, power of attorney or other legally sufficient authority), its scope, validity, issuer, evidence and revocation/expiry where applicable.
- Before a filing requiring representation, separately verify the actor's legally required professional entitlement and the mandate to act for that client and procedure, according to centrally approved procedure-specific rules. Do not assume every filing requires a Gestor Administrativo.
- Block legally dependent submission when required entitlement or mandate is absent, expired, revoked or unverified; escalate uncertain legal requirements to LEGAL_REVIEW_REQUIRED.
- Preserve verification provenance, evidence, decisions and immutable audit logs. Tenant supervisor approval does not substitute for legal authorization, and registration records alone do not establish a client mandate.

## Initial operating model: manual Tramisur handoff (business priority clarification)
- Phase 1: each Tenant/dealership receives customer requests, collects and processes supporting documents, and submits a prepared case through AutoTramita.
- AutoTramita's internal backoffice reviews documents, requests missing information, prepares the case and coordinates manual handoff with external provider Tramisur. Tramisur handles the agreed official filing/representation activities within its actual legal authority; AutoTramita records returned status, evidence and outcome for the Tenant.
- For the initial release, do not require automated professional-registry integrations, automated gestor verification or automated provider submission. Record the responsible external provider and manually verified authority/mandate where legally required; preserve existing legal authorization and filing safeguards.
- Phase 2, only after observing actual operations: consider automation of repeatable checks and provider exchange.
- Phase 3, subject to growth and applicable professional requirements: optionally employ an in-house licensed Gestor Administrativo and adapt the workflow.
- Step 74 representative-registry design is a future-capability specification, not a Phase 1 implementation requirement. Step 75 periodic automated professional-status verification is deferred, not approved.
- This is an architecture/business-priority decision only: no implementation or deployment authorized.

## Phase 1 manual handoff to Tramisur (Step 75 — approved A)
- The Tenant/dealership collects customer documents and prepares the case; AutoTramita internal backoffice validates completeness and assembles a case-specific handoff package for Tramisur.
- An authorized AutoTramita backoffice operator transmits the package using an agreed secure channel; record the handoff timestamp, responsible operator, recipient/provider, channel reference, manifest/version of transmitted documents, and current handoff status.
- Tramisur handles the agreed official procedure within its legal authorization and returns case outcome, filing receipt and other official evidence through the agreed secure channel. Backoffice records the response, documents, status and timestamps and notifies the authorized Tenant users.
- Maintain immutable audit history and Tenant isolation. External handoff must respect personal-data minimization, authorized recipient checks and existing mandate/legal-filing controls; transmission alone is not proof of official filing.
- No Tramisur API, automated provider integration, or deployment is authorized in Phase 1. Future automation remains a separate architecture decision.

## Phase 1 manual Tramisur processing statuses (Step 76 — approved A)
- Track external-provider handoff progress with READY_FOR_TRAMISUR (prepared, not yet transmitted), SENT_TO_TRAMISUR (handoff recorded), IN_PROCESS (provider processing confirmed), ADDITIONAL_DOCUMENTS_REQUIRED (provider requests a documented supplement), and COMPLETED (official outcome and supporting evidence recorded).
- Only authorized AutoTramita backoffice staff update provider-facing workflow statuses based on actual communications and evidence from Tramisur; do not imply that SENT_TO_TRAMISUR means an official filing was submitted.
- ADDITIONAL_DOCUMENTS_REQUIRED captures the request, required items and responsible follow-up; once supplied, return to the appropriate confirmed processing state rather than silently completing the case.
- COMPLETED requires a documented outcome and relevant official receipt or evidence as applicable; unresolved legal, deadline or document-verification blockers retain their independent controls.
- Tenant users see permitted case progress and actionable document requests but not confidential internal backoffice notes or another Tenant's information.
- Audit every status transition with actor, timestamp, source/reason, and supporting evidence. No Tramisur API or automated status synchronization in Phase 1.

## Phase 1 additional documents through Tenant portal (Step 77 — approved A)
- When Tramisur requests supplementary documentation, an authorized AutoTramita backoffice operator records the provider's request, required document types, instructions and relevant dates on the existing case, setting ADDITIONAL_DOCUMENTS_REQUIRED.
- Notify authorized users of the relevant Tenant/branch in-app and by email, disclosing only information appropriate for that Tenant; allow them to upload requested supplementary documents directly into the existing case.
- Preserve the originals and all replacement or supplementary document versions, upload actor, timestamps, request-to-document association and audit history; never silently overwrite previous evidence.
- Backoffice reviews the new documents for completeness and suitability, records review outcomes, and manually transmits the approved supplement to Tramisur through the agreed secure channel, recording the handoff manifest, recipient, operator and timestamp.
- Uploading a document does not mean that Tramisur has received, accepted or officially filed it. Provider receipt/acceptance and workflow transitions require independently recorded evidence.
- Maintain applicable deadline alerts, legal authorization controls and Tenant/branch isolation throughout; no automated Tramisur integration in Phase 1.

## Phase 1 two-stage document completeness approval (Step 78 — approved A)
- The Tenant/dealership collects required case documents and explicitly marks the case as submitted for AutoTramita backoffice completeness review; this Tenant assertion does not itself establish readiness for Tramisur.
- An authorized AutoTramita backoffice operator independently checks the documents against the centrally approved, procedure-specific checklist and records findings.
- If items are missing, inconsistent or unusable, return the case to the appropriate Tenant/branch with actionable reasons and a request for correction or supplementary evidence; maintain document versions and audit history.
- Only after backoffice approval may the case enter READY_FOR_TRAMISUR and be eligible for the controlled manual Tramisur handoff. Enforce this gate server-side.
- Record Tenant submitter, reviewing backoffice actor, timestamps, checklist version, decision, reasons and supporting evidence. Backoffice approval establishes internal document readiness, not official acceptance by Tramisur or a competent authority.
- Continue to enforce independent legal representation, statutory deadline and document authenticity safeguards; no implementation or deployment authorized.

## Central procedure-specific document checklists (Step 79 — approved A)
- AutoTramita centrally governs versioned document checklist templates per procedure type, with mandatory and conditionally mandatory items and clearly defined conditions.
- When a Tenant/dealership creates a case, the platform selects the applicable approved checklist version and shows the required items and completion state.
- Tenant users may upload and replace evidence but cannot delete, bypass or mark centrally mandatory requirements as inapplicable without an authorized, documented exception review.
- Backoffice may request additional case-specific documents with a recorded reason; such additions do not silently modify the central template.
- Store checklist template/version, applicability decisions, item-to-document associations, completion and review outcomes, actors and timestamps in the case audit history.
- Backoffice remains responsible for the second-stage readiness review and approval before READY_FOR_TRAMISUR; checklist completion alone does not authorize handoff or official filing.
- Template changes require centrally governed approval and explicit effective dates; preserve historical case context and apply legal-transition rules where relevant.

## Dynamic conditional document checklist (Step 80 — approved A)
- Derive the applicable mandatory and conditionally mandatory document items from the centrally approved, versioned procedure template and case attributes, including applicant category, vehicle provenance and other legally relevant fields.
- Re-evaluate checklist applicability whenever an authorized Tenant user changes a relevant case attribute; display newly required items and the reason/condition for each requirement.
- Preserve previously uploaded files, document versions and all historical checklist applicability decisions, even if a document is no longer currently required. Do not silently discard evidence.
- Audit the old and new attribute values, actor, timestamp, rule/template version, affected checklist items and resulting readiness state.
- If a material change affects an already backoffice-approved case before handoff, invalidate its prior document-readiness approval and require a fresh backoffice review before READY_FOR_TRAMISUR or transmission; do not silently reopen or undo a completed official filing.
- Unclear legal applicability is escalated for review rather than arbitrarily resolved by a Tenant user; preserve statutory deadlines and independent filing authorization controls.
- Architecture only: no implementation or deployment authorized.

## Upload technical validation and manual backoffice document review (Step 81 — approved A)
- On Tenant document upload, automatically validate allowed file types (initially PDF, JPEG/JPG and PNG), configurable size limits, file integrity and basic security checks; reject unsafe, unsupported or corrupt files with actionable user feedback and an auditable rejection reason.
- Do not treat a technically valid upload as authentic, legible, complete, legally sufficient or accepted by Tramisur.
- Authorized AutoTramita backoffice reviewers manually inspect readability, completeness, correct document type, case identity/attribute consistency and whether a clearer replacement or supplement is required.
- Record technical validation outcome separately from manual review status, reviewer, timestamps, findings and any resubmission request; preserve original and replacement versions under Tenant isolation and retention controls.
- Only the approved two-stage completeness gate permits READY_FOR_TRAMISUR; maintain independent authenticity, legal-authority and deadline safeguards.
- No OCR-based automated substantive approval or Tramisur integration is required for Phase 1; architecture only, no implementation/deployment authorized.

## Per-document manual review statuses (Step 82 — approved A)
- Each uploaded case document/version has an independently tracked backoffice review status: PENDING_REVIEW, APPROVED, REJECTED, or REPLACEMENT_REQUIRED. These review statuses are distinct from upload technical-validation outcomes, authenticity verification, and case workflow status.
- Only appropriately authorized AutoTramita backoffice staff may approve, reject, or request replacement; record reviewer, timestamp, decision, reason and relevant evidence in an immutable audit history.
- Tenant users see the status and actionable, Tenant-safe explanation for rejected documents or replacement requests, but not confidential internal notes or other Tenants' information.
- A replacement is a new preserved document version with a fresh PENDING_REVIEW decision; prior files, decisions and timestamps remain accessible to authorized auditors and reviewers.
- Backoffice may retain approval of unchanged documents, but a materially changed document or relevant case attribute must trigger the appropriate re-review.
- READY_FOR_TRAMISUR requires every applicable mandatory checklist item to be satisfied by an approved current document, plus separate overall backoffice readiness approval and existing legal/deadline controls. Individual document approval alone never establishes official acceptance by Tramisur.
- Architecture/specification only; no implementation or deployment authorized.

## Rejected-document notifications and correction tasks (Step 83 — approved A)
- When authorized backoffice staff set a document to REJECTED or REPLACEMENT_REQUIRED, automatically create or update a case-linked correction task for the responsible Tenant/branch user, avoiding duplicate open tasks for the same document requirement.
- Notify the responsible eligible Tenant user in-app and by email, with the document type, actionable rejection/replacement reason and secure case link; avoid sensitive document contents in email and enforce Tenant/branch access on opening.
- Permit authorized Tenant users to upload a replacement as a new preserved version within the existing case. Notify the relevant backoffice review queue when a replacement passes upload validation and is ready for fresh manual review.
- Keep the task open until the required document is approved by backoffice, or an explicitly authorized and audited determination establishes that the requirement no longer applies; uploading alone does not close it.
- Track task ownership, creation, notification, reassignment, resubmission, review, closure and timestamps in the case audit trail; preserve prior document decisions and versions.
- Maintain statutory deadline reminders and independent readiness, authenticity and legal-authorization gates. No implementation or deployment authorized.

## Missing-document reminders and escalation (Step 84 — approved A)
- For an open Tenant correction task requiring supplementary or replacement documentation, send an in-app and email reminder to the eligible assigned Tenant user at 24 hours after the documented request, and another at 48 hours, provided the required upload remains outstanding.
- At 72 hours without submission, escalate to an appropriately scoped active branch MANAGER or Tenant ADMIN/OWNER; avoid duplicate escalations and never disclose case information outside authorized Tenant/branch scope.
- When a replacement is submitted and awaits backoffice review, suspend missing-upload reminders while keeping the correction task open until approval; backoffice rejection or a new replacement request creates a documented follow-up cycle with its own notification timeline, without erasing prior cycles.
- Statutory deadline alerts and imminent-risk escalation operate independently and immediately when warranted; the 24/48/72-hour schedule must never delay legal-deadline warnings.
- Record notification schedule, delivery attempts, recipient, escalation, actor, task state, timestamps and any authorized reassignment or closure in the audit trail.
- No automated Tramisur integration, implementation or deployment authorized.

## Primary responsible Tenant employee per case (Step 85 — approved A)
- Every active case has one primary responsible eligible Tenant employee, scoped to the case's active branch, for operational ownership of document requests, correction tasks, reminders and case follow-up.
- An appropriately authorized branch MANAGER or Tenant ADMIN/OWNER may reassign case responsibility within existing branch-membership permissions; record old/new assignee, actor, reason and timestamp without rewriting history.
- On membership suspension, revocation, loss of branch access or departure, retain the case and all evidence, flag unfinished cases for reassignment and notify eligible supervisors according to the existing reassignment/escalation policy.
- Transfer outstanding actionable tasks and future case notifications to the new eligible assignee without erasing previous task, reminder or audit records; no cross-Tenant access or unauthorized branch visibility.
- Supervisors retain oversight within their authorized scope, while the single assignee remains the default operational recipient. Statutory deadlines and urgent alerts remain independent of reassignment.
- Architecture only; no implementation or deployment authorized.

## Primary AutoTramita backoffice operator per case (Step 86 — approved A)
- Each active case has one primary responsible AutoTramita backoffice operator, distinct from the Tenant/dealership's primary responsible employee.
- The assigned operator coordinates document completeness review, Tenant communication, manual Tramisur handoff, provider follow-up, outcome evidence and case completion within applicable permissions.
- Authorized backoffice supervisors may reassign the operator for absence, workload or other operational reasons, recording previous and new assignee, actor, reason and timestamp in the immutable audit trail.
- Transfer pending backoffice tasks and future operational notifications to the newly assigned operator while preserving past actions, messages, document reviews and evidence.
- If an operator becomes unavailable, flag cases for reassignment and notify an authorized backoffice supervisor; no case should become invisible or lose statutory deadline monitoring.
- Assignment does not itself confer licensed professional representation rights or permission to perform Tramisur's legally restricted filings.
- Keep Tenant and platform backoffice role boundaries and Tenant isolation enforced. Architecture only; no implementation or deployment authorized.

## Automatic workload-based backoffice assignment (Step 87 — approved A)
- When a Tenant submits a case for AutoTramita backoffice review, automatically assign one primary backoffice operator from the pool of active, available and appropriately authorized operators.
- Select the eligible operator with the fewest currently active assigned cases; use a deterministic fair tie-breaker to distribute equal-load assignments rather than repeatedly favoring one operator.
- Make assignment atomically under concurrent case submissions to avoid race conditions and systematic overload. Record assignment method, selected operator, timestamp and decision basis in the audit trail.
- An authorized backoffice supervisor may manually reassign a case with an auditable reason; preserve all prior task and assignment history and route future notifications to the new operator.
- If no eligible operator is available, retain the case in an unassigned backoffice queue and notify the supervisor; keep statutory deadline alerts active.
- Automated workload assignment grants no legal representation authority and does not automate Tramisur handoff or official filing. Architecture only; no implementation or deployment authorized.

## Backoffice operator availability states (Step 88 — approved A)
- Maintain availability states AVAILABLE (eligible for new case assignment), BUSY (continues existing work but no new assignments), AWAY (absent, no new assignments) and OFFLINE (not currently logged in, no new assignments).
- Automatic workload-based assignment from Step 87 considers only active, appropriately authorized operators whose effective availability is AVAILABLE at the assignment instant.
- Operators may update their own work availability; authorized backoffice supervisors may override it, with actor, reason, source and timestamp audited.
- OFFLINE is derived from authenticated session presence and must not be spoofed by a manual AVAILABLE setting; define effective availability consistently across concurrent sessions and avoid stale-presence assignment.
- A change to BUSY, AWAY or OFFLINE does not automatically remove already assigned cases; supervisors can explicitly reassign them with audit history. Urgent deadlines, pending tasks and escalations continue even when the assignee is unavailable.
- If no operator is eligible, cases remain in the unassigned queue with supervisor notification and independent statutory deadline monitoring.
- Architecture only; no implementation or deployment authorized.

## Preserve backoffice case ownership across logout (Step 89 — approved A)
- When a backoffice operator logs out or becomes effectively OFFLINE at the end of the workday, retain ownership of all unfinished assigned cases and their history; do not bulk reassign solely because the operator is offline.
- The operator can resume assigned work on return, subject to active account and permissions; the operator is ineligible for new automatic assignments until effective availability becomes AVAILABLE.
- Continue independent monitoring of statutory deadlines, urgent case risks, open tasks and supervisory escalation while the assignee is offline; offline status must never suppress urgent alerts.
- Authorized backoffice supervisors may manually reassign urgent or otherwise necessary cases to eligible operators, recording the reason, old/new assignee, actor and timestamp and routing future notifications appropriately.
- Distinguish ordinary end-of-day logout from suspension, revocation, prolonged absence or account removal, which remain subject to existing case reassignment and access safeguards.
- Architecture only; no implementation or deployment authorized.

## Planned backoffice absence and controlled case reassignment (Step 90 — approved A)
- Authorized backoffice operators or supervisors may record planned absence periods, including start and end date/time and appropriate absence category, without exposing unnecessary sensitive leave details to Tenants.
- During an effective absence, set operator availability to AWAY and exclude them from new automatic case assignment, regardless of ordinary presence/session state.
- Provide authorized backoffice supervisors a scoped overview of all unfinished cases assigned to an absent operator, with urgency, open tasks and statutory deadline risk highlighted.
- Permit supervisors to reassign selected cases individually or in bulk to eligible operators, with permission checks, recipient availability, an auditable reason, actor, timestamp, old/new assignment and notifications.
- Do not automatically reassign every case merely because absence begins; supervisors decide which cases can wait and which require coverage, while urgent deadline alerts continue independently.
- On return, restore eligibility according to the operator's effective availability; do not silently reclaim cases already reassigned. Preserve case and assignment history.
- Architecture only; no implementation or deployment authorized.

## Automatic case priority based on deadlines (Step 91 — approved A)
- Assign each active case an effective backoffice priority: CRITICAL (imminent statutory deadline risk), HIGH (short deadline or material blocker), NORMAL (ordinary processing), or LOW (no special urgency).
- Derive the minimum legally required priority from centrally governed statutory deadline rules, verified deadline-risk signals and relevant case blockers; recompute on material deadline, status or risk changes.
- Present backoffice work queues ordered by effective priority, with deterministic secondary ordering and visible reason/source for elevated priority.
- Authorized backoffice supervisors may manually raise priority with a recorded reason, actor and timestamp, but cannot lower effective priority beneath the automatically required statutory-risk floor or suppress independent legal alerts.
- Distinguish internal work prioritization from statutory due dates; priority adjustments do not extend deadlines, imply a filing was made, or override legal review blocks.
- Maintain full audit history of priority changes, computed inputs and manual overrides under Tenant access controls. Architecture only; no implementation or deployment authorized.

## Dedicated critical-case backoffice queue (Step 92 — approved A)
- Surface all active cases with effective CRITICAL priority in a dedicated, supervisor-visible backoffice queue regardless of their current operator assignment; enforce platform-role access and Tenant isolation.
- Immediately notify authorized backoffice supervisors when a case enters CRITICAL, including the reason, applicable deadline, current assignee, blocking conditions and a secure case link.
- Permit a supervisor to reassign a critical case to an eligible available operator with an auditable reason; reassignment does not change legal deadlines, suppress alerts, or bypass filing/legal-review blocks.
- If no eligible operator is available, retain the case in the critical queue as unresolved and continue repeated, deduplicated escalation until an authorized response or resolution is recorded.
- Remove a case from the critical queue only when its effective priority legitimately falls below CRITICAL due to verified change in underlying risk, not merely because someone acknowledged an alert or reassigned the case.
- Record queue entry/exit, risk basis, alerts, acknowledgement, escalation, assignment changes and timestamps in immutable audit history. Architecture only; no implementation or deployment authorized.

## Critical case assignment acknowledgement (Step 93 — approved A)
- A backoffice operator assigned a CRITICAL case must explicitly acknowledge taking responsibility for its urgent handling; assignment alone is not acknowledgement and acknowledgement does not mean the case has been processed, filed, or resolved.
- Require acknowledgement within 15 minutes of the applicable backoffice working schedule after assignment. Count only working minutes; if assigned outside working hours, the 15-minute clock starts at the next working period. Store the applicable schedule/time zone and audit calculation.
- If the acknowledgement deadline expires, immediately escalate to an authorized backoffice supervisor, with the current critical risk and assignment context. The supervisor may explicitly reassign the case to another eligible available operator; record actor, reason, old/new assignee, timestamps and acknowledgement lifecycle.
- A reassignment requires a fresh acknowledgement from the new assignee. Acknowledgement must be authorized for the current assignee and current assignment version, preventing stale confirmations after reassignment.
- Statutory deadline alerts and critical-case escalation remain active independently of business-hour acknowledgement timing; the 15-minute acknowledgement window must never imply a legal extension or suspend urgent legal-risk monitoring.
- Architecture only; no implementation or deployment authorized.

## Critical case first substantive action monitoring (Step 94 — approved A)
- After the current backoffice assignee explicitly acknowledges a CRITICAL case, require a qualifying, auditable substantive action within 30 minutes of applicable backoffice working time.
- Qualifying actions include an actual document-review decision, a supplementary-document request, or a recorded substantive preparation step for manual handoff to Tramisur. Merely opening/viewing a case, signing in, refreshing a page, or acknowledging assignment does not qualify.
- Use server-recorded action events tied to the case, acting operator and current assignment version; do not permit arbitrary client-side activity signals or backdated entries to satisfy the requirement.
- If no qualifying action is recorded before the 30-working-minute deadline, immediately alert an authorized backoffice supervisor for intervention or explicit reassignment, retaining an audit of the alert and response.
- On reassignment, the new operator must acknowledge the new assignment and then meet the applicable first-action requirement; stale actions from previous assignments cannot satisfy the new obligation.
- Preserve statutory deadline monitoring, CRITICAL queue visibility and legal-review blocks independently of this operational timer. The internal 30-minute window never extends a statutory deadline.
- Architecture only; no implementation or deployment authorized.

## Waiting for Tenant documents on critical cases (Step 95 — approved A)
- Introduce WAITING_FOR_TENANT as a documented operational waiting condition for cases requiring supplementary documents from the Tenant; preserve the distinct provider handoff lifecycle and statutory-risk priority.
- Record each outstanding requested document/item, request timestamp, responsible Tenant party, requester, delivery channel, applicable internal response expectation and immutable communication history.
- Notify authorized Tenant users through the existing case portal, allow uploads into the same case, preserve document versions, and trigger Backoffice review upon submission. Do not treat an uploaded replacement as approved until the established review gate is passed.
- While a valid, actionable Tenant request remains outstanding, do not classify the Backoffice operator as inactive merely because no further operator action is possible; maintain explicit supervision for other pending tasks and do not erase previously triggered acknowledgement or first-action failures.
- Preserve CRITICAL priority, dedicated critical queue, statutory alerts and supervisor escalation whenever legal deadline risk persists. Waiting for Tenant documents does not suspend, reset or extend any statutory deadline or remove legal-review restrictions.
- Use urgent, deduplicated Tenant reminders consistent with deadline severity and existing document reminder rules; log alerts and responses.
- When the Tenant submits requested material, clear or update the waiting condition as appropriate and return the case to the responsible Backoffice operator for substantive review, with notification and audit. Partial submission leaves unresolved items pending.
- Architecture only; no implementation or deployment authorized.

## Escalation for overdue Tenant document requests (Step 96 — approved A)
- When requested Tenant documentation remains outstanding, continue the existing automated, deduplicated in-app/email reminders to authorized Tenant contacts, with heightened urgency driven by verified statutory deadline risk.
- Notify authorized Backoffice supervisors when non-response threatens a statutory deadline; provide the missing-item list, request history, current priority, applicable deadline and responsible case operator.
- Permit supervisors to contact the Tenant through other approved channels (such as phone or email) and record each attempt, channel, timestamp, actor, outcome and any agreed follow-up, without exposing internal Backoffice notes to unauthorized Tenant users.
- Keep the WAITING_FOR_TENANT operational condition until required documentation is supplied and processed under the existing document-review workflow. Retain CRITICAL priority and dedicated queue visibility whenever the underlying legal risk persists.
- Tenant non-response, reminder delivery, supervisor acknowledgement and contact attempts must not pause or extend statutory deadlines, bypass legal-review blocks, imply official filing, or automatically resolve/close the case.
- Preserve immutable notification/contact history and Tenant isolation. Architecture only; no implementation or deployment authorized.

## Tenant-visible reasons for document-related case delays (Step 97 — approved A)
- For cases with WAITING_FOR_TENANT, show authorized Tenant users a clear localized status equivalent to "Waiting for your documentation", with an actionable list of outstanding requested documents, the original request date, and an upload action within the existing case.
- Show a suitable statutory-deadline urgency warning when verified deadline risk exists, without claiming a deadline extension or revealing legally uncertain dates as confirmed.
- On upload, show the submitted item's status as "Submitted — awaiting review" until the Backoffice completes its separate document approval process; do not auto-approve or imply the case is ready for Tramisur.
- If multiple requested items remain outstanding, keep the waiting status and identify the remaining items. Preserve requests, upload versions, review decisions and communications in the audit trail.
- Apply Tenant and branch-level authorization to all displayed case data and uploads. Never expose internal Backoffice notes, private supervisory escalation details, Tramisur coordination or cross-Tenant information in the Tenant portal.
- Architecture only; no implementation or deployment authorized.

## Tenant-facing estimated case completion date (Step 98 — approved A)
- Display a clearly labeled, non-binding estimated completion date in the authorized Tenant case portal when sufficient reliable information exists, derived from procedure type, document readiness, current workflow status, and supported processing-duration assumptions.
- Distinguish estimated completion from statutory deadlines, official filing dates, legal guarantees and contractual commitments; do not imply that a projected date changes any statutory requirement.
- Recalculate or withdraw the estimate when material inputs change, including outstanding Tenant documentation, Backoffice review, manual handoff to Tramisur, provider waiting time, or other documented delays. Explain meaningful changes in plain Tenant-visible language without exposing internal notes.
- During the phase-one manual Tramisur workflow, use only validated, maintainable assumptions or actual provider updates; do not invent provider SLAs, real-time integration signals or precise dates without sufficient evidence.
- If confidence or data sufficiency is inadequate, show an explicit 'Estimate currently unavailable' state instead of a fabricated date. Preserve estimation provenance, version and change history for authorized audit.
- Apply existing Tenant/branch access controls. Architecture only; no implementation or deployment authorized.

## Historical case data for completion-time estimates (Step 99 — approved A)
- Estimate procedure completion time from actual, comparable, completed AutoTramita cases, grouped by procedure type and relevant workflow characteristics, with data sufficiency and reliability checks.
- Capture real elapsed durations and distinct stages or delay reasons, including Tenant document waiting, Backoffice review, and manual Tramisur handoff/provider waiting, to avoid misleading blended averages.
- During initial operation or for insufficient samples, use versioned, explicitly approved Backoffice baseline durations rather than inventing historical statistics; clearly mark estimate provenance and uncertainty.
- Reassess estimates as the sample grows and relevant conditions change, without treating historical averages as legal deadlines, guarantees, provider SLAs or official completion promises.
- Exclude or appropriately handle erroneous, reopened, exceptional and incomplete cases; retain auditability of the method, inputs and approval of baseline assumptions. Use only privacy-preserving aggregated information across Tenants, without disclosing other Tenants' cases.
- If no trustworthy historical or approved baseline data exists, show 'Estimate currently unavailable' as decided in Step 98.
- Architecture only; no implementation or deployment authorized.

## Tenant-facing estimated completion range and confidence (Step 100 — approved A)
- Present an estimated completion interval (e.g., a range of working days and corresponding indicative calendar dates), rather than relying only on one precise completion date, whenever sufficient reliable information exists.
- Derive the range and its confidence classification (HIGH, MEDIUM or LOW) from comparable completed cases, data quality, sample sufficiency, dispersion and relevant case conditions. Broaden the interval or withhold the estimate when uncertainty warrants it; never fabricate numerical confidence or precision.
- When historical evidence is insufficient, show an explicitly approved, versioned baseline range clearly identified as an indicative assumption, or 'Estimate currently unavailable' if no trustworthy baseline exists.
- Recompute or withdraw ranges and indicative dates when material workflow conditions change, including outstanding Tenant documentation, Backoffice processing and manual Tramisur handoff; provide a comprehensible Tenant-visible explanation.
- Clearly distinguish estimates and confidence from statutory deadlines, guarantees, contractual service levels and confirmed official actions. Do not imply provider real-time integration in phase one.
- Audit estimate methodology/version, provenance and meaningful revisions while enforcing Tenant/branch data isolation.
- Architecture only; no implementation or deployment authorized.

## Tenant notification for material estimate delays (Step 101 — approved A)
- Notify authorized Tenant case participants via in-app notification and email when the newly estimated completion range ends more than two applicable working days after the upper bound of the previously displayed estimate range.
- Compare successive published, reliable ranges using the relevant working-day calendar and time zone; record the old/new range, basis for comparison and decision. Do not trigger misleading notifications when estimates are unavailable or unsupported.
- Include the updated indicative completion range, a clear non-sensitive explanation (such as outstanding Tenant documents or a documented wait for Tramisur), and a secure link to the case. Never disclose internal Backoffice notes or unverified provider claims.
- Smaller estimate adjustments update the portal without separate delay emails; deduplicate repeated notifications for the same material change while allowing new notices for subsequent material delays.
- Retain the prior estimate, recalculation reason, notification delivery attempts and timestamps in the audit trail.
- These estimates and notifications are informational, not statutory deadlines or service guarantees, and must not affect independent legal-deadline alerts, priority or review blocks.
- Architecture only; no implementation or deployment authorized.

## Tenant-facing case progress timeline (Step 102 — approved A)
- Provide authorized Tenant users a chronological, case-specific timeline of externally meaningful, confirmed milestones: case opened, documents submitted, Backoffice document review, manually handed to Tramisur, provider processing in progress, and procedure completed.
- Show actual recorded dates/times and localized milestone labels; mark stages as completed only on supporting workflow events or evidence. Do not imply a Tramisur handoff, official filing or completion before it actually occurred and was recorded by authorized Backoffice staff.
- Add supplementary-document requests, replacement submissions, material status changes and other relevant Tenant-actionable events to the timeline, preserving chronological history rather than overwriting earlier milestones.
- Permit repeat cycles (e.g., multiple document reviews and requests) without fabricating a strictly linear process; distinguish current status, pending future steps and confirmed completed milestones.
- Keep internal Backoffice work notes, supervisory escalations, private Tramisur correspondence, sensitive legal-review details and other Tenants' information out of Tenant-facing events. Enforce existing Tenant/branch permissions and audit event provenance.
- Architecture only; no implementation or deployment authorized.

## Tenant notifications for significant case milestones (Step 103 — approved A)
- Send authorized Tenant users in-app and email notifications for meaningful, verified case milestones: Backoffice approval of required documentation, actual manual handoff to Tramisur, provider processing confirmed from reliable Backoffice-recorded evidence, and confirmed procedure completion.
- Notify authorized Tenant users whenever supplementary documents or another Tenant action are required, with a secure case link and actionable description.
- Do not generate a separate email for every minor internal state change or timeline event; show such Tenant-visible changes on the case timeline without unnecessary message volume.
- Trigger notifications only after the corresponding milestone is durably recorded and supported; in phase one do not imply an automated Tramisur integration, filing, or completion that has not been confirmed.
- Deduplicate retries and repeated events, retain notification delivery attempts and history, and enforce Tenant/branch access and privacy controls; never expose internal Backoffice notes or private provider correspondence.
- Statutory deadline alerts, CRITICAL risk escalation and mandatory legal notifications remain independent and must not be suppressed by milestone-notification preferences.
- Architecture only; no implementation or deployment authorized.

## Tenant–Backoffice case-linked messaging (Step 104 — approved A)
- Provide two-way messaging between authorized Tenant users and authorized AutoTramita Backoffice participants directly within each case, for questions, clarifications, replies and supplementary-document requests.
- Persist messages chronologically with case reference, sender identity and role, creation timestamp, visibility classification and an auditable record; enforce Tenant and branch scope on every read, send and attachment operation.
- Notify relevant authorized recipients of new actionable messages through the established in-app/email notification framework, with deduplication and secure case links; preserve independent statutory deadline alerts.
- Maintain strictly separate channels or visibility boundaries for Tenant-visible messages, internal Backoffice notes, supervisory discussion and private Tramisur correspondence. Internal messages must never be exposed through Tenant APIs, notifications, exports or timeline events.
- Route requests for required documents through the established versioned checklist, upload and Backoffice approval workflow; a chat message or attachment alone must not mark documentation approved or a case submitted to Tramisur.
- Messaging does not imply legal representation, official filing, completion, or any pause/extension of statutory deadlines. Architecture only; no implementation or deployment authorized.

## Assigned Backoffice operator owns Tenant case messages (Step 105 — approved A)
- Route each new Tenant-visible case message to the case's currently assigned primary Backoffice operator; notify that operator and maintain a visible unread/actionable message queue.
- Authorized Backoffice supervisors may monitor unanswered messages across their scope and, if the assigned operator is unavailable, respond within the Tenant-visible conversation or explicitly reassign the case under existing audited reassignment controls.
- Do not automatically transfer case ownership solely because a message arrives while an operator is OFFLINE or AWAY; retain existing assignment and planned-absence rules.
- Flag messages involving statutory deadlines or other verified CRITICAL risks for prompt supervisor visibility and independent legal-deadline escalation; a message's wording alone must not silently change the verified statutory priority.
- Preserve message-to-case linkage, sender and responder identities, delivery/read state and timestamps, including assignment changes. Enforce Tenant/branch access and strict separation from internal Backoffice notes and private Tramisur communications.
- Architecture only; no implementation or deployment authorized.

## Tenant message response service targets (Step 106 — approved A)
- Track an internal first-substantive-response target for each actionable Tenant-to-Backoffice case message according to message priority: CRITICAL within 30 working minutes, HIGH within 2 working hours, NORMAL within 8 working hours, and LOW within 24 working hours.
- Measure elapsed time against the approved Backoffice working schedule, calendar and time zone; begin at receipt, count only working time, and calculate the due time deterministically even for messages received outside working hours.
- Record receipt timestamp, message priority and rationale, responsible Backoffice assignee, response deadline, first qualifying response timestamp, any supervisor escalation and immutable audit history.
- A meaningful authorized Backoffice reply addressing the message or explicitly requesting necessary clarification qualifies as a response; automated acknowledgements, read receipts and internal notes alone do not satisfy the response target.
- When the response target is breached, alert the authorized Backoffice supervisor and retain the outstanding message in the monitored queue until handled. Absence or reassignment does not silently reset or erase elapsed time or the breach.
- Enforce Tenant/branch scope, notification deduplication and existing message visibility boundaries. These are internal customer-service response targets, not statutory deadlines, official filing promises or legal time extensions; statutory alerts and critical-case escalations remain independent.
- Architecture only; no implementation or deployment authorized.

## Automatic Tenant message priority classification (Step 107 — approved A)
- Assign an initial message priority (CRITICAL, HIGH, NORMAL or LOW) from verified case statutory risk, case priority, the type of requested action and relevant message context; preserve message priority separately from case priority.
- Messages requiring action on a case with verified imminent statutory deadline risk receive suitably elevated priority and the Step 106 response target; classification must never reduce independent case-level legal alerts or deadline controls.
- Tenant text claiming urgency may flag the message for human review, but does not by itself establish or modify a verified statutory deadline, legal risk classification, or filing status.
- Authorized Backoffice supervisors may increase message priority with a recorded reason, actor and timestamp; do not permit a manual override to suppress the verified legal-risk minimum.
- Recalculate applicable response targets consistently when priority is legitimately raised, without silently resetting elapsed waiting time, masking an existing breach or implying a statutory deadline extension.
- Log classification basis, relevant inputs, changes and notifications; enforce Tenant/branch access and avoid exposing internal risk rules or other Tenants' information.
- Architecture only; no implementation or deployment authorized.

## Tenant-visible case message delivery, read and reply states (Step 108 — approved A)
- For each Tenant-authored case message, expose clear Tenant-facing states: SENT (durably accepted by AutoTramita), READ (first opened by an authorized Backoffice participant), and REPLIED (a qualifying Backoffice response has been sent).
- Record server-side sent, first-read and first-qualifying-reply timestamps, the authorized actor and corresponding message identifiers. Preserve a complete event history rather than overwriting audit facts.
- Mark READ only upon an authenticated, authorized explicit message view, not mere email delivery, notification preview, background polling, or access by an unauthorized user.
- Mark REPLIED only upon a substantive Backoffice reply associated with the message or its actionable conversation thread; automated acknowledgements, read receipts and internal notes do not qualify.
- Read receipts must not pause, satisfy or reset the Step 106 response target; REPLIED does not imply that the underlying case, requested documents, legal filing or procedure is resolved.
- Enforce Tenant/branch permissions and separate internal Backoffice/Tramisur communications from Tenant-visible message states. Architecture only; no implementation or deployment authorized.

## Tenant message attachments linked to case documentation (Step 109 — approved A)
- Allow authorized Tenant users to attach PDF, JPG and PNG files to Tenant-visible case messages, subject to the existing upload size, integrity, malware/security and file-type validation controls.
- Store each accepted attachment securely against its originating case and message with immutable file identity, uploader, timestamp, provenance and Tenant/branch access checks; preserve version and replacement history.
- Backoffice may associate a message attachment with the appropriate required or conditional procedure-checklist item, or request proper classification where ambiguous, without duplicating or silently overwriting an existing approved version.
- Message delivery or attachment upload must never automatically satisfy a mandatory checklist requirement, grant document approval, mark Backoffice readiness, or trigger manual Tramisur handoff. The normal PENDING_REVIEW / APPROVED / REJECTED / REPLACEMENT_REQUIRED review workflow remains authoritative.
- Notify the responsible Backoffice operator of actionable uploads and make status and any required correction visible to the authorized Tenant; avoid leaking private internal correspondence or attachments.
- Architecture only; no implementation or deployment authorized.

## Backoffice-to-Tenant document sharing in case messages (Step 110 — approved A)
- Authorized Backoffice users may attach and send PDF, JPG and PNG files to authorized Tenant participants through the Tenant-visible case conversation, including approved forms, receipts and confirmed final procedural documents.
- Before release, the sending Backoffice operator must explicitly confirm that the particular file/version is intended and permitted for Tenant disclosure; apply server-side authorization, case linkage and explicit Tenant-visible classification, with a default-deny boundary for internal-only material.
- Preserve document identity, source, version, sender, intended case/Tenant scope, timestamp, delivery event and audit history. Use secure access-controlled retrieval; do not disclose cross-Tenant or other-branch information.
- Internal Backoffice documents, supervisory notes, private Tramisur correspondence and provider-only evidence remain inaccessible to Tenant users unless a specific releasable document is deliberately reviewed and shared. A message attachment must never inherit public visibility merely from association with a case.
- Sharing a document through chat does not by itself certify authenticity, mark checklist items approved, prove official filing or completion, or alter statutory deadlines and case state.
- Apply existing attachment validation, notification deduplication and secure message delivery controls. Architecture only; no implementation or deployment authorized.

## Unified Tenant-visible case document archive (Step 111 — approved A)
- Each case provides an authorized Tenant-facing Documents tab that consolidates all documents explicitly available to that Tenant, regardless of whether uploaded via a checklist/form, attached to a Tenant message, or deliberately shared by Backoffice.
- Provide filtering and organization by document category, workflow/review status, and upload/share date, plus secure preview or download where the file format permits.
- Show the actual current review state and document version history; retain replaced, rejected and superseded versions with provenance and audit records, subject to authorization and retention rules. Never imply an attachment is approved solely because it appears in the archive.
- Reference a canonical case document and its versions from both messaging and checklist views to avoid uncontrolled copies, conflicting statuses or accidental replacement.
- Apply server-side Tenant, branch, case and document-level authorization on listing, preview, download, search and exports. Default-deny internal Backoffice materials, private Tramisur correspondence and provider-only files unless a specific document/version has been deliberately reviewed and released to the Tenant.
- Archive visibility and document sharing do not by themselves certify authenticity, change case state, prove official submission or alter statutory deadlines.
- Architecture only; no implementation or deployment authorized.

## Bulk download of Tenant-visible case documents as ZIP (Step 112 — approved A)
- Provide an authorized Tenant user with a Download all (ZIP) action from the case Documents tab to export the case documents and versions that user is permitted to access at the time of the request.
- Organize ZIP entries by document category and include a human-readable manifest with document name, category, current review status, version, and relevant dates; distinguish current from superseded versions without implying that rejected or pending files are approved.
- Apply server-side Tenant, branch, case, document and version authorization before inclusion and again when delivering the generated archive; exclude internal Backoffice notes, private Tramisur correspondence, provider-only files and any document not explicitly released to that Tenant.
- Generate archives securely with safe filenames/paths, size and resource limits, non-public temporary storage and short-lived access; prevent cross-Tenant leakage, stale permissions and unauthorized reuse of export links.
- Audit requesting user, case, request/completion timestamps, included document identifiers/versions, outcome and download access; respect retention and data protection requirements.
- ZIP export does not constitute document approval, official filing evidence, legal certification or a change in statutory deadlines.
- Architecture only; no implementation or deployment authorized.

## Tenant-downloadable informational case PDF report (Step 113 — approved A)
- Provide an authorized Tenant user with a downloadable PDF case report in addition to the ZIP document archive.
- Include case reference, procedure type, permitted vehicle details, current case status, verified Tenant-visible chronological milestones, and a categorized document inventory with actual review statuses.
- Include the actual Backoffice-recorded Tramisur handoff and procedure completion dates only when those events have been confirmed; do not invent or imply official submission or provider processing.
- List relevant official filing receipts and their available verified metadata, clearly distinguishing OFFICIALLY_VERIFIED, MANUALLY_ACCEPTED, pending review and verification failure; never present OCR-derived or unverified information as officially authenticated.
- Show the report generation date/time, applicable time zone and a clear disclaimer that this is an informational AutoTramita case summary, not a government-issued certificate or independent proof of official filing.
- Apply server-side Tenant, branch, case and field-level authorization at generation and download; exclude internal Backoffice notes, private Tramisur correspondence, other-Tenant data and unreleased documents. Audit report generation and download.
- Report generation must not change the underlying case, document, legal-deadline or official-receipt states. Architecture only; no implementation or deployment authorized.

## Unique report ID, QR verification and PDF integrity (Step 114 — approved A)
- Assign each generated informational case PDF report a globally unique, immutable report identifier and an issuance timestamp with explicit time zone; each regeneration is a distinct issued report/version.
- Embed a QR code linking to an HTTPS AutoTramita verification endpoint. The QR code must not contain personal data, case details, authorization credentials, or a publicly usable bearer token.
- Record a SHA-256 cryptographic digest of the finalized issued PDF bytes, report identifier, issuing system context, issue time, permitted case reference, and audit provenance. Verification must compare the submitted or downloaded PDF's digest with the trusted issuance record; simply scanning the QR code cannot establish that a separately held PDF has not been modified.
- Verification pages must enforce authentication and case/Tenant/branch authorization for nonpublic information; an unauthenticated QR scan must not disclose personal, vehicle or procedural details. Treat access and validation attempts as security-relevant events.
- Distinguish valid issued report, altered/nonmatching file, unknown identifier, and withdrawn/superseded report as applicable without rewriting original audit records. Report integrity verification is not a governmental attestation, official filing receipt, qualified electronic signature, or proof that a procedure is completed.
- Retain previous issued versions and their digests under applicable retention policies; secure generation, downloads and report verification against unauthorized cross-Tenant access.
- Architecture only; no implementation or deployment authorized.

## Immutable historical versions of issued case PDF reports (Step 115 — approved A)
- When relevant case data changes after a report has been issued, a newly generated informational PDF is a separate issuance with its own unique report ID, QR verification reference, timestamp and SHA-256 digest.
- Preserve every previously issued report and its trusted issuance record and original bytes without overwriting or mutating historical files, hashes or issuance timestamps, subject to applicable lawful retention and erasure obligations.
- Maintain an explicit ordered report-issuance history for each case. Distinguish the most recently issued report from earlier historical reports; the latter may no longer reflect the current case state, but remain authentic records of what was issued at that time.
- On authorized verification of an earlier report, display its original issue time and historical/superseded status with a clear warning that the current case data may have changed. Do not conflate a historical report with a forged, altered or legally revoked document.
- New issuance does not automatically invalidate an older report's integrity verification or alter official receipts, legal deadlines or case workflow states. Reverify any presented PDF against the hash of its own issuance, not the latest report.
- Enforce Tenant/branch access controls on history, downloads and verification, and audit report generation and verification events. Architecture only; no implementation or deployment authorized.

## Automatic final informational PDF report upon confirmed case completion (Step 116 — approved A)
- After an authorized Backoffice operator has confirmed case completion based on actual documented evidence and the case has durably entered the appropriate completed state, automatically generate a final informational PDF case report from the confirmed Tenant-visible case snapshot.
- Assign a new immutable report identifier, issuance timestamp, QR verification reference and SHA-256 digest according to Steps 113–115; preserve the finalized PDF bytes and issuance record.
- Make the completed report available in the authorized Tenant-facing case Documents archive and send a deduplicated in-app/email notification with a secure case link after successful issuance.
- Ensure idempotent generation for a given completion event, safe retries and a monitored failure queue; report-generation or notification failure must not falsely reverse a legitimately confirmed completion or generate duplicate reports. Surface failures to Backoffice for resolution.
- Any later case correction or post-closure review must preserve the original report unchanged; subsequent report issuance uses a new identifier and remains separately traceable under the historical-report policy.
- Report generation must never independently decide that a procedure is complete, prove official filing, certify a government action or suppress legal alerts; preserve Tramisur phase-one manual evidence and authorization controls.
- Architecture only; no implementation or deployment authorized.

## Post-completion Tenant–Backoffice messaging (Step 117 — approved A)
- Keep the authorized Tenant-visible case conversation available after a case is confirmed COMPLETED, subject to normal retention, Tenant/branch permissions and security controls.
- A new post-completion Tenant message creates a traceable Backoffice follow-up task linked to the closed case, assigned to the responsible eligible operator or routed to supervisor oversight if unavailable, with the established message response targets and notifications.
- Preserve the original COMPLETED status, completion evidence, issued reports, official receipts and historical timeline; receiving or replying to a message does not automatically reopen the case, alter legal deadlines, invalidate documents or trigger an official corrective filing.
- Backoffice reviews the follow-up and records its disposition, including whether clarification suffices or a controlled post-closure review/correction is necessary. Any official corrective action follows the previously approved supervisor authorization and legally authorized representative rules (Steps 72–73).
- Retain an auditable history of messages, follow-up tasks, decisions, responsible actors and timestamps, while strictly separating Tenant-visible correspondence from internal Backoffice and private Tramisur communications.
- Architecture only; no implementation or deployment authorized.

## Controlled post-completion error-report review (Step 118 — approved A)
- When an authorized Tenant user reports a possible error in a completed case, create a distinct auditable post-completion error-review task linked to the original case and the originating Tenant message; acknowledge receipt without treating the allegation as verified.
- Assign the task to the responsible Backoffice operator when eligible, with supervisor oversight and existing message-response targets; capture the alleged error, affected documents or case fields, evidence, reviewer findings and disposition.
- If the alleged error relates to work actually performed by Tramisur, Backoffice contacts Tramisur through the agreed secure manual phase-one channel, records the communication and evidence, and does not imply automated provider integration or unverified outcomes.
- Any official corrective filing or action requires prior approval by the appropriately scoped OWNER/ADMIN/MANAGER and, where legally required, execution by an appropriately authorized professional representative under Steps 72–73; ambiguous legal effects require central legal review.
- Notify the authorized Tenant of material review milestones and any additional information needed, without exposing internal notes or private Tramisur correspondence.
- Preserve the original COMPLETED case state, historical reports, receipts, documents and audit trail unless an independently authorized controlled post-closure process changes the applicable state. A report is not proof of an actual error, and opening review does not automatically invalidate any document or extend statutory deadlines.
- Architecture only; no implementation or deployment authorized.

## Tenant-visible post-completion error review tracking (Step 119 — approved A)
- In a completed case, expose an authorized Tenant-facing Error Report section for each submitted post-completion error allegation, linked to its review task and original case without automatically reopening the case.
- Show an auditable progression using REPORTED (received), UNDER_REVIEW (Backoffice investigation), WAITING_FOR_INFORMATION (specific Tenant evidence or clarification requested), CORRECTION_IN_PROGRESS (a properly authorized correction is underway), and RESOLVED (review concluded with recorded outcome).
- Only enter CORRECTION_IN_PROGRESS after the required scoped supervisor approval and any applicable legal-authority checks; do not imply a correction has been officially filed merely because work has begun.
- RESOLVED must display a clear outcome, distinguishing no error found, explanation provided, correction completed with evidence, or other documented disposition; resolution does not necessarily mean the alleged error was substantiated.
- Allow authorized Tenant users to provide supplementary information and documents through existing secure case messaging/upload controls; notify them of material status changes and actionable requests without exposing internal Backoffice notes or private Tramisur communications.
- Retain status transition timestamps, responsible actors, reasons, evidence and audit history. Preserve original COMPLETED case status and immutable issued reports unless a separately approved post-closure process changes them; do not suspend statutory deadlines through status changes.
- Architecture only; no implementation or deployment authorized.

## Post-completion error review response targets and escalation (Step 120 — approved A)
- For each post-completion error report, require Backoffice to begin a substantive investigation within one Backoffice working day of receipt, and target a documented review disposition within three Backoffice working days.
- Compute targets using the approved Backoffice working calendar, schedule and time zone; retain original receipt time, calculated start/review due times, first substantive review action, disposition time and complete audit history.
- Starting review requires an actual investigative action, not merely opening a notification or marking the report as read. A review disposition records findings and whether further authorized corrective work is required; completing an official correction is not presumed to occur within three days.
- Automatically alert the authorized Backoffice supervisor if the three-working-day review target is missed; surface missed start targets and unresolved tasks in the monitored queue, with recorded reasons and follow-up ownership. Operator absence or reassignment must not erase elapsed time or breaches.
- Reports indicating possible statutory deadline impact, invalid official evidence, or document validity risks must be promptly triaged through the existing CRITICAL/legal-review and statutory-alert mechanisms rather than waiting for the ordinary one-/three-day targets; allegations alone do not establish a verified legal violation.
- If Tenant information is missing, record WAITING_FOR_INFORMATION and the outstanding request, but do not silently erase the original target or imply a statutory suspension. Any justified internal clock treatment requires an explicit auditable rule.
- These are internal Backoffice service targets, not legal deadlines, guarantees of Tramisur response or government correction completion. Architecture only; no implementation or deployment authorized.

## Waiting for Tramisur in post-completion error review (Step 121 — approved A)
- Introduce WAITING_FOR_PROVIDER as a distinct post-completion error-review status when Backoffice has actually sent a documented question or evidence request to Tramisur through the agreed secure manual phase-one channel.
- Record provider identity, request purpose, responsible Backoffice operator, actual dispatch timestamp and time zone, permitted evidence reference, expected response if agreed, and the eventual provider response and receipt timestamp. Do not imply an automated Tramisur API or delivery confirmation without evidence.
- Keep the error-review task open and supervisor-visible, with separate clocks for the Step 120 internal review target and elapsed provider waiting time; entering WAITING_FOR_PROVIDER must not erase, reset or silently suspend an internal SLA breach.
- After two Backoffice working days without a recorded substantive provider reply, remind the assigned Backoffice operator; after four Backoffice working days, escalate to the authorized Backoffice supervisor. Compute against the approved Backoffice working calendar and deduplicate reminders.
- On receipt of a substantive provider response, record evidence and return the task to UNDER_REVIEW or the next properly authorized state; preserve full status history and audit.
- Tenant-facing updates may explain that an external provider response is awaited, without disclosing private Tramisur correspondence or unverified assertions. Statutory deadlines, CRITICAL risk escalations and legally required corrective actions remain independent of provider waiting.
- Architecture only; no implementation or deployment authorized.

## Tenant-facing provider-waiting status for error review (Step 122 — approved A)
- When a post-completion error review is genuinely in WAITING_FOR_PROVIDER under Step 121, show authorized Tenant users the neutral status label “Čeka se odgovor vanjskog pružatelja usluge” (localized appropriately for the portal).
- Show the verified date the Backoffice inquiry was actually sent and the latest confirmed Tenant-visible status change; never invent provider acknowledgment, response time, estimated resolution or official filing progress.
- Expose only a minimal, understandable waiting explanation. Do not disclose private Tramisur correspondence, individual contacts, internal Backoffice notes, provider-only evidence, or sensitive operational details.
- Keep the underlying case COMPLETED and the error review open, while internal provider-wait reminders, supervisor escalation, statutory alerts and critical-risk handling continue independently.
- When a verified provider response is recorded and the review leaves WAITING_FOR_PROVIDER, update the Tenant-visible status from actual workflow events and apply established significant-event notification rules.
- Enforce Tenant/branch/case authorization, audit all status transitions, and avoid cross-Tenant disclosures. Architecture only; no implementation or deployment authorized.

## Tenant notification after Backoffice review of Tramisur response (Step 123 — approved A)
- In phase one, Backoffice manually records Tramisur's actual response through the agreed secure channel, including receipt time, responsible operator, source/evidence reference and review outcome; no automated Tramisur integration or implied provider confirmation.
- Notify authorized Tenant users via in-app and email only after Backoffice has verified and recorded a provider response that materially changes the Tenant-visible error-review status or requires a specific Tenant action or document.
- Do not send a Tenant notification for purely internal provider correspondence, repetitive acknowledgements or responses with no externally meaningful effect. Keep the portal's permitted status accurate and evidence-based.
- Never forward private Tramisur correspondence, individual provider contacts, internal Backoffice notes or unapproved evidence to the Tenant; compose a concise approved Tenant-facing explanation and actionable request when relevant.
- Deduplicate notification attempts, preserve audit records of the source response, verification, decision to notify, recipients and delivery, and enforce Tenant/branch/case authorization.
- Statutory deadlines, CRITICAL escalations and mandatory legal alerts remain independent and may not be delayed by routine provider-message review. Architecture only; no implementation or deployment authorized.

## Voluntary Tenant service rating after case completion (Step 124 — approved A)
- After a case is confirmed COMPLETED, permit an authorized Tenant user with case access to submit an optional private AutoTramita service rating of 1–5 stars and an optional free-text comment linked to that specific case.
- Ratings and comments are not public testimonials, must not be exposed across Tenants, and are visible only to appropriately authorized Backoffice quality/supervisor personnel and the submitting Tenant according to case access rules.
- Participation is voluntary and must not affect case processing, statutory deadlines, post-completion error reports, correction rights, or access to documents.
- Preserve submission timestamp, actor, case/tenant linkage and audit history; handle comments as potentially sensitive user-supplied content with authorization and safe rendering.
- The feedback measures the AutoTramita service experience, not an official authority decision or independently verified Tramisur performance. Any subsequent public publication would require a separate policy and appropriate permission.
- Architecture only; no implementation or deployment authorized.

## Low-rating Backoffice quality follow-up (Step 125 — approved A)
- When an authorized Tenant user submits a voluntary 1- or 2-star AutoTramita service rating for a completed case, automatically create one auditable Backoffice quality-review task linked to the rating and case; ensure idempotency and avoid duplicate tasks from retries.
- Notify the authorized Backoffice supervisor and assign an eligible responsible operator for review of the rating, optional comment, and relevant case history; the operator may contact the Tenant where appropriate and records the investigation, actions, and outcome.
- Keep feedback private, apply case/Tenant access controls, preserve the original rating and audit trail, and do not automatically reopen or change the completed case or alter legal deadlines.
- If feedback plausibly alleges a case error, permit Backoffice to initiate the separate controlled post-completion error-review process under Steps 118–123; a low score alone does not establish an error or authorize official correction.
- Track the quality-review task separately from official case/procedure statuses, with supervisor oversight and no automatic provider communication or corrective filing.
- Architecture only; no implementation or deployment authorized.

## Low-rating customer contact service target (Step 126 — approved A)
- For every 1- or 2-star service rating that triggers the Step 125 quality-review task, Backoffice must substantively review the complaint and make a genuine, documented attempt to contact the Tenant within one Backoffice working day of rating receipt.
- Calculate the internal deadline using the approved Backoffice working calendar and time zone. Record receipt, due time, reviewer, contact attempt timestamp, channel, permitted contact destination/reference and outcome; merely opening the task or sending an automated acknowledgment does not satisfy the target.
- If no qualifying attempt is recorded by the deadline, automatically notify the authorized Backoffice supervisor and retain the overdue task until appropriately addressed; operator absence or reassignment does not erase the original deadline or breach.
- If the Tenant does not respond, document the attempt and leave the quality-review task open until an authorized, reasoned disposition is recorded; do not falsely imply successful contact or resolution.
- Preserve privacy, Tenant and case authorization, audit history, and a separation from statutory deadlines, the completed case status and any distinct post-completion error-review process. This is an internal service-quality target, not a legal response deadline.
- Architecture only; no implementation or deployment authorized.

## Central Backoffice customer satisfaction dashboard (Step 127 — approved A)
- Provide an access-controlled central Backoffice quality dashboard for authorized supervisors, using actual voluntary case-linked ratings and Step 125 quality follow-up tasks.
- Show average star rating together with rating count, proportion of 1–2-star ratings, open and resolved low-rating quality-review tasks, average elapsed Backoffice working time to the first qualifying documented Tenant contact attempt, and monthly satisfaction trends.
- Support filtering by reporting period and procedure type; use consistent definitions and denominator disclosure, and show insufficient sample size rather than misleading precision when applicable.
- Distinguish an attempted contact from successful contact, and quality-review task closure from substantive resolution of a case error; avoid treating missing voluntary ratings as neutral or positive feedback.
- Restrict aggregate dashboard access to appropriately authorized AutoTramita Backoffice quality/supervisory personnel, apply minimum-cell-size or equivalent safeguards against identifying individual Tenants in narrow breakdowns, and prevent cross-Tenant data disclosure.
- Preserve traceability to authorized underlying tasks, audit dashboard access where appropriate, and do not alter completed cases, statutory deadlines, or provider workflows.
- Architecture only; no implementation or deployment authorized.

## Internal Backoffice operator quality analytics (Step 128 — approved A)
- Provide authorized Backoffice supervisors with internal, access-controlled operator-level quality analytics: active/processed/completed case counts, comparable case processing durations, adherence to defined internal service targets, counts of associated complaints and low service ratings, and trends over time.
- Attribute metrics carefully across primary operator assignments, reassignment, periods of responsibility and shared work; distinguish correlation with a case rating from proof of individual fault.
- Segment or contextualize by procedure type, case complexity, verified statutory urgency, missing Tenant documents, Tramisur/provider waiting periods, operator availability and other externally controlled delays; avoid misleading unadjusted rankings.
- Include appropriate sample sizes and definitions, distinguish attempts from successful contacts, and avoid automatically translating voluntary ratings or complaints into disciplinary conclusions.
- Restrict individual-level access to appropriately authorized supervisors and personnel with a legitimate operational need, audit sensitive access, and comply with applicable Spanish/EU employee privacy, transparency and data-protection requirements; no public publication or cross-Tenant leakage.
- Analytics support human oversight and service improvement only: no automated employment, compensation, sanction or performance decisions. No changes to statutory deadlines or case legal outcomes.
- Architecture only; no implementation or deployment authorized.

## Personal Backoffice operator performance dashboard (Step 129 — approved A)
- Give each active authorized Backoffice operator a private personal dashboard showing their own processed and completed case counts, comparable average handling duration, internal service-target adherence rate, voluntary service ratings associated with their assigned cases, and month-by-month trends.
- Enforce server-side per-user scoping: operators may see only their own metrics, not other operators' individual statistics. Authorized Backoffice supervisors retain access to team and operator analytics under Step 128.
- Distinguish actual operator-controlled handling time from Tenant-document and Tramisur/provider waiting periods, and contextualize metrics by case type, complexity, statutory urgency, assignment/reassignment and sample size.
- Ratings associated with an operator's cases are not automatically attributable to that operator's conduct; avoid presenting complaints or voluntary feedback as verified individual fault or a definitive performance score.
- Keep the dashboard internal, privacy-conscious, auditable and informational only; do not trigger automated employment decisions or change case outcomes, statutory deadlines or quality-review workflows.
- Architecture only; no implementation or deployment authorized.

## Personal operator deadline and task alerts (Step 130 — approved A)
- On each authorized Backoffice operator's personal dashboard, provide a consolidated, actionable view of their assigned cases and tasks with approaching or breached deadlines, linking each alert to the corresponding authorized case/task.
- Display risk-aligned priority: CRITICAL for confirmed or reasonably suspected imminent statutory risk under existing legal-risk controls; HIGH for urgent work and breached internal service targets; NORMAL for routine approaching internal targets. Respect the centrally defined priority floor and avoid downgrading statutory risks.
- Show verified due time, relevant task/case, concise reason and overdue/approaching state, calculated using the applicable legal or Backoffice working calendar as appropriate; do not conflate statutory deadlines with internal service targets.
- Scope operator views to assigned authorized work. Supervisors retain oversight of critical/unassigned queues, and operator logout, absence or reassignment must not silence independent statutory alerts or required supervisor escalations.
- Keep existing in-app/email notification and escalation mechanisms active; dashboard visibility alone does not count as acknowledgment, substantive action or completion. Audit material status and priority changes.
- Architecture only; no implementation or deployment authorized.

## Personal Backoffice task list with filters (Step 131 — approved A)
- Provide each authorized Backoffice operator a “My Tasks” view containing their assigned, permitted case-linked operational tasks, with filters for priority, task status and deadline and sorting by earliest due time or receipt/creation time.
- Distinguish tasks actively actionable by the operator from those waiting on Tenant documents (WAITING_FOR_TENANT / WAITING_FOR_INFORMATION) or an actual Tramisur response (WAITING_FOR_PROVIDER), using verified workflow state rather than inference.
- Each task must link directly to its authorized case and task detail; enforce server-side Backoffice assignment and case access controls for both list results and navigation.
- Always prominently surface CRITICAL statutory-risk work independently of optional filters or sorting; filters may organize routine work but must not conceal mandatory critical warnings or suppress existing supervisor escalation and statutory notifications.
- Display the relevant verified due time, whether a deadline is statutory or an internal service target, and appropriate overdue state; never treat merely opening a task as an acknowledgment, substantive action or completion.
- Maintain audit of meaningful task state/assignment changes. Architecture only; no implementation or deployment authorized.

## Manually marking assigned Backoffice tasks in progress (Step 132 — approved A)
- Permit an authorized Backoffice operator to manually transition a task assigned to them into IN_PROGRESS, subject to valid workflow transitions and server-side assignment/access checks.
- Record actor, task/case linkage, transition timestamp and time zone, prior and new status, and elapsed time since assignment/creation; retain immutable audit history across subsequent pauses, reassignments and completions.
- IN_PROGRESS expresses the operator's declared working state only. Changing to this status does not itself count as a substantive action, a CRITICAL acknowledgment, successful contact, statutory filing, or task completion under existing service-level controls.
- Internal and statutory deadlines, urgent alerts and supervisor escalations continue independently; no clock is reset, suspended or satisfied merely by marking IN_PROGRESS.
- Preserve distinctions between active work and genuine WAITING_FOR_TENANT, WAITING_FOR_INFORMATION or WAITING_FOR_PROVIDER conditions, and do not imply automated time tracking of actual effort solely from status duration.
- Architecture only; no implementation or deployment authorized.

## Manual task pause with mandatory reason (Step 133 — approved A)
- Permit an authorized assigned Backoffice operator to move an eligible IN_PROGRESS task to PAUSED only with a mandatory meaningful reason, such as an interruption or internal consultation, and subject to server-side workflow and assignment authorization.
- Record the actor, original and new status, reason, pause start and end timestamps/time zones, and cumulative paused duration, preserving the full audit history and distinguishing declared pause duration from actual working effort.
- Require an explicit authorized transition out of PAUSED to resume work or move to an appropriate genuine waiting state; do not silently infer that a provider or Tenant is being awaited from a generic pause.
- Keep paused tasks visible in the operator's task list and authorized supervisor oversight, including any due/overdue flags.
- PAUSED must not automatically stop, extend, reset or satisfy statutory deadlines, internal service targets, CRITICAL acknowledgments, substantive-action targets, alerts or escalations. Any exception to an internal clock would require a separately approved auditable rule.
- Architecture only; no implementation or deployment authorized.

## Open design questions
- Escalation recipients and severity for overdue deadlines.
- Specific source connectors and authoritative mappings of procedures, competent authorities and applicable jurisdictions.
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
33. Configured authoritative calendar sources are checked at least every 24 hours when available, with check timestamps, results and errors recorded.
34. New or changed calendars enter PENDING_REVIEW and notify platform administrators; ACTIVE versions remain unchanged pending approval.
35. Failed checks retry without publishing unverified data, and persistent failures are surfaced to administrators.
36. Statutory deadline calculations select the calendar based on procedure and competent authority rather than dealership address by default.
37. Each calculation retains competent authority, jurisdiction, calendar version and rule version for audit.
38. Uncertain authority or calendar applicability triggers LEGAL_REVIEW_REQUIRED and prevents presenting a provisional deadline as legally confirmed.
39. New cases receive a suggested competent authority based on approved procedure, location and case-fact mappings.
40. Authorized users may correct the suggested authority only with a recorded reason and full audit history.
41. Corrections that affect deadlines trigger controlled rule/calendar reassessment; uncertainty flags LEGAL_REVIEW_REQUIRED rather than certifying a guess.
42. A centrally governed registry stores administrative authority names, available official identifiers, jurisdictions and supported procedures for all Tenants.
43. Only authorized platform administrators may approve registry changes, with official source provenance, version history and audit records.
44. Registry changes do not silently change existing cases or confirmed statutory deadlines.
45. Official authority sources are monitored periodically, with candidate changes retained as PENDING_REVIEW and old/new differences shown to platform administrators.
46. Only authorized platform administrators approve publication of registry changes; source provenance, prior versions and approvals remain auditable.
47. Registry monitoring never silently changes existing case authority assignments or confirmed legal deadlines.
48. Available verified authority sources are checked at least once every 24 hours, recording timestamps, outcomes and errors.
49. Detected changes remain PENDING_REVIEW until approved, and the last approved registry stays active meanwhile.
50. Failures are retried and persistent errors escalated without publishing unverified authority data.
51. Imminent authority-jurisdiction changes are flagged URGENT_REVIEW and promptly escalated to platform administrators.
52. Activation requires verified legal basis, effective date, territorial/procedural scope and transitional applicability, with approval audit.
53. Potentially affected existing cases are flagged for review; no automatic authority reassignment or silent deadline changes occur.
54. Approved authority changes trigger targeted in-app and email notices only to Tenants with potentially affected cases, scoped to responsible employees and authorized supervisors.
55. Notices describe the change, effective date and securely link to affected cases; Tenant and branch isolation is enforced.
56. Notification delivery attempts and outcomes are audited, and notices never silently modify case authority or statutory deadlines.
57. Potentially affected cases receive AUTHORITY_REVIEW_REQUIRED until an authorized user explicitly confirms authority or initiates a correction.
58. Review records actor, timestamp, outcome and rationale; legally authority-dependent actions remain blocked while independent work continues.
59. Unresolved legal ambiguity escalates to LEGAL_REVIEW_REQUIRED, and acknowledgment never silently modifies statutory rules or triggers blocked actions.
60. Outstanding AUTHORITY_REVIEW_REQUIRED cases trigger daily in-app and email reminders to the responsible authorized employee.
61. After 48 elapsed hours without review completion, authorized supervisors receive an escalation, scoped to Tenant/branch permissions.
62. Reminders and escalation continue as applicable until documented review resolution, and legally dependent actions remain blocked meanwhile.
63. An unresolved authority review with a confirmed statutory deadline less than 24 hours away triggers CRITICAL_DEADLINE_RISK and immediate targeted in-app/email alerts.
64. Critical cases appear with highest priority for authorized users; uncertain deadlines are explicitly labeled and escalated for urgent legal verification.
65. Critical alerts do not change deadlines, bypass legal blocks or automatically execute actions, and all alerts are auditable.
66. An unresolved case past a legally confirmed statutory deadline is flagged STATUTORY_DEADLINE_EXCEEDED and shown in an authorized overdue queue.
67. Responsible employees and authorized supervisors receive immediate in-app/email escalation; due date, overdue duration and review activity are audited.
68. Deadline expiry triggers procedure-specific review of legal consequences and remedies, without assuming the case is irrecoverably lost or automatically executing actions.
69. Responsible employees may submit overrun explanations and evidence but cannot independently close the overrun review.
70. Closure requires an authorized OWNER/ADMIN or appropriately scoped MANAGER; unresolved legal ambiguity requires central legal review.
71. Closure retains permanent overrun history and audit evidence, and does not silently change statutory deadlines or lift unrelated legal blocks.
72. Cases can retain official filing receipts with original document, competent authority, registration identifier and submission timestamp.
73. Verified official submission time is compared with the applicable statutory deadline; an authorized supervisor may resolve an overrun alert on proof of timely filing.
74. Conflicting or unverifiable evidence requires review; the original alert, evidence, decision and correction history remain auditable without mislabeling a disproven breach.
75. Supported filing-receipt PDFs/images undergo attempted automatic extraction of filing timestamp, registration number and authority, with uncertainty recorded.
76. When an official CSV or other supported validation mechanism exists, authenticity is checked separately from text extraction; statuses are VERIFIED, PENDING_REVIEW and VERIFICATION_FAILED.
77. Failed or uncertain extraction/authenticity requires manual review, and no deadline alert is automatically cleared solely from OCR output.
78. Temporary unavailability of official CSV verification retains PENDING_REVIEW and triggers controlled automatic retries with auditable attempts.
79. Service unavailability is not treated as failed authenticity; independent case work may continue, but the receipt cannot be represented as verified.
80. Persistent failures trigger authorized manual review and deadline-risk alerts when relevant, without automatically clearing deadline warnings.
81. An affirmative invalid CSV or official document mismatch sets VERIFICATION_FAILED and immediately alerts responsible authorized case users and supervisors.
82. Failed verification prevents treating the receipt as authenticated proof of timely filing and requires documented manual review, with escalation of legal uncertainty.
83. Preserve original document, official validation result and correction history; invalid CSV alone is not treated as proof of intentional fraud.
84. Authorized employees may correct incorrectly extracted CSV values against the original receipt, with old/new values and actor recorded.
85. CSV correction triggers a fresh official verification while the document remains unverified pending success or authorized alternative evidence review.
86. Prior verification failures remain auditable and CSV correction alone never clears statutory deadline alerts or legal blocks.
87. Official filing receipts without CSV are accepted for evidence review and checked using other official mechanisms where available.
88. When electronic official validation is unavailable, authorized supervisors may manually accept documented evidence, clearly distinguished from official verification.
89. Legal ambiguity escalates to central legal review; evidence and decisions remain auditable without automatic removal of deadline alerts or legal restrictions.
90. Filing receipts are checked against available case-specific identifiers, including VIN, plate, applicant, procedure and application reference.
91. Material contradictions set DOCUMENT_CASE_MISMATCH and block automatic acceptance; missing data is reported as an incomplete match assessment.
92. Authorized supervisory review is required to resolve mismatches, with full comparison evidence and audit trail retained.
93. Potential duplicate receipts are detected by document fingerprint, CSV or issuer-scoped official registration identifiers and flagged POSSIBLE_DUPLICATE_RECEIPT.
94. Reuse for genuinely related cases requires authorized supervisory review and documented justification, not automatic rejection.
95. Cross-Tenant duplicate detection must not reveal any other Tenant's identity or confidential information; all review outcomes are audited.
96. Previously verified receipts are periodically rechecked for official revocation where the issuing authority supports it.
97. Confirmed official cancellation marks RECEIPT_REVOKED, immediately alerts authorized case users and prompts deadline/legal reassessment.
98. Service unavailability is not revocation; preserve all verification history and route uncertain legal effects to central review without automatically declaring a missed deadline.
99. Official receipt revocation identifies all linked cases, including privacy-safe cross-Tenant associations, and flags REVOKED_RECEIPT_REVIEW_REQUIRED per affected case.
100. Each affected case receives an independent legal/deadline assessment and targeted notifications without exposing another Tenant's data.
101. Revocation alone does not establish invalidity of all linked proceedings; preserve evidence, review decisions and audit history.
102. Confirmed receipt revocation affecting a completed case creates a distinct POST_CLOSURE_REVIEW_REQUIRED review without rewriting the original closure status.
103. Authorized supervisors assess consequences, escalating legal ambiguity centrally, with original completion and subsequent review actions independently audited.
104. Revocation does not automatically void a completed proceeding or authorize corrective filings.
105. Employees can propose post-closure corrections but execution requires prior approval by an appropriately scoped OWNER/ADMIN/MANAGER.
106. Approval does not replace legally required Gestor Administrativo or other representative authorization; unresolved legal questions block dependent actions.
107. Original closure, correction approval, legal authority, filing evidence and outcomes remain independently auditable.
108. A centrally governed professional representative registry records identity, applicable registration and Colegio, verified status, scope and evidence.
109. Representative-to-Tenant associations remain isolated; client/procedure-specific representation mandates are tracked separately.
110. Filing authorization independently checks required professional entitlement and client mandate, blocking submission if either legally required check is unresolved.
