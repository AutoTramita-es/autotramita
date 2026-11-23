# ADR-003: Global user identity, tenant-local customers and memberships

- **Status:** Accepted
- **Date:** 2026-11-23
- **Project:** AutoTramita.es

## Context
Customers can submit cases without creating an account, later register, and interact with multiple dealerships. Dealership employees may belong to multiple tenants. Identity must not compromise tenant isolation.

## Decision
Separate the following entities:
- `users`: global login identity with UUID `id`, `email`, `email_verified_at`, `auth_subject`, `status`, `created_at`. No `tenant_id`.
- `tenants`: dealership with UUID `id`, unique `slug`, `legal_name`, `status`.
- `tenant_memberships`: tenant-scoped employee/owner authorization with UUID `id`, `tenant_id`, `user_id`, `role`, `status`, `created_at`.
- `customers`: tenant-scoped customer record with UUID `id`, `tenant_id`, optional `user_id`, contact/name fields and `created_at`. A customer record can exist without a login.
- `cases`: tenant-scoped case with UUID `id`, `tenant_id`, `customer_id`, `service_id`, `status`.

A single `users` row may link to customer records in multiple tenants, but each dealership sees only its own customer and case records. Customer self-service access to their own cases is separately authorized; it must not rely on dealership membership or client-supplied identifiers.

Existing anonymous cases can be claimed only after proof of control/entitlement, using secure, short-lived single-use verification; email matching alone is insufficient. Preserve audit history.

## Consequences
A single login can show the customer's own cases across dealerships while keeping tenant data separate. A user can simultaneously be a customer of one tenant and an employee of another without sharing permissions.

## Open decisions
- Whether duplicate `customers` records in the same tenant may be linked or merged, and the verification/merge policy.
- Detailed customer claim workflow, OIDC provider and fine-grained roles.

## Scope
Architecture decision only; no database migrations or endpoints are implemented.
