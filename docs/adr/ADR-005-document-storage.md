# ADR-005: Document storage and tenant isolation

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
Registration and ownership transfer cases contain personal identification, vehicle records, technical certificates and other sensitive documents.

## Decision
- Store document metadata in tenant-scoped PostgreSQL tables, protected by RLS.
- Store file contents in private S3-compatible object storage, not directly in database rows.
- Authorize every upload, download and preview against user identity, case entitlement and tenant; global customer identity is not permission to access another tenant's files.
- Use short-lived, scoped access for object transfers; do not expose public buckets or predictable public URLs.
- Preserve audit history of access and document state changes.
- Background document processing must enforce tenant context and safe file validation.

## Consequences
RLS alone does not protect object storage. Storage policies, access checks, retention and deletion must be specified and tested.

## Open decisions
Storage provider, retention periods, malware scanning pipeline, file-size limits, encryption key management and deletion/legal-hold rules.

## Later amendments
- Storage mechanism amended by [ADR-011](ADR-011-documents-on-shared-nextcloud.md) (shared Nextcloud instead of S3-compatible storage); authorization, audit and isolation rules here remain in force.

## Scope
Architecture only.
