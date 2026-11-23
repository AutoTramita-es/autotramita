# ADR-004: API-first contracts and client generation

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
AutoTramita.es serves Next.js web and Flutter Android/iOS clients with one FastAPI backend.

## Decision
- REST API exposed under `/api/v1/`, documented by FastAPI OpenAPI.
- Pydantic request/response contracts; consistent validation and error payloads.
- OpenAPI-driven generated TypeScript and Dart clients to avoid duplicated handwritten endpoint definitions.
- Explicit authorization for every operation and tenant context checks.
- Stable pagination, filtering and ordering conventions, documented per endpoint.
- Idempotency keys and deduplication for money movement and other retry-sensitive writes.
- Authenticated webhook endpoints validate signatures and handle retries and out-of-order events.
- Contract tests ensure OpenAPI and actual responses stay aligned.

## Consequences
Backend contract is the source of truth for web/mobile integrations. Breaking API changes require deliberate versioning or migration.

## Open decisions
Exact pagination format, error schema (e.g. RFC 9457), authentication provider, API rate limits and public integration APIs are to be specified before implementation.

## Scope
Architecture only. No endpoints implemented.
