# ADR-010: Keycloak as identity provider

- **Status:** Accepted
- **Date:** 2026-11-24
- **Project:** AutoTramita.es
- **Depends on:** ADR-001, ADR-003, ADR-009
- **Refines:** ADR-001 ("OIDC-compatible identity provider to be selected")

## Context
ADR-001 left the OIDC provider open. The owner chose Keycloak, and a per-environment Keycloak service with its own database is already prepared in Docker Compose (not deployed). The G5 foundation review found that identity, active workspace and revocation need an explicit split between provider and application.

## Decision
- Keycloak authenticates the person (password, recovery, optional second factor, e-mail verification). `users.auth_subject` stores the Keycloak `sub`.
- The application owns authorization: tenant memberships, roles, branch grants, workspace context and platform grants. Tenant, branch and role are **not** trusted from token claims.
- Active tenant and branch live in an application-owned `user_sessions` record validated on every request, so membership revocation, deactivation, tenant switching and remote logout take effect immediately without waiting for token expiry.
- Access tokens are short-lived; native clients use authorization code with PKCE through the system browser; web uses HttpOnly cookies with CSRF protection.
- Separate Keycloak realm and database per environment (PROD, DEV). No shared realm.
- Dealership second factor stays optional (AT-03 decision 18); central and professional policy remains an open AT-02 decision.

## Consequences
Keycloak outage blocks sign-in but not already validated sessions beyond their short lifetime. Application must maintain session and membership checks itself. Session timings (proposed 30 min idle, 12 h web) need owner approval.

## Open decisions
Realm and client configuration, account recovery verification, MFA policy for central and professional roles, session lifetimes, Keycloak SSO for authorized staff access to Nextcloud, upgrade and backup procedure.

## Scope
Accepted architecture decision only; nothing is deployed or implemented.
