# F1 reconciliation plan — 2026-11-24
REC-01 APPROVED AND COMPLETE; REC-02–07 PROPOSED, NOT AUTHORIZED.
[Audit findings](F1-RECONCILIATION-AUDIT.md) | [AT-01](../specifications/AT-01-foundation-infrastructure.md) | [Execution brief](../specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md) | [G6](../G6-EXECUTION-ORDER.md)

| Gate | Scope | Exit evidence |
|---|---|---|
| REC-01 | Preserve existing branch | Archive archive/f1-foundation-2026-11-24 created at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a; GitHub compare with f1/foundation identical, 0 ahead/behind, no files changed. Audit and plan on main. |
| REC-02 | Reconcile documentation and authorization history | Owner confirms historical authorization or marks unknown; reconcile G6 and blueprint without rewriting history; establish current baseline and explicit task permissions. |
| REC-03 | Separate maintenance and unrelated scope | Identify provenance and separately authorized changes; propose isolated maintenance branch and clean F1 candidate from current main; review .gitleaksignore narrowly; no live service changes. |
| REC-04 | Align T01–T05 | Reuse reviewed existing code, exact toolchain pins, four DB roles, worker/platform tests, real PG16 RLS evidence; review migration 0002 before inclusion. Individual task approvals and CP01–05. |
| REC-05 | Align T06–T07 | Implement accepted O02/O03/O18/O19, resolve only outstanding fingerprint/cursor/persistence choices before changes; real Redis7 tests and API contracts; CP06–07. |
| REC-06 | Align T08–T10 | OTel hook, health scope, OpenAPI, pinned CI and full regression evidence; CP08–10. |
| REC-07 | Final F1 acceptance | AC01–15 evidence, clean scope, owner review and separate merge authorization. No deployment implied. |

## Rules
Preserve original and archive branches. No force push, reset, automatic merge/rebase/cherry-pick. Proposed clean candidate feat/at01-f1 from current main, selective reviewed reuse only after explicit authorization. No duplicate implementation by default. Separate maintenance operations from F1; live state and authorization unverified. No production/shared DB, Redis or infrastructure changes. No destructive migrations. Keep 15 deferred AT-01 decisions open. Each gate stops for owner review; REC-01 approval does not authorize REC-02 or subsequent implementation. Existing T01-only authorization does not expand through this plan; do not execute until reconciliation clarifies the baseline.
Archive is a Git reference, not an independent offsite backup or protected immutable tag. No branch protection changes authorized.
