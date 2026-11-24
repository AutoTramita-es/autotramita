# ADR-011: Document content on the shared Nextcloud

- **Status:** Accepted
- **Date:** 2026-11-24
- **Project:** AutoTramita.es
- **Depends on:** ADR-002, ADR-005, ADR-008
- **Supersedes:** the "S3-compatible object storage" clause of ADR-001
- **Amends:** ADR-005 (storage mechanism only; its authorization, audit and isolation rules stand)

## Context
The owner decided that document content is stored in the existing shared Nextcloud at `cloud.autotramita.es` (see [DNS, Nextcloud and mail](../DNS-NEXTCLOUD-MAIL.md)), replacing the earlier S3-compatible proposal. ADR-001 and ADR-005 still name S3.

## Decision
- File content is stored in Nextcloud through WebDAV and the OCS API using per-environment service accounts and separate folder roots (`AutoTramita/PROD`, `AutoTramita/DEV`). No direct filesystem writes.
- Document metadata stays in tenant-scoped PostgreSQL tables under RLS (ADR-002/005): UUID, tenant, relationships, type, MIME, size, SHA-256, version, uploader, scan status, retention.
- Folder layout is UUID-based and does not grant permissions. Tenant content lives under `Tenants/{tenant_uuid}/…`, replacing the earlier `Partners/{partner_uuid}` name, so that "partner" is reserved for authorized gestorías and engineers. Internal and system areas stay separate.
- Customers, dealerships and partners never receive Nextcloud access; they reach files only through the AutoTramita API after business authorization. Download links are issued by the application and are short-lived; S3 presigned URLs are not assumed.
- Uploads are validated (actual MIME, size), quarantined and scanned with ClamAV before release; originals are preserved.
- The shared Nextcloud is a common trust and failure boundary; service-account scope, quotas and backups must be defined before production use.

## Consequences
Reuses existing infrastructure; requires an application-side storage adapter, careful service-account isolation, and a tested restore path. RLS still does not protect Nextcloud, so all access checks stay in the application.

## Open decisions
Retention and deletion rules, encryption and key management, file-size limits (proposed 50 MB documents, 20 MB photos, 250 MB video), malware pipeline operation, backup and restore, Nextcloud service-account provisioning.

## Scope
Accepted architecture decision only; nothing is provisioned or implemented.
