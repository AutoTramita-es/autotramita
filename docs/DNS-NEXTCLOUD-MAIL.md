# AutoTramita.es — DNS, Nextcloud and mail
Status: Accepted design decisions, 2026-11-24. Documentation only; no implementation or deployment.

## DNS and domains (decisions 01–04)
Cloudflare authoritative DNS, DNSSEC, proxied web traffic, WAF, DDoS protection, HTTPS, Full (strict) for HTTPS origin connections. Hybrid architecture: web services via Cloudflare Tunnel, mail via direct DNS-only endpoints. One dedicated server, two isolated Docker Compose projects (autotramita-prod and autotramita-dev), separate tunnels and networks; no staging. DEV protected by Zero Trust; admin additionally protected. Traefik per environment, explicit service exposure. Central REST API /v1/, English technical names, Spanish UI. Auth domains serve Keycloak SSO (decision 05); separate instances, OIDC authorization code + PKCE, BFF host-only cookies, no browser token storage.

| PROD | DEV | Purpose |
|---|---|---|
| autotramita.es | dev.autotramita.es | Public frontend |
| www.autotramita.es | — | Redirect to apex |
| partners.autotramita.es | partners-dev.autotramita.es | Partners |
| clientes.autotramita.es | clientes-dev.autotramita.es | Clients |
| admin.autotramita.es | admin-dev.autotramita.es | Internal admin |
| api.autotramita.es | api-dev.autotramita.es | REST API |
| auth.autotramita.es | auth-dev.autotramita.es | Authentication |
| webhooks.autotramita.es | webhooks-dev.autotramita.es | Signed external callbacks |
| docs.autotramita.es | docs-dev.autotramita.es | Documentation |
| cloud.autotramita.es | cloud-dev.autotramita.es | Nextcloud |
| cdn.autotramita.es | cdn-dev.autotramita.es | Public static content only |
| status.autotramita.es | — | Independent status service |
| webmail.autotramita.es | — | Webmail |
| — | mailpit-dev.autotramita.es | Protected test mail UI |

Web tunnel records: proxied CNAME (apex flattening); actual targets pending. CDN and status targets pending. External callbacks require signature verification; DEV callbacks must not bypass protection broadly. CORS restricted to approved environment origins. No public database ports. No actual DNS records created by this decision.

## Nextcloud (revised decision 06, option B)
Existing Docker Nextcloud architecture is the central document storage; no MinIO and no storage/storage-dev hostnames. Separate PROD and DEV Nextcloud instances, databases, Redis and credentials. WebDAV + OCS API via service accounts; no direct filesystem writes. Partners and clients access files exclusively via AutoTramita API with business authorization. Authorized internal staff may access Nextcloud via Keycloak SSO; direct access must not bypass document permissions or controlled versioning. No public shares by default. Private documents never cached on CDN.
PostgreSQL holds document metadata, UUID, tenant/client/vehicle/case relationships, type, filename, storage reference, MIME, size, SHA-256, version, uploader, timestamps, scan status and retention. Validate actual MIME and size, quarantine and scan via ClamAV before release; preserve original and business versions. Proposed limits from accepted storage discussion: documents 50 MB, photos 20 MB, video 250 MB, subject to transfer constraints. Authorized short-lived application download links, not assumed native S3 presigned URLs. TLS and encrypted storage, audit, EU data location, GDPR/LOPDGDD. Consistent encrypted offsite backup of files, database and configuration; provider not decided.
Folder layout: AutoTramita/Partners/{partner_uuid}/{Clients,Vehicles,Cases,Contracts,Invoices}; DirectClients/{client_uuid}/{Vehicles,Cases,Documents}; Internal/{Administration,Accounting,Legal,Templates}; System/{Generated,Quarantine,Archive}. UUID paths rather than personal identifiers. Folder layout does not grant permissions.

## Mail (decision 07, option B)
Existing FS-Mailserver (Postfix/Dovecot) for business mail; external transactional SMTP provider for automatic notifications, provider pending. Mail remains independent of AutoTramita deployment.
Domains: mail.autotramita.es (SMTP/IMAP), webmail.autotramita.es, notify.autotramita.es (transactional sender), bounce.autotramita.es (bounce handling, provider-specific).
Business addresses at @autotramita.es: info, comercial, socios, clientes, soporte, tramites, documentacion, facturacion, contabilidad, pagos, legal, privacidad, seguridad. Use aliases/shared mailboxes as appropriate. Transactional senders: notificaciones@notify.autotramita.es and no-reply@notify.autotramita.es.
DNS plan: mail A/AAAA DNS-only if applicable; apex MX, SPF TXT, DKIM selector TXT/CNAME, _dmarc TXT; notify SPF, DKIM and DMARC; bounce MX or provider-specific records; webmail proxied CNAME; MTA-STS (_mta-sts TXT and mta-sts HTTPS host) and TLS reporting (_smtp._tls TXT). PTR set by IP provider. Actual values and selectors pending existing server/provider verification; avoid duplicate SPF records. SMTP/IMAP must not use ordinary Cloudflare HTTP proxy.
Notification service: queue, retries, audit, Spanish templates for registration, invitations, cases, missing documents, status changes, invoices, payments, reminders, signatures, security and Keycloak password resets. Sensitive documents via authenticated app links, not automatic attachments.
Inbound documentacion mailbox: Dovecot source of truth, Sieve signals, IMAP IDLE and periodic reconciliation, subject to FS-Mailserver integration contract. Scan attachments, store in Nextcloud, associate with verified case; ambiguous matches go to manual review, never match solely by sender address. DEV uses Mailpit, test mailboxes and credentials, no real outbound mail.
## Scope
Only DNS/domain, Nextcloud and mail decisions and directly related dependencies recorded here. No backup provider decision, no implementation, deployment or DNS changes authorized by this document.
