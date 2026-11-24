# ADR-001: Technology stack and modular monolith

- **Status:** Accepted
- **Date:** 2026-11-23
- **Project:** AutoTramita.es

## Context
AutoTramita.es requires a multi-tenant SaaS for dealerships, customers, administrative cases, documents, billing and credit, with web and Android/iOS clients and a documented, stable API.

## Decision
Use a **modular monolith** for the initial backend, with clearly separated domains under `app/`:
- Python / FastAPI for REST endpoints, validation and OpenAPI documentation.
- Pydantic v2 for schemas and configuration.
- PostgreSQL for primary relational storage; SQLAlchemy 2.x for persistence; Alembic for migrations; psycopg 3 for database connectivity.
- Redis for caching and task broker; Celery workers for asynchronous operations.
- S3-compatible object storage for documents, with application-level access control.
- Next.js + TypeScript for the web frontend.
- Flutter for Android and iOS.
- HTTPX for external integrations; an OIDC-compatible identity provider to be selected.
- Pytest, Ruff, mypy, OpenTelemetry and Sentry (or equivalents) for testing and observability.
- Docker Compose for local development and initially containerized deployment.

REST API routes are versioned under `/api/v1/`. OpenAPI is the contract for generated TypeScript and Dart clients. Financial operations require idempotency, audit trails and robust webhook handling.

## Consequences
One deployable backend simplifies transactions, development and operations. Domains remain separated so services can be extracted later if justified. Product-specific infrastructure, authentication provider and deployment details are future decisions.

## Later amendments
- The S3-compatible object storage clause is superseded by [ADR-011](ADR-011-documents-on-shared-nextcloud.md); the OIDC provider is [ADR-010](ADR-010-identity-provider-keycloak.md) (Keycloak).

## Scope
Architecture decision only; no application implementation or deployment.
