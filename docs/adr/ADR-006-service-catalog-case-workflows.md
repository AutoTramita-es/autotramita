# ADR-006: Configurable service catalog and case workflows

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
AutoTramita.es supports multiple vehicle administration services with different required documents, forms, workflows, fees and professional partners.

## Decision
- Maintain a centrally governed, versioned service catalog.
- Each service has configurable input fields, required documents, eligibility and workflow rules.
- Cases retain the service definition/version used when opened so later catalog edits do not silently change in-flight requirements.
- Support case submission without account registration; later secure linking to a verified user identity.
- Separate statutory taxes/fees from AutoTramita service charges.
- Regulated professional actions are routed to authorized external gestoría partners where required; platform ownership of workflow does not imply regulatory authorization.
- Ficha Reducida is procured by AutoTramita from a qualified external engineer as an integrated service, rather than requiring the end customer to arrange it.

## Consequences
Dynamic forms, versioned workflows and audit history are core domain concerns, not ad hoc frontend logic.

## Open decisions
Exact service list, workflow state machine, escalation/SLA rules, external partner APIs and per-service regulatory requirements.

## Scope
Product architecture only.
