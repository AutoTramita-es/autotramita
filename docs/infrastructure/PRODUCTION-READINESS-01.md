# PRODUCTION-READINESS-01 — Remaining production obligations

Date: 2026-11-28. **Status: DEFINED, PENDING AS A SEPARATE TASK. It consolidates obligations and authorizes nothing:** implementation, merge into `main`, deployment and every change to live infrastructure each need the owner's order. Origin: [D50](../design/F2-DECISION-REGISTER.md). Goal: the earliest safe launch of AutoTramita.es.

This list does not replace or waive the source records; where it differs from them, they apply.

## 1. Starting point

Read from the repository at `c08845a`. Live infrastructure was not inventoried for this document.

| Area | State |
|---|---|
| Public site | `autotramita.es` answers with the maintenance page (HTTP 200 on 2026-11-28), served by nginx from `./maintenance` of the checkout (`docker-compose.maintenance.yml`) |
| Backend | identity, sessions, workspace context, audit and platform grants. `billing`, `cases`, `credit`, `customers`, `documents`, `integrations`, `services`, `tenants` and `vehicles` under `app/` contain no Python code |
| Web application | none in the repository |
| Application packaging | no application Dockerfile; no ASGI server among the dependencies; `API_IMAGE` and `WEB_IMAGE` are `…:pending` |
| `docker-compose.yml`, profile `application` | placeholders: `worker` and `scheduler` start `app.celery_app`, which does not exist (the recovery worker runs inside the API process); `api` receives no `AUTH_*` setting, no platform database credentials, no `CURSOR_SIGNING_KEY` and no `TRUSTED_PROXY_CIDRS`, and `.env.prod.example` lacks the `AUTH_*` settings and the last two |
| Packages | F2-T10 implemented, CP10 **not** accepted (independent security review open); T11–T13 and F3 onward not authorized |
| Release | `main` is at `1e8be38`; F1 and F2 are on `dev` only |
| Calculator (DEMO-CALC-01) | its code is not on `dev`; public tax estimates are not permitted before gestor validation and AC12 ([DEMO-CALC-01, section 0](../DEMO-CALC-01.md)) |

**Consequence:** a launch of the SaaS product is not a deployment task today. The earliest safe launch depends first on what is launched.

## 2. Launch levels (owner decision 1)

| Level | Content | Main dependencies | Obligations |
|---|---|---|---|
| **L1** | Public information site in place of the maintenance page; no accounts, no personal data collected | content, approved assets, legal texts | group A |
| **L2** | L1 and the public vehicle registration calculator | gestor validation and AC12; completing, reviewing and merging the calculator; its own deployment gate | A, B |
| **L3** | Accounts and platform backend | application packaging, a web application, Keycloak, database, mail | A, C, D |
| **L4** | Commercial MVP, approved slices of F1–F9 ([roadmap, section 6](../design/DESIGN-ROADMAP.md#6-mvp-definition)) | most product modules; no date is committed | A, C, D, E, and B if the calculator is part of it |

**Recommendation:** launch **L1** first. It needs no Keycloak, application database or unfinished module. Add L2 when the gestor validation exists. Treat L3 alone as an internal step: without business modules it offers customers nothing to do.

## 3. Obligations

Status of every row: open.

### A. Every public launch (L1 and above)

| ID | Obligation | Source |
|---|---|---|
| PR-A01 | Scope, release content and the way to `main` (a narrow release; F1/F2 need not go with it) | release option 3; [roadmap, section 11](../design/DESIGN-ROADMAP.md#11-release-gates) |
| PR-A02 | Legal notice, privacy and cookie texts with verified operator data, after Spanish legal review | [public pages specification](../design/PUBLIC-AUTH-SUPPORT-LEGAL.md#legal-information--publication-gate) |
| PR-A03 | Approval of content, image rights and accessibility; the imported rasters are not approved for release | roadmap, section 11; [blueprint](../MASTER-BLUEPRINT.md) |
| PR-A04 | DNSSEC, Full (strict) TLS and WAF checked; no unauthorized direct access to the origin | O16, O17 |
| PR-A05 | Monitoring and alerting of the public address, and incident response (L1 part of O11) | O11; roadmap, section 11 |
| PR-A06 | Deployment from a fixed version, with runbook and tested rollback to the maintenance page; public files served from outside the working checkout, so that a Git operation there cannot change the site | O12; roadmap, section 11 |
| PR-A07 | Separate deployment authorization | roadmap, section 11 |

### B. Calculator (L2)

| ID | Obligation | Source |
|---|---|---|
| PR-B01 | Gestor validation of the fiscal calculation and AC12; until then access restricted and marked as unvalidated | DEMO-CALC-01, section 0 |
| PR-B02 | Calculator work committed, reviewed, merged and passing full CI | DEMO-CALC-01; ADR-008 |
| PR-B03 | Review of image, Compose, Traefik, tunnel, access protection, rollback and resource impact; deployment approval | DEMO-CALC-01, section 0 |
| PR-B04 | If the public can upload documents: legal basis and processor terms for the external reading service, before opening it | AT-20; extends PR-A02 |

### C. Backend, database and Keycloak (L3 and above)

| ID | Obligation | Source |
|---|---|---|
| PR-C01 | Application image, ASGI server, corrected Compose services and complete production settings, platform role credentials and `CURSOR_SIGNING_KEY` included (without them platform routes answer 503) | section 1; [CP10, section 9](../design/F2-CP10-REPORT.md#9-production-blockers) |
| PR-C02 | Web application and the same-origin API route | D13; roadmap |
| PR-C03 | Database provisioning reconciled with `harden.sql`, Keycloak database included; inventory of shared `PUBLIC` grants | R11, O06 |
| PR-C04 | Read-only inventory of persistent migration state before the first live migration | R05 |
| PR-C05 | Encrypted off-site backup, RPO/RTO decided, restore drill | O07, O08; roadmap, section 11 |
| PR-C06 | Secret files and rotation; resource quotas after measurement; full monitoring; readiness separated from liveness | O09, O10, O11, O20/R12 |
| PR-C07 | Real trusted proxy networks configured and tested | `TRUSTED_PROXY_CIDRS` (R06 live) |
| PR-C08 | Transactional mail provider and domain records (SPF, DKIM, DMARC); D37 stays disabled in production until then | O15, D37 |
| PR-C09 | Keycloak production hardening (admin console and `/realms/master` not public, permanent administrator, build options), password blacklist, SMTP settings | D43; [identity README](../../identity/README.md) |
| PR-C10 | **IR-07:** credential changes under the production cache stack and a database failover or restart; review F-T10-02 with it | D46 |
| PR-C11 | **Provider version mismatch:** the production tag and upgrade step 8 say `1.1.1`, the build gives `1.2.0` (since `81fa391`); the upgrade rehearsal ran with `1.1.1`. Correct tag, procedure and the compose header (which still names `up --no-build`), and decide whether to rehearse again | independent verification of PROD-SEC-01 |
| PR-C12 | Production Keycloak upgrade or first installation: own authorization, 14-day rule (the exception does not cover production), backup first. `docker-compose.yml` still names 26.4.7: never start it without the production override | D45; [upgrade procedure](../../identity/keycloak/UPGRADE-26.8.2.md) |
| PR-C13 | If a realm already exists: image first, then the manual steps, the reconciliation script, `at_mfa_mandatory` and `kc-admin-api` | CP09 and CP10 blockers |
| PR-C14 | Valid image acceptances on the day; CVE-2026-91403 (Red Hat Critical) reassessed before every deployment; deployment by upgrade step 4 | D49, D50 |
| PR-C15 | Production bootstrap of the first grant administrator (refused by design today) | D30 |
| PR-C16 | Retention and legal basis for security events and ended sessions | **D42 open**, AT-20 |
| PR-C17 | Controlled recovery of a locked account: until the T11 interface exists such an account stays locked; decide before real users | D41, D44; CP09, section 11 |

### D. Acceptance of the security work (L3 and above)

| ID | Obligation | Source |
|---|---|---|
| PR-D01 | Independent security review and owner acceptance of F2-T10 (CP10) | [CP10 report](../design/F2-CP10-REPORT.md) |
| PR-D02 | Decide which of T11–T13 are needed before launch; final F2 acceptance (CP13) | [execution order](../design/F2-EXECUTION-ORDER.md) |
| PR-D03 | Decide the proposed decisions O06–O17 and O20 that the chosen level needs | [AT-01](../specifications/AT-01-foundation-infrastructure.md) |

### E. Product (L4)

| ID | Obligation | Source |
|---|---|---|
| PR-E01 | Approved and implemented packets F3–F9 with their open business, legal, payment and professional-contract decisions | [roadmap](../design/DESIGN-ROADMAP.md#5-proposed-development-phases-and-checkpoints) |
| PR-E02 | Release gates: professional contracts, payment reconciliation, support escalation | roadmap, section 11 |

## 4. Dated obligations

| Date | What happens | Action |
|---|---|---|
| **2026-12-31** | last day of the Guava acceptance (CVE-2026-102554). **From 2027-01-01 the image gate fails, in CI on `dev` too, at every launch level** | before then: a Keycloak 26.8.x patch with the fixed Guava (upgrade, its own order), or a new owner decision with severity reassessment (C1). Availability of such a patch was not checked |
| 2027-02-22 | the other five acceptances expire | same rule |

The gate can also fail earlier, when scanner data change (a new finding, a changed severity or fix state). That is a finding to decide, never a reason to weaken the gate.

## 5. Permanent rules and deferred items

- **C1:** severity is reassessed whenever an acceptance is renewed or extended. **C3:** existing network access is not extended (D50).
- Technical debt, not launch blockers: V-02 to V-07 ([PROD-SEC-01, section 9](PROD-SEC-01.md#92-findings)).
- Deferred by earlier records and unchanged: Dart analysis (R10), LCI-04/05, session geolocation (AC-SES-10), F-T10-03 to F-T10-08.

## 6. Shortest path

1. Owner decides the launch level (section 2). Independently of it, assign the Guava obligation (section 4).
2. For L1: order one bounded package covering PR-A01 to PR-A06; start the legal review and the operator data at once, as they do not depend on code.
3. Verify the package once on its final version, then authorize the deployment (PR-A07).
4. Plan L2, L3 or L4 as separate packages after the first launch.

## 7. Owner decisions needed now

| # | Decision | Recommendation |
|---|---|---|
| 1 | Launch level | L1 |
| 2 | Guava before 2026-12-31 | check for a patched Keycloak release by mid-December; decide then between upgrade and renewal |
| 3 | Operator legal data and legal reviewer (PR-A02) | name them now |
| 4 | Order for the first bounded package | after decisions 1 and 3 |
