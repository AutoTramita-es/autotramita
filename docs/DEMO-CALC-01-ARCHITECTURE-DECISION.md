# DEMO-CALC-01 — Owner-approved integration decision

Date: 2026-11-25
Status: Owner confirmed; documentation only. Implementation and deployment not performed by this change.

## Decision

The vehicle registration calculator is an integral part of AT-02 in AutoTramita-es/autotramita. The existing project root is `/opt/stacks/autotramita.es`. Use the existing project Docker stack, PostgreSQL infrastructure and design system, subject to accepted ADRs and safe database isolation. Do not create a separate stack, standalone application or remote repository. The demonstration hostname remains https://calculadora.autotramita.es and the target demonstration date remains 2026-11-26.

## Supersession

This decision overrides conflicting isolation, repository, database and deployment instructions in the earlier DEMO-CALC-01 execution brief, including the proposed `/opt/stacks/autotramita-calculator` directory and dedicated PostgreSQL instance. All compatible functional, fiscal, BOE, PDF, privacy, testing and acceptance requirements remain in scope. There must be one calculator, one UI and one calculation engine; the BOE importer and calculation engine are shared AT-02 components. The technical report belongs in the existing repository at `docs/DEMO-CALC-01-REPORT.md`.

## Concurrency and safety

Do not interrupt F2-T10-REC or modify its active working tree. Before implementation inspect Git status, worktrees, HEAD, accepted ADRs, AT-02 structure, migrations, Compose and routing. A separate Git worktree and development branch in the same repository is the proposed isolation mechanism, not a separate deployment stack; exact paths and branch require inspection and coordination. No concurrent migrations or uncoordinated shared configuration changes. Reuse PostgreSQL infrastructure without assuming permission to alter existing application data or bypass tenant isolation. Coordinate integration, migration and deployment gates with the active development work. No unrelated service restarts or security changes. Verify HTTPS and acceptance criteria before declaring readiness.

## Next step

Read-only preflight in `/opt/stacks/autotramita.es`: `git status --short --branch`, `git worktree list`, `git log -1 --oneline`, `ls -la`. Revise the execution brief against the actual repository and accepted ADRs before implementation. This documentation commit does not authorize additional Git operations or infrastructure changes.
