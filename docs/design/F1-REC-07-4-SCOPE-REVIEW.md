# REC-07.4 — scope, authorization and live-gate review (documentation only)
2026-11-24 | CLOSED | documentation only | F1 COMPLETED / ACCEPTED FOR DEVELOPMENT AND CI
[Final validation plan](F1-FINAL-VALIDATION-PLAN.md) | [Reconciliation plan](F1-RECONCILIATION-PLAN.md) | [AT-01](../specifications/AT-01-foundation-infrastructure.md)

Method: git history and file contents of `main..dev` (candidate 76b8bd5 plus this commit), GitHub API ref listing, repository documents. No database, host, Docker, DNS or Traefik state was queried or changed by this review; statements about live state repeat what the documents say and are **unverified**.

## 1. Findings that need an owner decision first
| # | Finding | Evidence | Needed |
|---|---|---|---|
| A | **Archive and original F1 branches are no longer on GitHub.** REC-01/REC-03 recorded `archive/f1-foundation-2026-11-24` (and `f1/foundation`) at e22ae3b0c9b2bed861f29ed4d7dfd1c366a8ff7a. `git ls-remote origin` and the GitHub refs API now list only `dev` (76b8bd5…) and `main` (1e8be38…); no tags. | Commit e22ae3b is still intact and is an ancestor of `dev`, so no content is lost, but the protective reference is gone. This session never deleted a branch; who or what removed them (manual deletion, auto-delete after merge, repository setting) is unknown. | Decide whether to recreate `archive/f1-foundation-2026-11-24` at e22ae3b (a new ref, no force, no rewrite) or accept `dev` history as the only record. Not done here: it is outside documentation-only scope. |
| B | **Provisioning script and migration guard disagree (R11, now concrete).** `scripts/provision-postgres.py` does not create the `schema_migrations` schema and does not make `dev` owner of it, but `migrations/env.py` (REC-07.1 R02) refuses to run unless the connected role owns both `schema_migrations` and `public`. A database provisioned only by the script would reject every migration. | script lines 91–102 vs `scripts/db/harden.sql` and `migrations/env.py` | Separate approval (outside F1 paths) to align the script with `harden.sql` before any live provisioning; test on a disposable target only. |

## 2. R13 — inventory of `main..dev` (78 files, 55 commits: 52 Ante Vrcan, 3 Copilot)
Classification: **F1** = authorized F1 implementation/evidence; **MAINT** = separate maintenance operation; **PLAN** = planning/governance document; **EXT** = unrelated to F1.
| Group | Files | Origin (first commit) | Class | Authorization basis | Recommendation |
|---|---|---|---|---|---|
| `app/` (26), `tests/` (21), `migrations/` (3: env, mako, 0001), `scripts/db/harden.sql`, `alembic.ini`, `pyproject.toml`, `uv.lock`, `.python-version` | 55 | F1 steps 1–9 on f1/foundation (754d7d1, a962cd3 …), T01–T10 reconciled on dev (8e1de01 …), REC-07.1–07.3 fixes | F1 | G6/brief T01–T10 (CP01 explicit; CP10 collective acceptance); REC-07.x explicit | Include |
| `.github/workflows/ci.yml` | 1 | 0462b98 (F1 step 9), updated cbcbe51 (dev/main triggers), REC-07.3 | F1 | G6 step 9, REC-03 conditional approval; verification only, no deploy job (guarded by `tests/test_ci_workflow.py`) | Include |
| `openapi/` (openapi.json, check-clients.sh, toolchain/package.json + lock) | 4 | 5049be5 (F1 step 8); toolchain 41dc794 | F1 | G6 step 8; toolchain manifest approved in REC-07.3 | Include |
| `.gitleaksignore` | 1 | 0462b98 | F1 | see §3 | Include (exact fingerprints only) |
| `docs/DEVELOPMENT.md` | 1 | 98ef0bf | F1 | AC15 | Include |
| `docs/design/F1-FINAL-VALIDATION-PLAN.md`, `docs/design/F1-RECONCILIATION-PLAN.md` (M); this file is added by REC-07.4 and not counted | 2 | REC-01/07.0 | PLAN | owner-approved reconciliation | Include |
| `docs/G6-EXECUTION-ORDER.md` (M), `docs/specifications/AT-01-F1-CLAUDE-CODE-EXECUTION-BRIEF.md` (M), `docs/MASTER-BLUEPRINT.md` (M) | 3 | REC-02/03/04 status records | PLAN | owner-approved REC-02..07 | Include (status blocks reconciled, §6) |
| `docs/specifications/AT-05-BOE-vehicle-catalog-plan.md` | 1 | 1690114 "propose AT-05 official BOE vehicle catalog import plan" | EXT | a proposal document on dev; no F1 authorization needed or implied | Owner chooses: include as proposal, or keep out of the F1 release |
| `docs/DNS-NEXTCLOUD-MAIL.md` (M, 5 lines) | 1 | records the temporary development page and tunnel routes | MAINT | documents a maintenance operation; live claims unverified | Owner chooses with MAINT group |
| `maintenance/` (index.html, 3 webp, 3 svg) and `docker-compose.maintenance.yml` | 9 | e22ae3b "document temporary maintenance page" (author Copilot) | MAINT | separate operation; G6 lists compose changes as forbidden **for F1 work**, so this is outside F1 and has no F1 authorization | Owner chooses (see §7) |

Not in the range and not changed by F1: `docker-compose.yml/.dev/.prod/.tunnels`, `.secrets/`, Traefik/Cloudflare configuration, frontend, Flutter, Keycloak, Nextcloud, Celery, business modules. Verified by the path list: no file outside the groups above.
History note: three commits are authored by Copilot (8e1de01 T01 toolchain reconciliation, 397b9ce merge, e22ae3b maintenance); the 26 `refs/agents/*` checkpoint refs and "Agent host session" commits seen in a local `git log --all` are local tool artifacts, not part of `dev` or `main` and not pushed.

### Maintenance assets and routing review (no live change)
- `maintenance/index.html`: static Spanish page, no scripts, no forms, no external URLs, no tracking; images are local files (about 206 KB total).
- `docker-compose.maintenance.yml`: `nginx:1.27-alpine` (tag, not digest), read-only mount of `./maintenance`, `restart: unless-stopped`, external Docker network `proxy`, Traefik routers for `autotramita.es` (TLS via the `cloudflare` resolver) and `www` with a permanent redirect to the apex. It is a **live-routing definition for the production hostname**; the `autotramita-maintenance` container is in the host's running list, consistent with the documents, but its state and Traefik/Cloudflare behaviour were not verified here.
- Risks to record: image not pinned by digest; no security-header middleware defined here; the routing definition would live in `main` after a merge and any later change to it changes the public site; F2+ application routing for `autotramita.es` must replace or coexist with this router.

## 3. R13 — Gitleaks fingerprints (`.gitleaksignore`, 3 exact entries)
**Open issue:** the first version of this review (commit 40933f6) quoted two of the synthetic strings literally; the CI secret scan over full history therefore fails (run 45441256794, 2 findings, both in this file at lines 39 and 40). The text is now reworded, but the scan covers history, so the run stays red until the owner decides: add two exact commit-and-line fingerprints for 40933f6 to `.gitleaksignore` (same mechanism as the three below), or another approach. The owner approved the two exact fingerprints (CP14) and they were added.
| Fingerprint | Commit (in dev history) | Content (reviewed, redacted here) | Assessment |
|---|---|---|---|
| `dcc2640…:tests/test_idempotency.py:generic-api-key:25` | F1 step 6b | a short synthetic string constant used as a fake key in a test | false positive |
| `dcc2640…:tests/test_idempotency.py:generic-api-key:93` | F1 step 6b | a second short synthetic string used as a fake key in a test | false positive |
| `05c49be…:tests/test_idempotency.py:generic-api-key:34` | T06 | a random UUID used as a synthetic Idempotency-Key | false positive |
All three are commit-and-line exact, rule-specific and refer to test data; there is no path, rule or regex wildcard. The current tree contains no literal of that kind (later renamed/built without a literal). Not tested here: whether each entry is still required by gitleaks v8.21.2 (that needs a scan without the file); CI secret scan on the full history is green with them (run 45439536780). No blanket exclusion exists or is proposed. Comment in the file calls the origin "f1/foundation branch"; accurate historically.

## 4. Live gates (not executed; owner acknowledgement required before any live step)
| ID | Gate | State and required evidence before the live action |
|---|---|---|
| R05 | Migration 0002 (`0002_idempotency_keys`) | Present in history (dcc2640), removed from the chain in T06 (05c49be) on the condition that it was never applied to a persistent DEV/PROD database. Only documentary evidence exists. Before the first live migration: separate read-only inventory of persistent DEV/PROD migration state (alembic version table or equivalent), or the owner records F1 as local-only with a live block. Never stamp, drop or restore automatically. |
| R11 | Provisioning vs hardening | See finding B. Also differs: script revokes only CONNECT (not all privileges, so default PUBLIC TEMP remains) from PUBLIC on the database, and does not revoke default EXECUTE on functions from PUBLIC. Reconcile and test on a disposable PostgreSQL 16 before any provisioning; never run against the shared host from F1. |
| R12 | Readiness (O20) | Public surface is liveness only (`GET /api/v1/health`); readiness is an internal function with component names only. Decide internal readiness semantics, dependency failure behaviour and monitoring before live. |
| R06 live | Trusted proxy networks | `TRUSTED_PROXY_CIDRS` is empty by default; real Traefik/Cloudflare tunnel addresses must be set and tested before deployment. |
| O06/O09/O12/O13/O17 | see §5 | gates "before live". |

## 5. Deferred decision register (15 PROPOSED, none accepted by this review)
O04 Keycloak clients (F2) · O05 session/MFA (F2) · O06 shared-DB PUBLIC grants inventory (before live) · O07 encrypted offsite backup (before PROD) · O08 RPO/RTO (before PROD) · O09 secret files and rotation (before live) · O10 resource quotas (before live) · O11 monitoring/alerts (before PROD) · O12 manual deployment from immutable digests (before live) · O13 DEV SMTP egress deny (before DEV live) · O14 Nextcloud accounts/quotas (AT-09/before live) · O15 transactional SMTP provider (AT-16) · O16 DNSSEC/Full(strict)/WAF (before PROD) · O17 direct-origin protection (before PROD) · O20 liveness vs readiness (before live). Accepted and unchanged: O01, O02, O03, O18, O19. Source of truth: AT-01 §10.

## 6. R14 — status consistency
- Individual CP02–CP09 acceptances were never recorded; only CP01 (explicit) and CP10/CP11/CP12/CP13 (explicit) exist, plus the collective T01–T10 acceptance at CP10. Nothing is inferred or back-dated.
- The status blocks in G6, the F1 brief, the AT-01 specification and the master blueprint still say "REC-02", "T01 only" or "T02–T10 not authorized". They remain as history; each document now starts with a **current status pointer** to this review and the reconciliation plan, which are authoritative. Normative requirements are unchanged.
- Test count history: 93 (REC-03) → 336 (CP10) → 368 (REC-07.1) → 397 (REC-07.2) → 419 (REC-07.3), zero skipped each time.

## 7. Release boundary — owner selection (nothing merged)
Release candidates cannot drop individual files from a history-preserving merge; excluding a group needs a follow-up revert commit (no history rewrite is authorized). Options:
1. **Everything on dev** (F1 + maintenance + AT-05 + DNS doc). Simplest, preserves history; brings the maintenance routing definition into `main`.
2. **F1 plus governance docs; maintenance, DNS doc edits and AT-05 reverted on the release branch** with a recorded reason; maintenance is released through its own approved change.
3. **Keep F1 on dev only** until a live gate plan exists (no release of F1 yet).
Recommendation: option 2 or 3, because the maintenance assets are a separate live operation with their own risks (§2) and AT-05 is an unapproved proposal. Decision is the owner's; merge to `main` needs its own explicit authorization either way.

## 8. AC01–15 matrix at this point (evidence to date; final PASS only in REC-07.5)
| AC | Status | Evidence | Open items |
|---|---|---|---|
| 01 | evidence ok | locked sync CI; exact pins; npm lock | clean-checkout rerun (07.5); Dart analysis deferred |
| 02 | evidence ok | settings/masking tests, secret scan | fingerprints reviewed (§3) |
| 03 | evidence ok | migration cycle CI; R02/R03 | clean candidate, live state gate R05 |
| 04 | evidence ok | role tests, R02 impostor tests | catalog diff in 07.5 |
| 05 | evidence ok | FORCE RLS, missing context tests | repeat in 07.5 |
| 06 | evidence ok | forged write/read/join tests | repeat in 07.5 |
| 07 | evidence ok | composite FK tests | repeat in 07.5 |
| 08 | evidence ok | pool reuse tests, R01/R04 | repeat in 07.5 |
| 09 | bounded scope | worker fixture context only | owner accepts fixture scope; real Celery in a later phase |
| 10 | evidence ok (F1 fixtures) | API/idempotency/cursor tests; no business persistence | none for F1 |
| 11 | evidence ok | Redis tests, R06/R07/R15 | live proxy networks gate |
| 12 | evidence ok | health/log/OTel, R08 | readiness O20 live gate |
| 13 | evidence ok, bounded | contract tests, R09 validator, TS/Dart generation | Dart analysis deferred (R10) |
| 14 | evidence ok | three CI jobs, 419 tests, 0 skipped, `-W error` | final candidate run (07.5) |
| 15 | partial | DEVELOPMENT.md, rollback notes | scope decision §7, finding A, rollback guide verification (07.5) |

## 9. Closure of R13 / R14 and what remains
R13: inventory, origin, authorization class, maintenance review and fingerprint review are complete; the **release selection (§7) and the archive decision (finding A) are owner decisions**. R14: status pointers, AC matrix, decision register and release boundary are recorded. R05/R11/R12 stay open as live gates (P2) with the evidence listed in §4. No code or configuration was changed in REC-07.4.

## Final decisions (2026-11-24)
- Release selection (§7): **option 3, F1 stays on `dev`**; `main` unchanged. R13 and the AC15 scope condition are CLOSED; the maintenance, DNS-doc and AT-05 group remains on `dev` and is not released.
- Finding A: closed by owner decision: only `dev` and `main` exist, no archive branch; Git history preserves e22ae3b.
- Finding B / R11, R05, R12, real proxy networks, 15 proposed decisions: deferred production prerequisites (see the plan's Final closure).
- §2 note: the R08 description of prefix recovery is superseded: the span route is now the registered template only.
