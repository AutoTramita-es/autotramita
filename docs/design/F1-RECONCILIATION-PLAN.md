# F1 reconciliation plan — 2026-11-24
REC-01 AND REC-02 APPROVED AND COMPLETE (documentation); REC-03–07 PROPOSED, NOT AUTHORIZED.
[Audit findings](F1-RECONCILIATION-AUDIT.md) | [AT-01](../specifications/AT-01-foundation-infrastructure.md) | [Execution brief](../specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md) | [G6](../G6-EXECUTION-ORDER.md)

| Gate | Scope | Exit evidence |
|---|---|---|
| REC-01 | Preserve existing branch | Archive archive/f1-foundation-2026-11-24 created at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a; GitHub compare with f1/foundation identical, 0 ahead/behind, no files changed. Audit and plan on main. |
| REC-02 | Reconcile documentation and authorization history | COMPLETE: historical broad authorization marked UNVERIFIED; G6, blueprint, AT-01 and brief updated on main; existing implementation preserved, CP01 blocked, no new execution permission. |
| REC-03 | Separate maintenance and unrelated scope | Identify provenance and separately authorized changes; propose isolated maintenance branch and clean F1 candidate from current main; review .gitleaksignore narrowly; no live service changes. |
| REC-04 | Align T01–T05 | Reuse reviewed existing code, exact toolchain pins, four DB roles, worker/platform tests, real PG16 RLS evidence; review migration 0002 before inclusion. Individual task approvals and CP01–05. |
| REC-05 | Align T06–T07 | Implement accepted O02/O03/O18/O19, resolve only outstanding fingerprint/cursor/persistence choices before changes; real Redis7 tests and API contracts; CP06–07. |
| REC-06 | Align T08–T10 | OTel hook, health scope, OpenAPI, pinned CI and full regression evidence; CP08–10. |
| REC-07 | Final F1 acceptance | AC01–15 evidence, clean scope, owner review and separate merge authorization. No deployment implied. |

## Rules
Preserve original and archive branches. No force push, reset, automatic merge/rebase/cherry-pick. Proposed clean candidate feat/at01-f1 from current main, selective reviewed reuse only after explicit authorization. No duplicate implementation by default. Separate maintenance operations from F1; live state and authorization unverified. No production/shared DB, Redis or infrastructure changes. No destructive migrations. Keep 15 deferred AT-01 decisions open. Each gate stops for owner review; REC-01 approval does not authorize REC-02 or subsequent implementation. Existing T01-only authorization remains historical and blocked at preflight; no implementation until explicit subsequent gate/task approval.
Archive is a Git reference, not an independent offsite backup or protected immutable tag. No branch protection changes authorized.

## REC-02 closure
REC-02 (2026-11-24): F1 implementation exists on f1/foundation at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a, preserved identically in archive/f1-foundation-2026-11-24; not merged or accepted. Historical broad authorization quoted in c467005 ("Autoriziram F1 prema G6-EXECUTION-ORDER.md") is UNVERIFIED: repository record exists, original owner instruction not established; neither confirmed nor invalidated retroactively. Later explicit T01-only authorization b6462e4 / 0973e24 remains recorded; CP01 blocked in preflight, no new implementation authorized or executable during reconciliation. T02–T10 not currently authorized. Audit reports 93 passing CI tests at e22ae3b (run 45398235580), not independently rerun; T01–05/T08–10 PARTIAL, T06–07 NON-COMPLIANT; AC05–08 compliant per reported CI, 7 partial, 3 non-compliant, AC09 not verified. F1 acceptance pending REC-07. REC-01 and REC-02 documentation approved; REC-03–07 require separate approval. No merge, deployment, F2 or infrastructure changes authorized. O01/O02/O03/O18/O19 remain ACCEPTED; 15 deferred decisions remain PROPOSED. Maintenance page and routing reported on implementation branch; live state and separate authorization unverified. Preserve both histories; no duplicate implementation or automatic cherry-pick.
