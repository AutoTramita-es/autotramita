# PROD-SEC-01 — Production security package: IR-05 and IR-06

Date: 2026-11-27, decisions, implementation, verification and closure 2026-11-28. **Status: ACCEPTED AND CLOSED BY THE OWNER ON 2026-11-28 ON `c08845a` (D50, [section 9](#9-independent-verification-and-closure-d50)). PB-1 is lifted.** C2 is replaced; C1 and C3 are permanent rules ([section 5](#5-interim-controls)). Closure is not a deployment authorization: the remaining production obligations are in [PRODUCTION-READINESS-01](PRODUCTION-READINESS-01.md). Implementation and evidence: [PROD-SEC-01 implementation](PROD-SEC-01-IMPLEMENTATION.md). Sections 1 to 8 keep the record as it was before the closure, except the notes marked D50.

[Implementation record](PROD-SEC-01-IMPLEMENTATION.md) · [F2 decision register (D46–D49)](../design/F2-DECISION-REGISTER.md) · [F2 execution order](../design/F2-EXECUTION-ORDER.md) · [CP09 report](../design/F2-CP09-RECONCILIATION-REPORT.md) · [INFRA-CI-02 acceptance](INFRA-CI-02-ACCEPTANCE.md#74-open-obligation-from-f2-ir-05-and-ir-06)

## 1. Origin and history

| Date | Record | Effect on IR-05 and IR-06 |
|---|---|---|
| 2026-11-25 | Independent security review of F2-CP09 on `cfbc8f7` | raised both as P3, not blocking CP09 |
| 2026-11-25 | D46 | deferred to INFRA-CI-02; existing network access is not extended |
| 2026-11-25 | D47 | severity binding named a mandatory INFRA-CI-02 requirement; interim controls (section 5); both stay deferred |
| 2026-11-27 | INFRA-CI-02 and INFRA-CI-02-REC-01 accepted | neither package addressed them; noticed while the acceptance was recorded |
| 2026-11-27 | **D48** (owner) | the obligations of D46 and D47 are **transferred to PROD-SEC-01**; nothing is waived or fulfilled |
| 2026-11-28 | Decision preparation (W1 read-out, W2 design; outside the repository) | IR-05 applies; IR-06 does not apply to the Local CI broker but to the GitHub builds and the prepared production build |
| 2026-11-28 | **D49** (owner) | Q1–Q5 answered, clarifications of the criteria approved, implementation authorized (section 7) |
| 2026-11-28 | Independent verification of `c08845a` | PASS, no open P0 or P1 (section 9) |
| 2026-11-28 | **D50** (owner) | accepted and closed; C2 replaced, C1 and C3 permanent (section 9) |

D48 changes only which package carries the obligations. D46 and D47 and the reports that name INFRA-CI-02 remain as the historical record.

## 2. Source findings

Source: `F2-CP09-INDEPENDENT-SECURITY-REVIEW.md` (2026-11-25), kept outside the repository, SHA-256 `9d7c2238b2176a670152b2f4b1aade556295de98e4e430f7983d7c03640ad553`. The two findings are quoted verbatim; line numbers are those of the review.

### 2.1 IR-05 — P3 — scan-gate hardening

> `scripts/identity/scan_gate.py`:
> - An acceptance matches on `(id, package)` only (line 158). It survives a change of installed version, severity escalation or a newly available fix until it expires.
> - The image check is `tag.endswith(image)` (line 132), a name match and not a digest binding. This is acceptable inside one trusted job.
> - The summary listing the accepted findings is written to `$RUNNER_TEMP` and is not uploaded as an artifact, so the per-run evidence of which acceptances applied lives only in the log's gate verdict.
>
> The gate is fail-closed for missing, old, foreign or partial reports and for invalid or expired entries (verified in code). **Recommendation:** also bind the installed version (or fail when `FixedVersion` appears), match the exact tag or image ID, and upload `summary.json`.

Later records on the same finding:

- D47: "bind every vulnerability acceptance to the severity it was accepted at (the gate fails when the reported severity rises above it)".
- Independent acceptance review of CP09 (outside the repository): severity binding must be explicit, and the gate should also fail when a `FixedVersion` appears, as the original finding recommended.

### 2.2 IR-06 — P3 — Local CI broker: `docker build` keeps network access for RUN steps

> `scripts/ci/lib/broker.py:126` builds with `--no-cache` but without `--network none`, so a `RUN` instruction in a branch's Dockerfile could reach the network. The Dockerfile validator refuses `--network`, `ADD`, parser directives, foreign `FROM` and `COPY --from`, and ssh, secret and cache mounts (lines 37-42, 143-171). The repository Dockerfile needs no network for `RUN` (`build.sh` compiles against the image's jars). The earlier draft's statement that the broker "uses network none" for the build is incorrect: that applies to the scan, not the build. **Recommendation:** add `--network none` to the brokered build.

## 3. Observed state

Read from the code at `285e638` on 2026-11-27. `scan_gate.py`, `vulnerability-acceptances.json`, `broker.py` and the `image-scan` job of `ci.yml` are unchanged since the F2-CP09 acceptance (`b24da2a`). No test was run for this section.

### 3.1 IR-05: applies

| Element | State |
|---|---|
| Severity | `scan_gate.py` line 158 matches an acceptance by `(id, package)`; entries carry no severity. **An accepted HIGH finding reported as CRITICAL passes the gate** |
| Installed version, available fix | the report row records both; neither affects the verdict |
| Image binding | line 132: `tag.endswith(image)` |
| Evidence | `ci.yml` writes `summary.json` to `$RUNNER_TEMP` and uploads no artifact; Local CI keeps only the step summary and the spike results. The job log prints the verdict, counts and blocking findings, not the accepted ones |
| Data available for binding | `vulnerability-review-26.8.2.json` records severity (HIGH for all six) and installed version of every accepted finding |
| Severity source | the gate counts the scanner's severity. For CVE-2026-91403 Red Hat reports **Critical** (CVSS 6.8), Trivy HIGH (IR-04, documented) |

### 3.2 IR-06: applicability not yet determined

The code does not match the finding's wording. This is a reading of the source, **not** the determination, and it closes nothing:

| Observation | Detail |
|---|---|
| The brokered build command | `broker.py` line 98 starts it with `docker build --network none`; line 126, which the finding cites, appends `--no-cache` to that command |
| Same at the reviewed SHA | lines 98 and 126 are identical at `cfbc8f7`; the option was introduced by `c7f19fd`, before the review |
| Regression test | `scripts/ci/selftest.py` asserts that the command starts with `docker build --network none` |
| Override by a step | the broker accepts only `--tag` and `--build-arg`; the Dockerfile check refuses `--network` |
| Not examined | whether the daemon's builder in fact gives a `RUN` instruction no network |
| Outside the finding's wording | the two `docker build` steps of `ci.yml` carry no `--network` option, so **on GitHub** a `RUN` instruction has the default network. Local CI runs the same steps through the broker, which adds the option |

## 4. Scope

### 4.1 In scope

| Work item | Content | Needs an order |
|---|---|---|
| W1 — IR-06 determination | read-only assessment: does the finding apply to the Local CI broker, proven at run time in a disposable context; does the same concern apply to the GitHub build; required scope of correction, or reasons why none is needed | assessment |
| W2 — IR-05 design | the open decisions of section 7, severity binding and the disposition of every element of 3.1 | assessment, owner decisions |
| W3 — IR-05 implementation | gate, acceptance format, tests, evidence retention | implementation |
| W4 — IR-06 correction | only what the owner decides after W1 | implementation |
| W5 — Independent verification and closure | separate session; owner's closure | verification |

### 4.2 Out of scope

IR-07 and every other production blocker (section 6); a Keycloak or dependency upgrade; renewing, adding or removing an acceptance (owner only); CI performance and the findings deferred by INFRA-CI-02; application features; production infrastructure.

### 4.3 Constraints

- No gate rule, test or security control is weakened; the gate stays fail-closed.
- Only the owner adds or changes an acceptance. Adding the fields that binding needs to the existing six is such a change.
- Existing network access is not extended (D46).
- Workflow changes (for example an artifact upload), broker policy and infrastructure change only with the owner's approval.

## 5. Interim controls

**Since 2026-11-28 (D50):** C1 and C3 are permanent rules. C2 has ended and is replaced by [step 4 of the production upgrade](../../identity/keycloak/UPGRADE-26.8.2.md#production-upgrade-prepared-not-applied) (build, scan the exact image, gate, record, create, check the container's image, start). The text below is the state before the closure.

In force until PROD-SEC-01 is **formally closed** (D48, confirmed by D49). Implementing or verifying a part of the package does not lift them. The replacement proposed for C2 is in [the implementation record, section 7](PROD-SEC-01-IMPLEMENTATION.md#7-deployment-safety-replacement-proposed-for-c2).

| # | Control | Source |
|---|---|---|
| C1 | The severity of a finding is reassessed whenever its acceptance is renewed or extended | D47 |
| C2 | Zero CRITICAL findings are confirmed **manually** before any production deployment; the gate alone is not enough | D47 |
| C3 | Existing network access is not extended | D46 |

Dates: the acceptance of CVE-2026-102554 (Guava) expires on **2026-12-31**, the other five on 2027-02-22. After expiry the gate fails; a renewal is subject to C1.

## 6. Production blockers

**Since 2026-11-28 (D50):** PB-1 is lifted; PB-2 is replaced together with C2. Current obligations: [PRODUCTION-READINESS-01](PRODUCTION-READINESS-01.md).

| ID | Blocker | Lifted by |
|---|---|---|
| PB-1 | **IR-05 resolved and independently verified** before any production deployment (D48) | PS-AC-01 to PS-AC-08 and PS-AC-10 met for IR-05 |
| PB-2 | Manual zero-CRITICAL confirmation for the image to be deployed (C2), as long as the package is not closed | record of the confirmation with scan evidence, per deployment |

D48 does not name IR-06 a production blocker; it requires its applicability and scope to be determined first. Whether a correction blocks production is decided by the owner after W1.

All other production blockers stay mandatory and unchanged, among them IR-07, the production Keycloak upgrade and the validity of the image acceptances: [CP09 report section 10](../design/F2-CP09-RECONCILIATION-REPORT.md#10-open-production-blockers) and [CP10 report section 9](../design/F2-CP10-REPORT.md#9-production-blockers). Closing this package alone does not make the application ready for production.

## 7. Owner decisions (D49)

The questions were open until 2026-11-28; the owner approved the recommended answers as [D49](../design/F2-DECISION-REGISTER.md).

| # | Question | Note (2026-11-27) | Decision (D49, 2026-11-28) |
|---|---|---|---|
| Q1 | Which severity binds an acceptance: the scanner's, the vendor's, or the higher of both? | D47 says "reported severity"; CVE-2026-91403 differs between the two | the authoritative **package-level** vendor: `redhat` for operating-system packages, `ghsa` for Java components. Scanner `Severity`, `SeveritySource` and that vendor's `VendorSeverity` must agree; missing, unknown, malformed or inconsistent data fails closed. CRITICAL always fails and cannot be accepted; only HIGH may be accepted; a duplicate acceptance fails. For CVE-2026-91403 the package-level HIGH is authoritative; Red Hat's CVE-level Critical stays documented and is reassessed at every renewal and before every deployment |
| Q2 | Bind the installed version, fail when a fix appears, or both? | a fixed Guava version (33.7.2) exists upstream, so "fail on `FixedVersion`" is expected to turn the gate red at once for that acceptance; to be confirmed on a scan report | both, by exact comparison with the acceptance: `installed` and `fixed` (`null`: no fix). Any difference invalidates the acceptance. Guava's recorded `fixed: 33.7.2` therefore passes; another or a new fix fails |
| Q3 | How is the gate summary retained? | an upload needs a workflow change | the gate prints its complete summary into the GitHub and Local CI job logs (disposition of PS-AC-06); no artifact upload. Deployment scan evidence is kept separately in the deployment record; log retention is limited and documented |
| Q4 | IR-06 scope after W1, including the GitHub build | | `--network none` on both image builds of `ci.yml`; `network: none` in the build of `identity/docker-compose.keycloak-production.yml`; the broker accepts exactly `--network none` from a step and keeps its isolation and every other restriction |
| Q5 | Which session implements, which verifies | they must differ | the implementing session implements; a completely new independent session verifies the final SHA; the owner decides on acceptance |

The six existing acceptances get `severity`, `installed` and `fixed` (values in D49); identifiers, packages, decisions and expiry dates are unchanged, and this is neither a renewal nor a new acceptance.

## 8. Acceptance criteria

Elements of IR-05 other than severity binding (PS-AC-04 to PS-AC-07) are met when implemented as written, or when the owner records a different disposition with its reason. PS-AC-01 to PS-AC-03 cannot be dispositioned away. The column *Clarification (D49)* is part of the criterion since 2026-11-28; PS-AC-07 and PS-AC-10 are unchanged.

| ID | Criterion | Evidence required | Clarification (D49) |
|---|---|---|---|
| PS-AC-01 | Every acceptance records the severity it was accepted at; an entry without it, or with an unknown value, fails the gate | negative tests | only `HIGH` is valid in an acceptance; an entry listed twice fails |
| PS-AC-02 | A finding reported above its accepted severity fails the gate (accepted HIGH reported CRITICAL: FAIL); equal severity passes; a reported severity the gate does not know fails | positive and negative tests, shown to fail against the old gate | "equal severity passes" applies to HIGH only; the rule also covers inconsistent and missing data on every finding, accepted or not; the new negative tests must fail against the old gate |
| PS-AC-03 | The six existing acceptances carry the severity of their review, by an owner-authorized change that alters no identifier, package, decision or expiry | diff, owner order | `severity`, `installed` and `fixed` are added, not the severity only |
| PS-AC-04 | An acceptance does not survive a change of installed version and, as decided under Q2, the appearance of a fix | tests | "appearance of a fix" means any difference from the recorded `fixed` |
| PS-AC-05 | The scanned image is bound by exact tag or image ID; a foreign image whose tag merely ends in the expected name fails | tests | image id = digest of the configuration in the saved archive = `ImageID` of the report; the tag exact, or its exact Local CI form. `docker inspect .Id` gives another value on the development host (containerd image store) |
| PS-AC-06 | The gate summary, with the accepted findings and the image ID, is retained for every run, on GitHub and in Local CI, without secrets | artifacts of both runs | the evidence is the job logs of both runs (Q3) |
| PS-AC-07 | The documentation of acceptances and of the gate states the rules as implemented, including the severity source (Q1) | review | unchanged |
| PS-AC-08 | No existing refusal, test or mandatory step is removed or weakened; full local and GitHub CI pass on the exact final SHA and compare as equivalent | run IDs, SHA, tree, comparison | accepting the exact `--network none` is not a weakening; extending test data with the new fields is not removing a test |
| PS-AC-09 | IR-06: a written determination with run-time evidence for the brokered build and an assessment of the GitHub build; the owner's decision on it; any ordered correction has a regression test and extends no network access | report, decision, tests | results of the decision preparation are not durable evidence; the implementation repeats and records them |
| PS-AC-10 | An independent session verifies the result, with no open P0 or P1 | verification report | unchanged |
| PS-AC-11 | The owner formally closes PROD-SEC-01 in the decision register; only then do C1–C3 end as interim controls, replaced by what the closing decision states | register entry | the closing decision must say what replaces C2 (proposal: [implementation, section 7](PROD-SEC-01-IMPLEMENTATION.md#7-deployment-safety-replacement-proposed-for-c2)) |

## 9. Independent verification and closure (D50)

### 9.1 Verification

A session that had not taken part in the preparation or the implementation verified the final SHA read-only on 2026-11-28. Verdict: **PASS — RECOMMENDED FOR OWNER ACCEPTANCE**; no open P0 or P1. This is the summary of its report, which was delivered to the owner and is not a file in the repository.

| Item | Result |
|---|---|
| Verified | `c08845a00b664a02ddcec74464ca95cef31b2657`, tree `a128e6e9ad5701c7114a040867c35184a583ab2a`; it differs from the tested implementation `208ad7f` (tree `86725a514eebb03b3ffb651780153e355babb4af`) only in `PROD-SEC-01-IMPLEMENTATION.md` |
| IR-05 | resolved: targeted adversarial probes; 121 gate and environment tests and the 51 runner self-tests repeated; old and new gate compared on a real scan report with 11 cases |
| IR-06 | resolved: run-time network probes of `docker build` and Compose, with controls; broker probes. The finding did not apply to the Local CI broker |
| CI | Local FULL CI `20261128-093213-d30c46` on `208ad7f` (6/6 jobs, 2,266 test executions, no failure, error or skip); GitHub runs 46131267013 and 46131808660 (5/5 jobs); test inventory digests equal. FULL CI was not repeated |
| Criteria | PS-AC-01 to PS-AC-10 met (PS-AC-06 by the Q3 disposition; PS-AC-08 on the implementation tree, the final commit being documentation only); PS-AC-11 then open |
| C2 proposal | build, save, scan and gate of a production-file build passed under a probe tag. `up --no-build` does **not** stop a moved tag (V-01); `create --no-build`, check, `start` does |
| Limits | nothing was deployed; the production daemon and the GitHub runner daemon were not inspected; start behaviour was probed with substitute commands and images, not with Keycloak |

### 9.2 Findings

| ID | Class | Finding | Disposition (D50) |
|---|---|---|---|
| V-01 | P2 | with `up --no-build` a substituted image is noticed only after it has started | **resolved by the accepted C2 replacement**: create, check, start |
| V-02 | P3 | the archive is tied to the daemon id only by "the id is unchanged around `docker save`"; the archive's `index.json` digest equalled the daemon id and could be compared directly | deferred (technical debt) |
| V-03 | P3 | the gate does not bind a report to the databases it was scanned with, so an older report of the same image passes next to fresh databases (as before D49); scan and gate run in one sequence | deferred |
| V-04 | P3 | `Vulnerabilities` given as `{}`, `""`, `0` or `false` counts as no findings, although the documentation says a non-list fails (as the old gate did) | deferred |
| V-05 | P3 | some wrongly typed reports end in a traceback without a summary; still a failure | deferred |
| V-06 | P3 | `severity_note` in `vulnerability-review-26.8.2.json` still says the gate counts the scanner's severity | deferred |
| V-07 | Info | an acceptance is not bound to a file path; `network: none` covers `RUN` steps, not the pull of the digest-pinned base images | deferred |

### 9.3 Owner decision (2026-11-28)

Accepted and closed on `c08845a` (PS-AC-11 met, [D50](../design/F2-DECISION-REGISTER.md); verbatim order in the [execution order](../design/F2-EXECUTION-ORDER.md)). C2 is replaced; C1 and C3 are permanent; V-02 to V-07 are technical debt; no further correction package or repeated review of this package is authorized.
