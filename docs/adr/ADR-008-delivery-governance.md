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
