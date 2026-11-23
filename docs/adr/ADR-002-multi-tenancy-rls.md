# ADR-002: Shared PostgreSQL database with tenant isolation and RLS

- **Status:** Accepted
- **Date:** 2026-11-23
- **Project:** AutoTramita.es

## Context
Many dealerships (tenants) must operate on a common SaaS without seeing one another's customers, cases, vehicles, documents or financial data.

## Decision
Use **one PostgreSQL database with shared tenant-scoped tables**, each carrying a non-null `tenant_id` (UUID), and PostgreSQL **Row-Level Security (RLS)** for defense in depth.

Global tables such as `users` and the central service catalog do not inherit a tenant context; their access is separately authorized. Tenant-scoped tables include `customers`, `tenant_memberships`, `vehicles`, `cases`, `documents`, `dealer_credit_accounts` and `payments`.

- Resolve active tenant server-side from authenticated and authorized membership, not from an untrusted request body.
- Set `app.tenant_id` with transaction-local `set_config(..., true)` on the **same connection and transaction** as SQLAlchemy queries.
- Enable and force RLS on tenant tables; application DB role is not table owner, superuser or `BYPASSRLS`.
- Policies must restrict both visible rows (`USING`) and inserted/updated rows (`WITH CHECK`).
- Use composite foreign keys including `tenant_id` for tenant-bound references, e.g. `cases(tenant_id, customer_id)` -> `customers(tenant_id, id)`.
- Admin cross-tenant operations require a distinct, narrowly scoped and audited authorization path; no arbitrary tenant switching.
- Background workers must establish their own verified tenant context.
- Object storage, cache keys, search indexes, logs and integrations require separate tenant isolation; RLS alone does not protect them.
- Test cross-tenant reads, writes, joins, jobs and attempts to omit or forge tenant context.

## Consequences
Efficient shared schema and migrations with strict discipline around database roles, transaction context and authorization. A global customer identity does not confer access to another dealership's records.

## Scope
Architecture decision only; implementation and security tests are pending.
