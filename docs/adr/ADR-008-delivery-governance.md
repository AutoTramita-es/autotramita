# ADR-008: Architecture-first, module-by-module delivery with Claude Code

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
The product owner and ChatGPT develop the product concept and architecture. Claude Code is responsible for implementing approved work.

## Decision
- Product owner approves business and architecture decisions.
- ChatGPT prepares ADRs, domain models, functional specifications, API contracts, implementation tasks and acceptance criteria, and maintains approved architecture documentation in GitHub.
- Claude Code writes implementation code, database migrations, tests and supporting technical changes against approved specifications.
- Use a hybrid sequence: settle cross-cutting foundation ADRs first, then design and implement one bounded module at a time.
- A module implementation begins only after relevant ADRs, scope, data models, API contract, acceptance criteria and dependencies are sufficiently defined and approved.
- Claude Code must not silently change accepted architectural decisions; unresolved questions are raised for decision.
- Review code and tests before accepting a module; prefer pull requests and traceable changes.
- Distinguish `Accepted` decisions from `Proposed` drafts; supersede decisions explicitly rather than rewriting history.

## Consequences
Architecture decisions stay separate from implementation; delivery can proceed incrementally without designing every feature up front.

## Next candidate module
Tenant and its dependencies on User and TenantMembership; branch/business-unit structure remains to be decided.

## Scope
Governance only; no implementation authorized by this ADR.

## Amendments
- **2026-11-25 (owner, F2-T09-REC final MFA decision):** recorded as an application of this ADR, not a change of its rules. The owner approved changes to accepted decisions D22, D23 and D41 explicitly before the code was written (record in `docs/design/F2-EXECUTION-ORDER.md`). The decision also states, for this and later work: a security finding is not downgraded while a takeover remains possible, and a new architectural component (for example a Keycloak extension) needs its own justification and authorization before it is implemented.
- **2026-11-25 (owner, Keycloak Security Provider Authorization):** the owner approved an own minimal Keycloak provider in Java using Keycloak SPIs and an own reproducible Keycloak image (pinned upstream image and build image), integrated in Local CI and GitHub Actions, and amendments of I07, D22, D23, D41 and D43 (recorded as D44 in the F2 decision register). Not approved: a Keycloak fork, a new external service, a new persistent database, new public ports. Keycloak classifies the SPIs used as internal (no compatibility promise); every Keycloak upgrade therefore runs the provider's mandatory regression tests before it is accepted.
- **2026-11-25 (owner, F2-T09-REC Final Completion Order):** the AutoTramita Keycloak image is scanned with a pinned Trivy in CI; the exposure of an upstream image is not accepted in place of a scan, and a CRITICAL or HIGH finding passes only with a time-limited acceptance by the owner. A Keycloak upgrade needs its own authorization. Narrow security corrections of the Local CI broker are approved as part of that work.
- **2026-11-25 (owner, F2-T09-REC Keycloak Security Upgrade):** the owner authorized the direct upgrade of Keycloak from 26.4.7 to 26.8.2 (D45 in the F2 decision register) and a **one-time exception** to the rule that a release is pinned only 14 days after its publication, for development, tests and CI only. The exception does not authorize a production deployment and does not change the upgrade policy: the next upgrade follows the 14-day rule again. A remaining HIGH or CRITICAL finding is never accepted automatically; only the owner accepts one, for a limited time, after an individual analysis. AC-CTX-01 asks for preserved F1 security guarantees with documented equivalence instead of literally unchanged tests.

