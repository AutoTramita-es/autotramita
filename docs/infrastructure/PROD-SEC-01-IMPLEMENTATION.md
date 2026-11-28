# PROD-SEC-01 — Implementation record (IR-05 and IR-06)

Date: 2026-11-28. **Status: IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION (PS-AC-10) AND THE OWNER'S DECISION (PS-AC-11).** This is the implementer's report; it accepts nothing. C1–C3 ([PROD-SEC-01, section 5](PROD-SEC-01.md#5-interim-controls)) stay in force until the owner formally closes the package. Nothing here authorizes a merge into `main`, a deployment, a new or renewed acceptance, or an upgrade.

[Package definition](PROD-SEC-01.md) · [D49 in the F2 decision register](../design/F2-DECISION-REGISTER.md) · [Upgrade and deployment procedure](../../identity/keycloak/UPGRADE-26.8.2.md#production-upgrade-prepared-not-applied) · [Local CI guide](LOCAL-CI.md)

## 1. Baseline and commits

| Item | Value |
|---|---|
| Repository, branch | `AutoTramita-es/autotramita`, `dev` |
| Baseline | `3fd4e4a5ea255365f48481575074d29c11f7baf9` (tree `7efe0e5`), the D48 documentation commit |
| Owner order | "PROD-SEC-01 — D49 Approval and Implementation", 2026-11-28 |
| Decision record | `c2a3f34` — D49 in the register, decisions and clarifications in [PROD-SEC-01](PROD-SEC-01.md#7-owner-decisions-d49) (before the code) |
| Implementation | the commit that adds this file; exact SHA, tree and CI evidence: [section 10](#10-ci-evidence) |
| Implementer | one Claude Code session (Q5); the decision preparation was a different session |

## 2. Approved decisions (D49)

| # | Decision | Where implemented |
|---|---|---|
| Q1 | Authoritative package-level vendor `redhat` (OS packages) and `ghsa` (Java components); scanner `Severity`, `SeveritySource` and that vendor's `VendorSeverity` must agree; missing, unknown, malformed or inconsistent data fails; CRITICAL always fails and cannot be accepted; only HIGH may be accepted; duplicates fail. CVE-2026-91403: package-level HIGH authoritative, Red Hat CVE-level Critical documented and reassessed at every renewal and before deployment | `scripts/identity/scan_gate.py` (`AUTHORITATIVE`, `severity_problem`, `judge`, `acceptances`); reassessment in the [deployment procedure](../../identity/keycloak/UPGRADE-26.8.2.md#production-upgrade-prepared-not-applied) step 4.5 and in the [provider README](../../identity/keycloak/provider/README.md) |
| Q2 | Acceptance bound to the exact installed version and fix state; any difference invalidates it | `judge`; fields `installed`, `fixed` in `identity/keycloak/vulnerability-acceptances.json` |
| Q3 | Complete gate summary in the GitHub and Local CI job logs (disposition of PS-AC-06); deployment evidence in the deployment record; retention limits documented | `scan_gate.main` prints the whole summary; [section 9](#9-security-guarantees-and-limitations) |
| Q4 | `--network none` on both image builds of `ci.yml`, `network: none` in the production compose build, broker accepts exactly `--network none` | `.github/workflows/ci.yml`, `identity/docker-compose.keycloak-production.yml`, `scripts/ci/lib/broker.py` |
| Q5 | This session implements; a new independent session verifies the final SHA; the owner decides | [section 11](#11-remaining-production-blockers-and-next-steps) |

Acceptances (owner-authorized, D49): only `severity`, `installed` and `fixed` were added to the six entries; `git diff 3fd4e4a -- identity/keycloak/vulnerability-acceptances.json` shows 18 added field lines and the rewritten format `comment`, and no other line. Identifiers, packages, `accepted_by`, `decision`, `reason` and `expires` are byte-identical. This is neither a renewal nor a new acceptance.

| CVE | Package | severity | installed | fixed | expires (unchanged) |
|---|---|---|---|---|---|
| CVE-2026-102554 | `com.google.guava:guava` | HIGH | `33.6.0-jre` | `33.7.2` | 2026-12-31 |
| CVE-2026-91403 | `java-21-openjdk-headless` | HIGH | `1:21.0.13.1.2-1.2.el9` | null | 2027-02-22 |
| CVE-2026-119373 | `sqlite-libs` | HIGH | `3.34.1-11.el9_8` | null | 2027-02-22 |
| CVE-2026-119374 | `sqlite-libs` | HIGH | `3.34.1-11.el9_8` | null | 2027-02-22 |
| CVE-2026-119379 | `sqlite-libs` | HIGH | `3.34.1-11.el9_8` | null | 2027-02-22 |
| CVE-2026-119586 | `sqlite-libs` | HIGH | `3.34.1-11.el9_8` | null | 2027-02-22 |

The values agree with a real scan of the image built from `3fd4e4a` on 2026-11-28 (pinned Trivy 0.76.2, databases of that day) and, for severity and installed version, with `vulnerability-review-26.8.2.json` (a test checks both).

## 3. Gate rules as implemented

`scripts/identity/scan_gate.py` (standard library, Python ≥ 3.10) exits 1 unless **all** of these hold. Rules 1–2 are unchanged from KC-SP-12; 3–8 are new or stricter (D49).

| # | Rule | Fails on |
|---|---|---|
| 1 | Databases: vulnerability DB schema 2 at most 48 h old, Java DB schema 1 at most 7 days, measured from `UpdatedAt` | missing, unreadable, older, more than 1 h in the future, other schema |
| 2 | Report: Trivy schema 2 of the pinned scanner `0.76.2`, with an `os-pkgs` result, a detected OS and a `lang-pkgs`/`jar` result | another scanner or schema, no OS or Java coverage, unreadable or malformed report (`Results` not a list of objects, findings not a list of objects) |
| 3 | **Image identity** (`--archive`, required): the saved archive holds exactly one image; the SHA-256 of its configuration blob equals the report's `Metadata.ImageID`; the report's `RepoTags` equal the archive's; that is exactly one tag, equal to `--image` or to its exact Local CI form `atci-<YYYYMMDD>-<HHMMSS>-<6 hex>-image-scan-<image>` | missing, unreadable, compressed or multi-image archive; configuration missing or over 4 MiB; another or no image id; other, extra or no tags; any tag that merely contains or ends in the name |
| 4 | **Severity of every finding** (all severities): `Severity` ∈ LOW, MEDIUM, HIGH, CRITICAL; `SeveritySource` is the authoritative vendor of its result (`os-pkgs`/`redhat` → `redhat`, `lang-pkgs`/`jar` → `ghsa`); `VendorSeverity[vendor]` is an integer 1–4 naming the same severity | missing, empty, `UNKNOWN` or made-up severity; another or no source; vendor rating missing, 0, text, boolean, out of range, not a map, or different from the scanner's; a finding in any other kind of result (no authoritative vendor) |
| 5 | **Finding identity:** `VulnerabilityID`, `PkgName`, `InstalledVersion` non-empty strings; `FixedVersion` absent, empty (read as no fix) or a non-empty string | anything else |
| 6 | **CRITICAL:** never passes, with or without an acceptance (`problem: "CRITICAL cannot be accepted"`) | every CRITICAL |
| 7 | **HIGH:** passes only with a valid acceptance of the same `(id, package)` whose `installed` and `fixed` equal the finding's exactly | no acceptance; other installed version; a fix appears, changes or disappears |
| 8 | **Acceptance entries:** all of `id`, `package`, `severity`, `installed`, `fixed`, `accepted_by`, `decision`, `expires` present; `severity` exactly `"HIGH"`; `installed` non-empty string; `fixed` `null` or non-empty string (absent is invalid); `accepted_by` `"owner"`; non-empty `decision`; `expires` a date from today to at most 90 days ahead; each `(id, package)` once | any invalid or expired entry (the gate fails, the entry matches nothing); an `(id, package)` listed twice fails and **every** copy is ignored |

The gate writes `--summary` and prints the same JSON into the log, then one line per blocking finding with its `problem`, then `scan gate: PASS|FAIL`; reasons go to stderr. The summary holds: verdict and reasons, scanner, database ages and SHA-256, image tags, `ImageID` and OS, the archive's configuration digest, tags and SHA-256, the SHA-256 of the report and of the acceptance file, counts per class and severity, the blocking rows, the accepted rows (id, package, installed, fixed, status, severity, source, class), acceptances that matched no finding (informational, they do not fail) and the limits. It reads no environment variable and contains no secret (a test sets a probe secret in the environment and checks the log).

## 4. IR-05 disposition

| Element of [PROD-SEC-01 §3.1](PROD-SEC-01.md#31-ir-05-applies) | Before (3fd4e4a) | Disposition |
|---|---|---|
| Severity | acceptance matched `(id, package)` only; HIGH reported CRITICAL passed | **fixed:** acceptance records `severity: "HIGH"`; CRITICAL never passes (rules 4, 6, 8) |
| Unknown or missing severity | everything outside HIGH/CRITICAL was skipped | **fixed:** fails on every finding (rule 4) |
| Severity source | the scanner's value only; vendor data ignored | **fixed:** package-level authoritative vendor must agree (rule 4, Q1) |
| Installed version, available fix | recorded in the summary, no effect | **fixed:** exact binding (rule 7, Q2) |
| Image binding | `tag.endswith(image)` | **fixed:** archive digest and exact tag (rule 3) |
| Evidence | summary in `$RUNNER_TEMP`, not uploaded; log had verdict, counts, blocking rows | **dispositioned (Q3):** whole summary in the job log of both CIs; no artifact upload |
| Duplicates, CRITICAL acceptance | second copy silently replaced the first; a CRITICAL could be accepted | **fixed:** rule 8 |

## 5. IR-06 determination and disposition

Run-time evidence of 2026-11-28 on the development host (Docker 29.10.1, buildx 0.39.1, Compose 5.8.1, containerd image store), in disposable builds of a probe Dockerfile (`alpine:3.21`, a `RUN` that lists the interfaces and tries `wget http://1.1.1.1`). The brokered command was produced by `scripts/ci/lib/broker.py` of this implementation.

| # | Build | Interfaces in `RUN` | Network |
|---|---|---|---|
| A | Local CI broker, the step naming `--network none` (the new `ci.yml` form) → `docker build --network none --label … --no-cache --tag <prefix>-autotramita-keycloak:ci <context>` | `lo` | unreachable |
| B | GitHub form `docker build --network none` | `lo` | unreachable |
| C | `docker build --network none`, Dockerfile `RUN --network=default` (the broker refuses this Dockerfile anyway) | `lo` | unreachable |
| C′ | control: the same Dockerfile without `--network none` | `lo eth0` | reachable |
| D | control: `docker build` without `--network` (the GitHub form before D49) | `lo eth0` | reachable |
| E | `docker compose build` with `build.network: none` (production form) | `lo` | unreachable |
| F | control: the same compose file without `build.network` (production form before D49) | `lo eth0` | reachable |

Determination: **the finding does not apply to the Local CI broker** — its build command started with `--network none` since `c7f19fd`, before the review (A; a `RUN --network=default` does not escape it, C). **It applied to the GitHub builds** (D: the default build network reaches the internet; not run on GitHub itself, whose runners use the same Docker default) **and to the prepared production build** (F). Disposition (Q4): both `ci.yml` builds and the production compose build now run without network; the broker accepts exactly `--network none` from a step, once, in the two-word form, and builds exactly the command it built before (`test_the_build_of_ci_yml_without_network_keeps_the_same_command`); every other network value or form is refused. No network access is extended (C3). The real Dockerfile builds without network (Local CI `security` run of this tree, and every CI run of the image).

Not examined: the GitHub-hosted runner's daemon at run time (the option is the documented Docker behaviour and is exercised by every GitHub run of the two builds).

## 6. Regression tests

| File | Before | After | Content |
|---|---|---|---|
| `tests/identity/test_scan_gate.py` | 30 | 114 | all 30 earlier test ids kept (test data extended with the new fields, PS-AC-08 clarification); new: acceptance fields (19 refusal cases), duplicates (3), severity binding and authoritative vendor (7 + 17 + 3), malformed reports (4), version and fix binding (5 + 1 + 5 on the committed acceptances), exact tag (2 positive, 10 negative), archive identity (5 + 5), whole summary in the log without secrets, `ci.yml` gate step binds the archive it saved |
| `tests/identity/test_identity_environment.py` | — | +1 | both `ci.yml` builds and the production compose build without network |
| `scripts/ci/selftest.py` (Local CI runner self-test) | 49 | 51 | all 49 kept; `--network none` accepted with an unchanged command; 9 new refused network forms; every `docker build` step of `ci.yml` passes the broker without network |

**The new tests detect the original defects.** The new `test_scan_gate.py` was run against the gate of `3fd4e4a`, behind a shim that only adapts the call signature (the old gate cannot read an archive) and records each verdict: 79 of 114 tests fail; in **70 of them the old gate returned PASS where the test requires FAIL** (among them every case below); 4 because the old gate raised an exception on a malformed report (the step ended with a traceback, not a verdict); 3 where the old gate failed, but not for the exact-tag reason (longer tag, no tag, other tag); 2 on summary fields the old gate does not write (archive identity, whole summary in the log). The same comparison on the real scan of 2026-11-28 with single synthetic changes, each gate with the acceptance file of its own commit:

| Case | Gate of `3fd4e4a` | Gate of D49 |
|---|---|---|
| unchanged report | PASS | PASS |
| accepted HIGH CVE-2026-91403 reported CRITICAL (Red Hat rating 4) | PASS | FAIL |
| accepted CVE-2026-119373 reported with severity UNKNOWN | PASS | FAIL |
| new finding without a severity | PASS | FAIL |
| new finding: Trivy MEDIUM, Red Hat CRITICAL | PASS | FAIL |
| installed version of `sqlite-libs` changed (CVE-2026-119379) | PASS | FAIL |
| a fix appears for CVE-2026-119586 | PASS | FAIL |
| image tagged `evil-<expected tag>` | PASS | FAIL |
| report `ImageID` of another image than the saved archive | PASS | FAIL |
| CRITICAL finding with an acceptance that says CRITICAL | PASS | FAIL |
| acceptance of CVE-2026-91403 listed twice | PASS | FAIL |

The first six cases are the fail-open cases reproduced in the decision preparation; the last three follow from the code and are covered by Q1. The scripts of both comparisons were kept in the session's scratch space only (not durable); the verifier can repeat them from the description above.

## 7. Deployment safety: replacement proposed for C2

Proposal for the closing decision (PS-AC-11); **documented, not executed, and C2 stays in force until the owner closes the package.** The procedure is step 4 of the [production upgrade](../../identity/keycloak/UPGRADE-26.8.2.md#production-upgrade-prepared-not-applied):

1. Build the production image from the prepared compose file (without network).
2. Record the daemon's image id; save the image; check the id is unchanged.
3. Scan that archive offline with the pinned scanner and fresh databases, exactly as the `image-scan` job.
4. Run the gate with `--archive` and `--image autotramita-keycloak:26.8.2-provider-1.1.1`: exit 0 proves the report is of exactly that archive and tag, zero CRITICAL, consistent severities and matching acceptances for every HIGH. Keep report, summary, archive hash and log in the deployment record (not in CI logs).
5. Start with `docker compose … up --no-build` only, and check every Keycloak container runs the recorded image id.

Evidence for step 5 (disposable compose project with `pull_policy: build`, 2026-11-28):

| # | Action | Result |
|---|---|---|
| G1 | `build`, record `docker image inspect .Id` | `sha256:6d87dcd4…` |
| G2 | change the Dockerfile (a rebuild would give another image) | — |
| G3 | `up -d --no-build` | container runs `sha256:6d87dcd4…`: no rebuild |
| G4 | control: `up -d` without `--no-build` | **rebuilt**, container runs `sha256:f06805cd…`: an image nobody scanned |
| G5 | `up -d --no-build` with the tag removed | refused (`No such image`), no implicit build or pull |

With the containerd image store the daemon's id is the digest of the image index, not the configuration digest that Trivy reports (on the scan image of 2026-11-28: `5a769fa5…` against `371c007c…`). The procedure therefore compares daemon ids with daemon ids (steps 2 and 5) and the archive with the report (the gate, step 4).

## 8. Acceptance criteria evidence

| ID | Evidence | Implementer's assessment (not an acceptance) |
|---|---|---|
| PS-AC-01 | rule 8; `test_no_acceptance_can_be_made_up` (no, null, unknown, lowercase, CRITICAL, MEDIUM severity), `test_an_acceptance_listed_twice_is_refused_with_every_copy` | met |
| PS-AC-02 | rules 4, 6, 7; `test_an_accepted_finding_passes_only_at_its_accepted_and_consistent_severity`, `test_missing_unknown_malformed_or_inconsistent_severity_fails_on_every_finding`, `test_only_a_valid_time_limited_owner_acceptance_lets_a_finding_through` (equal HIGH passes); shown to fail against the old gate (section 6) | met |
| PS-AC-03 | owner order D49; diff of section 2; `test_the_committed_acceptances_are_exactly_the_authorized_ones`, `test_every_committed_acceptance_rests_on_the_review_and_its_dates` | met |
| PS-AC-04 | rule 7; `test_an_acceptance_does_not_survive_a_change_of_version_or_fix`, `test_a_change_to_a_committed_finding_invalidates_its_acceptance`, `test_the_committed_acceptances_let_nothing_else_through[second_version]` | met |
| PS-AC-05 | rule 3; `test_the_image_of_github_and_of_local_ci_passes_by_its_exact_tag`, `test_an_image_whose_tag_is_not_exactly_the_expected_one_fails` (suffix match among them), `test_a_report_of_another_image_than_the_saved_archive_fails`, `test_a_missing_or_unreadable_archive_is_never_a_pass`; real data: image id = archive configuration digest (Local CI and the scan of section 2) | met |
| PS-AC-06 | Q3 disposition; `test_the_log_holds_the_whole_summary_with_the_accepted_findings_and_the_image`; the gate step logs of both runs in [section 10](#10-ci-evidence) | met by disposition, subject to the retention limits of section 9 |
| PS-AC-07 | gate docstring; acceptance file `comment`; section 3; [LOCAL-CI.md](LOCAL-CI.md), [identity README](../../identity/README.md), [provider README](../../identity/keycloak/provider/README.md); severity source stated (Q1) | for the verifier |
| PS-AC-08 | no test id removed (30/30 gate tests, 49/49 selftests); no refusal removed (broker: only the exact `--network none` added); no step removed; full Local CI and GitHub CI on the exact SHA and their comparison: [section 10](#10-ci-evidence) | see section 10 |
| PS-AC-09 | determination with run-time evidence and the assessment of the GitHub build (section 5); owner decision Q4 (D49); correction with regression tests (section 6); no network access extended | met |
| PS-AC-10 | not done here: a new independent session verifies the final SHA | open |
| PS-AC-11 | not done here: the owner's closing decision, which must state what replaces C2 (proposal: section 7) | open |

## 9. Security guarantees and limitations

Guarantees, given the trusted CI job (the job runs only repository code of the tested commit):

- No CRITICAL finding passes the gate. A HIGH finding passes only with a valid owner acceptance bound to its severity, installed version and fix state.
- No finding passes with severity information that is missing, unknown, malformed or contradicted by the authoritative package-level vendor.
- The report the gate judges is the report of the saved archive and its one exact tag.
- The Keycloak image is built without network on GitHub, in Local CI and in the prepared production build; the broker still refuses every other network option.

Limitations:

- **Severity source.** The gate trusts the package-level vendor rating as carried in Trivy's database; it does not query vendors, and does not read CVE-level ratings or CVSS. Red Hat's CVE-level Critical for CVE-2026-91403 is therefore not seen by the gate; it is a documented manual reassessment (Q1). A vendor that rates a finding only at the CVE level or not at all makes the gate fail; that is intended and cannot be accepted away.
- **Archive trust.** The gate binds the report to the archive, and the archive to the tag the step saved. That the archive is the image the job built rests on the job's own sequence of steps (inside one trusted job), as before; outside CI the deployment procedure adds the daemon-id checks of section 7.
- **Evidence retention.** GitHub keeps job logs for 90 days (repository setting, also the maximum allowed); the logs can be deleted by a repository administrator. Local CI keeps `.ci-results/<run>/logs/<job>/` on the development host until `cleanup.sh --results-older-than` removes them; they are not backed up. Neither is a deployment record: the deployment scan evidence must be kept separately (section 7).
- **Upstream fix for Guava.** A fix (`33.7.2`) exists upstream; the acceptance stays valid because it records exactly that fix state. Any change of the reported fix makes the gate red until the owner decides.
- **New findings.** A newly published CRITICAL, an escalation, a new HIGH or a change of installed or fixed version on the pinned image turns CI red at once. That is the policy working; it is a blocker for the owner, never a reason to weaken the gate.

## 10. CI evidence

Recorded in the following documentation commit, after the full Local CI run and the GitHub run on the exact implementation SHA.

## 11. Remaining production blockers and next steps

| Blocker | State |
|---|---|
| PB-1 — IR-05 resolved **and independently verified** | implemented here; verification by a new independent session (Q5, PS-AC-10) open |
| PB-2 — manual zero-CRITICAL confirmation per deployed image (C2) | in force until the owner closes the package; replacement proposed in section 7 |
| Acceptance validity | Guava (CVE-2026-102554) expires **2026-12-31**; after that the gate fails until a patched Keycloak or a new owner decision with reassessment (C1). The other five expire 2027-02-22 |
| CVE-2026-91403 | CVE-level Critical at Red Hat; reassess before every deployment and at renewal (Q1) |
| Unchanged and still mandatory | IR-07; the production Keycloak upgrade (the live `docker-compose.yml` still names 26.4.7); the 14-day rule for the pinned 26.8.2 image in production; the other blockers of [CP09 §10](../design/F2-CP09-RECONCILIATION-REPORT.md#10-open-production-blockers) and [CP10 §9](../design/F2-CP10-REPORT.md#9-production-blockers) |

Closing PROD-SEC-01 alone does not make the application ready for production.

## 12. Rollback

Nothing was deployed, so there is no runtime rollback. In the repository: `git revert` of the implementation commit (and of the evidence commit) restores the gate, acceptance file, workflow, broker, compose file and documentation of `c2a3f34`; `c2a3f34` itself only records D49. A revert brings back the IR-05 fail-open behaviour and the networked GitHub and production builds, so it needs the owner's decision, and C1–C3 apply throughout. A gate turned red by real vulnerability data is not a reason for a rollback (D49).

## 13. Changed files

| File | Change |
|---|---|
| `scripts/identity/scan_gate.py` | rules 3–8, `--archive`, whole summary in the log |
| `identity/keycloak/vulnerability-acceptances.json` | `severity`, `installed`, `fixed` on the six entries; format `comment` |
| `tests/identity/test_scan_gate.py` | regression tests (section 6) |
| `tests/identity/test_identity_environment.py` | build-network test |
| `.github/workflows/ci.yml` | `--network none` on two builds; `--archive` on the gate step; job comment |
| `scripts/ci/lib/broker.py`, `scripts/ci/selftest.py` | exact `--network none` accepted; tests |
| `identity/docker-compose.keycloak-production.yml` | `build.network: none`; header points to `up --no-build` |
| `identity/keycloak/UPGRADE-26.8.2.md` | deployment step 4 (C2 replacement proposal), prerequisites |
| `docs/infrastructure/PROD-SEC-01.md`, `LOCAL-CI.md`, `identity/README.md`, `identity/keycloak/provider/README.md`, this file | rules as implemented, status |
