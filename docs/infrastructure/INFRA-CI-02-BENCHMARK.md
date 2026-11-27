# INFRA-CI-02 — Benchmark

Date: 2026-11-27. Specification: [INFRA-CI-02.md](INFRA-CI-02.md). Changes: [INFRA-CI-02-IMPLEMENTATION.md](INFRA-CI-02-IMPLEMENTATION.md). Verdict and evidence: [INFRA-CI-02-ACCEPTANCE.md](INFRA-CI-02-ACCEPTANCE.md). Corrections after the independent review: [INFRA-CI-02-REC-01.md](INFRA-CI-02-REC-01.md) (final run of the reviewed commit added in 8.6 and 11, attribution in 8.3 corrected). **Every figure is an observation under the stated conditions; none is a guaranteed duration or saving.**

Durations are the runner's own run duration in seconds, shown as **median [minimum–maximum]** over the stated number of runs. All runs reported here passed with no failed, errored or skipped test unless stated otherwise.

## 1. Result

Local CI, baseline commit `852d28a` against the optimized commit `2781c10`.

| Profile | Baseline | Optimized | Change (s) | Time saved | Runs |
|---|---|---|---|---|---|
| full (`run-all.sh`) | 449.9 [448.7–462.5] | 261.9 [247.0–264.8] | −188.0 | 42 % | 3 / 3 |
| fast | 82.8 [81.4–86.1] | 40.4 [40.1–40.5] | −42.4 | 51 % | 3 / 3 |
| unit | 73.4 [73.0–73.8] | 29.7 [29.4–31.8] | −43.7 | 60 % | 3 / 3 |
| integration | 300.5 [296.6–303.3] | 94.9 [94.7–101.4] | −205.6 | 68 % | 3 / 3 |
| keycloak | 378.8 [374.4–382.2] | 221.2 [218.5–224.3] | −157.6 | 42 % | 3 / 3 |
| migrations | 29.1 [26.0–29.4] | 26.7 [24.6–29.4] | −2.4 | 8 % | 3 / 3 |
| security | 56.7 [52.9–59.1] | 54.8 [54.0–61.2] | −1.9 | 3 % | 3 / 3 |
| contracts | 17.2 [14.1–18.9] | 14.1 [13.0–15.2] | −3.1 | 18 % | 3 / 3 |

Two later commits change only the local runner: waiting for a Docker subnet (full runs after it: 8.4) and at most four workers for targeted runs (8.5). **Small targeted selections are a few seconds slower than before** (8.5); larger ones are faster.

## 2. Host and conditions

| Item | Verified value |
|---|---|
| CPU | AMD Ryzen 9 5950X, 16 cores, 32 threads |
| Memory | 125.7 GiB visible; 4 GiB swap |
| Storage | 2 × Samsung MZQL23T8 (3.84 TB NVMe) in software RAID1; `/dev/shm` 63 GiB |
| Software | Linux 5.15, Docker 29.2.1, Compose 5.0.2 |
| Sharing | development server that also runs other stacks (many containers) and agent sessions |

The host was **not idle** in any measurement; baseline and optimized runs were exposed to the same standing services. Load from other development work varied during the day (for example test containers of other sessions after 13:45 UTC), so differences of a few seconds are not significant.

- Two containers of another project on the host restarted in a loop all day (more than 10,000 restarts each), copying their data directory at every start. With no CI running, the drives were written at about 400 MiB/s each and about two CPUs were busy with the copies. Found after the matrix; not changed (outside this task, reported to the owner).
- The host-wide disk figures below therefore consist mostly of this background writing (summed over both drives about 600 MiB/s during the matrix and 800 MiB/s in the idle sample) and grow with elapsed time. They do not describe CI I/O. I/O contention was low in every run (PSI `io some` at most about 2 % of elapsed time).
- Swap was full or nearly full of pages of long-running services while more than 70 GiB of memory stayed available. Small swap traffic occurred in loaded runs; no run was short of memory and no process was killed for memory (`oom_kill` counter unchanged in every measured run).

## 3. Methodology

- Every measurement is a run of the existing Local CI runner. Final and baseline profile runs test a committed snapshot (`--ref`); the matrix tested the working tree of the implementation with `--workers N` and is therefore not acceptance evidence.
- Images and the uv and npm volumes were already present (warm cache). Cold-cache durations were not measured.
- Host figures are read from `/proc` every 2 s (busy CPUs, available memory, load) and as totals over the run (disk sectors, swap pages, `oom_kill`, pressure stall information). Container figures come from `docker stats` of all Local CI containers about every 3 s, grouped by workload; short peaks can be missed. Contract generation and the other Python steps run in the same kind of step container and are reported together except for short-lived generator containers.
- Worker matrix: the whole main test step of the workflow (parallel part, then serial part) with its services, 1, 2, 4, 8, 12, 16, 24 and 32 workers, each three times in three different orders. "Isolated": no other CI run. "Beside full CI": the same measurements while `run-all.sh` ran again and again (14 full runs); the single-worker configuration was measured beside load once.

## 4. Baseline (before optimization)

Commit `852d28a`: the development head with one corrected assertion (see IMPLEMENTATION 1.7; without it the identity job fails and two of its steps do not run).

### 4.1 Full local run

Runs `20261127-083804-587d5c`, `20261127-084547-6adffc`, `20261127-085317-794530`; tree `9c56bc165ecc80aea7b395c7758b01075e826ee8`; 2007 test executions (main suite 1559, identity 265, migration step 6, rate-limit regression 3 × 59), 364 deselected, none failed or skipped. Total **449.9 [448.7–462.5]**. Peak CI memory 6.4–7.0 GiB, peak CPU about 15–16 of 32 threads. The five jobs run in parallel.

| Job | Duration | Longest steps |
|---|---|---|
| test | 447.9 [446.7–460.3] | tests 356.4 [355.4–363.4]; rate-limit regression 53.6 [52.9–55.1]; mypy 11.4; client generation 5.2 |
| identity | 380.5 [380.2–386.0] | Keycloak tests 242.2 [241.7–245.0]; DEV and PROD import 37.8; two nodes 36.9; without provider 23.9; wait for realm 17.3; image build 7.0 |
| image-scan | 59.5 [58.6–61.4] | vulnerability database download 36.3; image build 7.4 |
| dependencies | 6.4 [5.0–6.6] | |
| secrets | 5.9 [5.4–6.6] | |

### 4.2 Development profiles

| Profile | Duration | Runs |
|---|---|---|
| fast | 82.8 [81.4–86.1] | `092708-742eb2`, `093334-ed40ae`, `093957-df2631` |
| integration | 300.5 [296.6–303.3] | `092830-4317c7`, `093500-d7a560`, `094118-7eec99` |

### 4.3 GitHub

| Selection | Run duration (wall) | Main tests step | Identity job |
|---|---|---|---|
| Last five green runs (`60cb5ad` and earlier): 45831044316, 45716768381, 45710877890, 45695118547, 45673597875 | 553 [461–683] | median 362 | median 434 |
| Runs with the current test inventory (identity job failing on the stale version): 45897963908, 45961211185, 45965134344, 45971351879 | main job about 610–700 | 495 on `81fa391` | not comparable (failed) |

## 5. Bottlenecks

1. **Main test suite, serial** (356 s, 79 % of the full run). 1559 tests in 56 files; the test time reported by JUnit is 356 s, so the time is in the tests and their database set-up, not in collection. The slowest tenth of the tests holds 42 %. Slowest files: `test_account_step_up` 37 s, `test_token_mutations` 33 s, `test_platform_grants_api` 24 s, `test_web_flow` 23 s, `test_ratelimit` 23 s, `test_workspace_pipeline` 20 s. The serial run used about one CPU (mean 0.7 of a thread for Python and 0.3 for PostgreSQL).
2. **Identity job** (380 s): one pytest process against one Keycloak (242 s), followed by a chain of instance starts (two nodes, DEV and PROD import, providerless instance: about 115 s).
3. **Rate-limit regression** (54 s): three repetitions that measure time. Kept unchanged by requirement.
4. Trivy database download (36 s), mypy (11 s), client generation (5 s): none is on the longest path of the full run.

## 6. Worker matrix (main test step)

### 6.1 Elapsed time

| Workers | Isolated: step run | parallel part | serial part | Speed-up | Beside full CI: step run | parallel part | serial part | Runs |
|---|---|---|---|---|---|---|---|---|
| 1 | 362.1 [360.3–365.1] | 343.8 [343.5–346.6] | – | 1.00× | 447.9 | 418.4 | – | 3 / 1 |
| 2 | 220.1 [214.3–229.6] | 151.8 [151.4–151.9] | 43.1 [42.0–58.2] | 1.65× | 281.9 [276.3–282.1] | 203.7 [201.5–211.2] | 47.8 [47.3–51.7] | 3 / 3 |
| 4 | 158.7 [158.5–160.2] | 78.8 [78.6–79.2] | 56.5 [55.0–56.6] | 2.28× | 190.9 [190.2–191.3] | 120.8 [117.2–122.8] | 45.2 [45.1–45.7] | 3 / 3 |
| 8 | 111.3 [109.8–119.8] | 44.9 [44.3–45.1] | 43.9 [42.0–52.1] | 3.25× | 137.2 [124.7–139.9] | 53.7 [53.3–63.0] | 51.2 [46.4–55.4] | 3 / 3 |
| 12 | 106.8 [104.1–109.4] | 34.9 [34.9–36.7] | 43.9 [42.7–47.0] | 3.39× | 131.8 [128.8–152.9] | 52.1 [50.5–66.0] | 47.8 [46.3–58.0] | 3 / 3 |
| 16 | 102.3 [99.4–103.9] | 30.9 [30.8–31.0] | 43.4 [42.1–47.6] | 3.54× | 121.6 [114.6–123.1] | 38.8 [37.0–47.1] | 48.0 [45.2–49.2] | 3 / 3 |
| 24 | 111.8 [105.0–116.4] | 30.2 [29.9–30.2] | 47.3 [43.7–51.6] | 3.24× | 131.9 [131.1–136.9] | 46.1 [41.6–47.6] | 48.7 [45.0–53.4] | 3 / 3 |
| 32 | 107.9 [105.8–119.0] | 32.4 [32.1–32.8] | 43.3 [42.4–49.5] | 3.36× | 133.0 [117.7–157.6] | 46.0 [37.5–55.3] | 47.0 [45.7–61.4] | 3 / 3 |

"Parallel part" is the pytest time of the tests in workers; "serial part" runs alone and does not depend on the worker count.

### 6.2 Resources, isolated

| Workers | Host busy threads mean / max | CI peak CPU (threads) | CI peak memory GiB | Lowest available GiB | PSI CPU % | PSI I/O % | PSI memory % | Host disk read / written GiB | Max swap-out MiB | OOM kills |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 4.3 / 10 | 1.5 | 0.4 | 88 | 0.4 | 1.3 | 0.2 | 21 / 232 | 0 | 0 |
| 2 | 5.0 / 11 | 2.4 | 0.7 | 88 | 0.4 | 1.2 | 0.2 | 13 / 142 | 0 | 0 |
| 4 | 5.9 / 11 | 4.6 | 1.3 | 87 | 0.5 | 1.2 | 0.2 | 10 / 102 | 0 | 0 |
| 8 | 7.4 / 14 | 9.1 | 2.3 | 87 | 0.6 | 1.2 | 0.2 | 6 / 69 | 0 | 0 |
| 12 | 8.8 / 19 | 13.3 | 3.1 | 86 | 0.9 | 1.1 | 0.2 | 6 / 66 | 0 | 0 |
| 16 | 9.6 / 23 | 17.5 | 4.2 | 84 | 1.3 | 1.1 | 0.2 | 5 / 61 | 0 | 0 |
| 24 | 10.6 / 30 | 24.5 | 5.9 | 83 | 3.9 | 1.1 | 0.2 | 5 / 67 | 0 | 0 |
| 32 | 12.1 / 31 | 27.9 | 7.6 | 81 | 7.9 | 1.1 | 0.2 | 6 / 64 | 0 | 0 |

### 6.3 Resources, beside full CI

Host figures include the concurrent full run.

| Workers | Host busy threads mean / max | CI peak CPU (threads) | CI peak memory GiB | Lowest available GiB | PSI CPU % | PSI I/O % | PSI memory % | Host disk read / written GiB | Max swap-out MiB | OOM kills |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 14.0 / 31 | 1.2 | 0.4 | 74 | 5.5 | 0.9 | 0.3 | 22 / 265 | 316 | 0 |
| 2 | 15.2 / 30 | 2.4 | 0.7 | 74 | 6.3 | 0.9 | 0.2 | 14 / 163 | 40 | 0 |
| 4 | 17.6 / 31 | 4.6 | 1.3 | 74 | 8.1 | 0.8 | 0.3 | 9 / 107 | 248 | 0 |
| 8 | 16.5 / 30 | 9.0 | 2.3 | 78 | 7.9 | 0.9 | 0.2 | 7 / 80 | 6 | 0 |
| 12 | 20.8 / 31 | 12.7 | 3.1 | 74 | 10.6 | 0.8 | 0.3 | 6 / 70 | 122 | 0 |
| 16 | 18.1 / 31 | 17.0 | 4.1 | 77 | 7.7 | 0.9 | 0.2 | 5 / 75 | 35 | 0 |
| 24 | 21.7 / 32 | 19.4 | 6.0 | 73 | 18.2 | 0.9 | 0.4 | 7 / 72 | 311 | 0 |
| 32 | 19.9 / 32 | 24.0 | 8.1 | 73 | 15.5 | 1.0 | 0.4 | 6 / 71 | 784 | 0 |

### 6.4 Concurrent workloads (median over runs of mean CPU / peak CPU in threads, peak memory in GiB)

All Local CI containers of the host, so the neighbouring full run is included in the loaded columns.

| Workload | isolated, 1 | isolated, 16 | beside full CI, 16 | full runs used as load | final full runs |
|---|---|---|---|---|---|
| python and contracts steps | 0.7 / 1.0, 0.3 | 4.5 / 15.2, 2.9 | 5.7 / 16.0, 3.0 | 4.1 / 12.9, 2.6 | 1.8 / 15.6, 2.8 |
| postgresql | 0.3 / 1.0, 0.1 | 1.4 / 8.1, 1.5 | 1.6 / 8.0, 2.1 | 1.5 / 6.4, 1.7 | 0.5 / 7.9, 1.6 |
| redis | 0.0 / 0.0, 0.0 | 0.0 / 0.1, 0.0 | 0.0 / 0.1, 0.0 | 0.0 / 0.1, 0.0 | 0.0 / 0.1, 0.0 |
| keycloak | – | – | 3.9 / 17.5, 7.6 | 5.1 / 20.2, 7.7 | 5.5 / 21.8, 7.3 |
| identity test processes | – | – | 0.2 / 0.7, 0.3 | 0.2 / 1.0, 0.4 | 0.2 / 1.0, 0.4 |
| security | – | – | 1.7 / 1.7, 0.2 | 0.8 / 1.5, 1.4 | 0.9 / 1.3, 1.2 |
| contract generators and other helpers | – | – | – | 1.4 / 1.4, 0.2 | – |

### 6.5 Effect on the neighbouring full run

The full runs that served as load used the automatic budget (limit 12 at that time) and passed every time (14 of 14, 2062 tests each).

| Time-weighted workers of the runs measured beside it | Full run duration | Full runs |
|---|---|---|
| under 7 | 260.1 [254.7–270.0] | 7 |
| 7 to 12 | 287.1 [280.1–289.0] | 3 |
| 12 and more | 316.7 [304.6–338.8] | 4 |

### 6.6 Choice

- **16 workers** gave the lowest median both isolated and beside full CI, with the narrowest range of the fast configurations when isolated (its slowest isolated run was faster than the fastest run with 12 workers). Beyond 16 the main step did not become faster, while CPU pressure and memory rose.
- The differences between 8 and 32 workers are small (about 10 % isolated) and ranges partly overlap beside load: the serial part (about 45 s) and the service start dominate from there on.
- The automatic limit was set to `AUTO_LIMIT = 16` (matrix and the choice precede the final measurements in section 8).
- A larger measured run slowed the neighbouring full run more (6.5). The runner's budget, which divides the limit between simultaneous runs (8 each for two runs) and lowers it further on a busy host, was kept: beside a full run, 16 workers were about 16 s faster for the measured step than 8, while full runs measured beside 12 or more workers took about 30 s longer than beside 7 to 12 (6.5; each load run overlapped several configurations, so this is indicative).
- Memory is not the constraint: the highest peak memory of the containers of one full run in the matrix period was 12.5 GiB, and at least 73 GiB of host memory stayed available.

## 7. Intermediate measurements during implementation

Working tree, single runs, **not acceptance evidence**; kept to show what each step contributed.

| Configuration | Profile | Duration | Run |
|---|---|---|---|
| baseline median | integration | 300.5 | see 4.2 |
| 4 workers | integration | 135.5 | `20261127-090450-0b0266` |
| 2 Keycloak shards | keycloak | 237.2 | `20261127-091223-11d3b0` |
| 4 workers, 2 shards | all | 258.5 | `20261127-091629-71718a` |
| 4 workers, 2 shards | fast | 45.7 | `20261127-092423-248420` |
| 12 workers, 3 shards, workspaces on tmpfs | all | 227.3 | `20261127-094635-25bb4f` |

- **Shared PostgreSQL server with workers** (rejected): one test failed because migrations inspect all roles of a server (run `20261127-090118-5268da`).
- **Keycloak shards** (final layout, alone): 216.3 s; test step 114.8 s with shards of 56 s (primary), 109 s (second factor) and 100 s (recovery, reconciliation, spike).
- **Verification instances started before the tests** (rejected): saved about 8 s alone, nothing under load, slowed the start of the two nodes (about 40 s → 49–66 s) and needed a smaller JVM heap.
- tmpfs workspaces were introduced together with more workers and shards; their separate effect was not measured.

## 8. Final measurements

### 8.1 Runs

Clean committed content, tree `a3e8c2d266021a64b61560a6fcbd0a06c35af674`, commit `2781c10540f31ae66cee5beb31b476ead3cded70`.

| Profile | Duration | Test executions baseline → optimized | Peak memory GiB | Peak CPU threads | Optimized run IDs |
|---|---|---|---|---|---|
| fast | 40.4 [40.1–40.5] | 724 → 779 | 2.4 | 15 | `20261127-121225-dacfcd`, `20261127-122445-bc666f`, `20261127-123711-96e6e4` |
| unit | 29.7 [29.4–31.8] | 724 → 779 | 2.3 | 16 | `20261127-121306-c6de03`, `20261127-122526-fa209e`, `20261127-123751-3db33b` |
| integration | 94.9 [94.7–101.4] | 835 → 835 | 3.8 | 17 | `20261127-121338-1f19c7`, `20261127-122556-915225`, `20261127-123821-3fc610` |
| keycloak | 221.2 [218.5–224.3] | 265 → 265 | 8.6 | 25 | `20261127-121519-50ea3a`, `20261127-122730-169a82`, `20261127-123956-584cfd` |
| migrations | 26.7 [24.6–29.4] | 65 → 65 | 0.2 | 1 | `20261127-121858-e4d792`, `20261127-123112-c4f80b`, `20261127-124340-a2a85e` |
| security | 54.8 [54.0–61.2] | 0 → 0 | 1.2 | 2 | `20261127-121923-81ef5d`, `20261127-123141-4d130c`, `20261127-124407-08dc59` |
| contracts | 14.1 [13.0–15.2] | 0 → 0 | 0.1 | under 1 | `20261127-122024-6982e7`, `20261127-123236-31c132`, `20261127-124501-b4cd2b` |
| all | 261.9 [247.0–264.8] | 2007 → 2062 | 11.1 | 25 | `20261127-122038-875a1f`, `20261127-123249-36d37e`, `20261127-124517-8cb786` |

Baseline run IDs of the profiles not listed in section 4: unit `20261127-125424-f467db`, `20261127-130343-429d2c`, `20261127-131251-652898`; migrations `20261127-125538-6b0813`, `20261127-130456-a21ff5`, `20261127-131405-a6b318`; security `20261127-125607-f24ba3`, `20261127-130525-e66321`, `20261127-131431-dc5ba5`; contracts `20261127-125706-35d018`, `20261127-130622-8b7e46`, `20261127-131524-d6c5d1`; keycloak `20261127-125724-7bc283`, `20261127-130636-0cd55f`, `20261127-131543-0b29a3`.

### 8.2 Full run, jobs and long steps

| Job or step | Baseline | Optimized |
|---|---|---|
| job test | 447.9 [446.7–460.3] | 216.8 [200.7–230.6] |
| job identity | 380.5 [380.2–386.0] | 259.8 [244.6–262.5] |
| job secrets | 5.9 [5.4–6.6] | 5.5 [4.5–5.7] |
| job dependencies | 6.4 [5.0–6.6] | 4.9 [4.7–5.6] |
| job image-scan | 59.5 [58.6–61.4] | 75.1 [71.5–77.3] |
| job runner | 0.7 [0.7–0.7] | 0.8 [0.8–0.8] |
| test: Tests | 356.4 [355.4–363.4] | 89.8 [89.8–107.0] |
| identity: Keycloak spike and OIDC tests | 242.2 [241.7–245.0] | 120.2 [119.7–126.0] |
| test: Rate-limit timing regression | 53.6 [52.9–55.1] | 54.4 [51.0–56.1] |
| identity: Import DEV and PROD realms into isolated Keycloak instances | 37.8 [37.2–38.2] | 24.6 [23.7–24.8] |
| identity: Start two Keycloak nodes on one PostgreSQL database | 36.9 [36.4–39.5] | 65.0 [63.6–65.3] |
| image-scan: Download the Trivy vulnerability databases | 36.3 [35.3–37.8] | 43.3 [43.0–44.0] |
| identity: Without the security provider the realm signs nobody in | 23.9 [23.6–25.7] | 8.0 [7.1–9.6] |
| identity: Wait for the imported realm | 17.3 [17.2–20.9] | under 5 s or removed |
| test: mypy | 11.4 [10.8–11.6] | 16.8 [16.8–17.4] |
| image-scan: Build the AutoTramita Keycloak image | 7.4 [6.5–8.0] | 6.5 [5.8–6.9] |
| identity: Build the AutoTramita Keycloak image | 7.0 [6.4–7.0] | 6.4 [6.3–7.3] |
| test: TypeScript and Dart clients can be generated | 5.2 [4.8–6.0] | 7.7 [5.1–8.9] |
| test: Start the servers of the additional test workers | under 5 s or new | 11.7 [9.2–12.3] |
| image-scan: Scan the image offline | under 5 s or new | 6.8 [6.5–8.3] |
| image-scan: Save the image for the scanner | under 5 s or new | 11.1 [6.7–11.2] |
| identity: Start the isolated DEV and PROD import instances | under 5 s or new | 10.2 [4.7–10.4] |

Main suite in the final full runs, pytest time: parallel part 39.9 [38.4–42.5], serial part 45.7 [45.1–60.0].

**Steps that became slower.** More now runs at the same time, so single steps compete for the CPUs: starting the two Keycloak nodes, mypy, the vulnerability database download, saving and scanning the image (the `image-scan` job) and client generation take longer than in the baseline (table above). The node start is on the longest path of the full run; `image-scan` is not.

Worker budget chosen by the runner in these full runs: [16, 16, 16]; host load before: [7.52, 8.53, 7.09].

### 8.3 Two simultaneous full runs

Two `run-all.sh` started 3 s apart.

| Pair | Run | Commit | Duration | Result | Test executions | Workers | Lowest available GiB | Host swap-out MiB | PSI CPU % |
|---|---|---|---|---|---|---|---|---|---|
| pair-1 | `20261127-124942-faa615` | 2781c10 | 282.8 | PASS | 2062 | 15 | 70 | 22 | 12.5 |
| pair-2 | `20261127-124945-daaa1a` | 2781c10 | 250.0 | FAIL | 1797 | 8 | 70 | 22 | 13.9 |
| fixpair-1-1 | `20261127-132311-7e4359` | 6d6307d | 349.4 | FAIL | 1879 | 16 | 67 | 6 | 19.9 |
| fixpair-1-2 | `20261127-132314-e9c1ba` | 6d6307d | 346.5 | PASS | 2062 | 8 | 66 | 6 | 20.1 |
| fixpair-2-1 | `20261127-132901-e1cf59` | 6d6307d | 312.9 | PASS | 2062 | 4 | 70 | 94 | 12.5 |
| fixpair-2-2 | `20261127-132904-27ff6e` | 6d6307d | 364.8 | PASS | 2062 | 4 | 71 | 94 | 11.3 |

Two of the six runs in these three pairs failed, for two different reasons; both were reported FAIL.

- `pair-2` (`2781c10`): Docker could not create the network of its identity job (`all predefined address pools have been fully subnetted`). The host had 30 Docker networks and only a few free default subnets; every full run takes one per job that needs the network. The limit and the way the runner takes networks existed before this change. The runner now waits for a released subnet (commit `6d6307d`); the `fixpair` runs are on that commit. Runs that had to wait: fixpair-1-2, fixpair-2-2. That failure did not recur.
- `fixpair-1-1` (`6d6307d`): one of 1614 main tests failed, `test_password_check::test_a_sign_in_that_saw_the_change_first_leaves_the_check_nothing_to_do`. **The cause of this failure is not proven.** Two things produce its assertion, and they are different findings:
  - *Reproduced, and consistent with the original log:* two test rigs with the same Redis namespace (built from `id()`, which Python gives out again) fail the same assertion and log nothing. The original run's log holds no captured warning for the test.
  - *Hypothesis, not supported by the original log:* a Redis operation over the application's 500 ms. An injected pause of 800 ms (run `20261127-141107-be863d`) fails the same assertion, but leaves the warning `password recovery processing failed`, which the original log does not hold.

  An earlier version of this report named the Redis delay as the most probable cause; that attribution was wrong to make. The shared namespaces are corrected in [REC-01](INFRA-CI-02-REC-01.md); no Redis timeout, assertion or retry was changed.

### 8.4 Full runs after the network fix

Commit `6d6307d`, one at a time: **256.2 [255.8–262.8]**, all PASS, 2062 test executions: `20261127-133509-80f335`, `20261127-133925-a46e09`, `20261127-134341-a9e21f`.

### 8.5 Targeted runs

Development feedback, never acceptance evidence. Three runs each, baseline and optimized alternating; optimized commit `3103631` (at most 4 workers for a targeted run).

| Command | Baseline | Optimized | Result | Test executions |
|---|---|---|---|---|
| `run-integration.sh -- tests/auth/sessions` | 29.7 [25.8–30.6] | 42.5 [35.3–43.8] | 43 % slower | 32 |
| `run-integration.sh -- tests/auth/web` | 42.3 [40.7–42.7] | 36.2 [35.9–36.3] | 14 % saved | 55 |
| `run-integration.sh -- tests/platform` | 63.3 [62.0–64.9] | 44.8 [42.0–46.1] | 29 % saved | 106 |
| `run-unit.sh -- tests/test_config.py` | 8.7 [7.8–10.3] | 11.0 [10.7–11.1] | 26 % slower | 82 |

Small selections are **slower** than before: starting worker servers and two pytest parts costs several seconds. `--workers 1` avoids it. With 16 workers (the first implementation) it was worse; the worker count of targeted runs was chosen from these runs (commit `6d6307d`, `--workers`, median of two):

| Command | 1 worker | 4 | 8 | 16 |
|---|---|---|---|---|
| `run-integration.sh -- tests/auth/sessions` | 29.9 | 34.8 | 44.5 | 43.8 |
| `run-integration.sh -- tests/auth/web` | 42.2 | 35.8 | 33.6 | 42.9 |
| `run-integration.sh -- tests/platform` | 63.5 | 45.8 | 46.1 | 50.4 |
| `run-unit.sh -- tests/test_config.py` | 9.2 | 11.3 | 11.8 | 13.1 |

The full-run saving at the median is 188 s.

### 8.6 Final commit of INFRA-CI-02 (the reviewed baseline)

Commit `1357d89a699aaf67c83acade180e7a55a8cfc08c`, tree `2418f7e82f0fad0c688829f2ffc8829870826c8e`: local full run `20261127-145105-141d26`, PASS, **247.6 s**, 2062 test executions (main suite 1614, Keycloak 265, migration step 6, rate-limit regression 3 × 59), none failed, errored or skipped. GitHub run [46020259401](https://github.com/AutoTramita-es/autotramita/actions/runs/46020259401) of the same commit: 5 of 5 jobs successful, **479 s**; `compare-github.sh`: **EQUIVALENT**. One local run: it adds no new median.

## 9. Test inventory equivalence

Compared case by case (test ID and outcome) from the JUnit files of the three baseline full runs and the three final full runs of section 8.

| Suite | Baseline (each run) | Optimized (each run) | Difference |
|---|---|---|---|
| Main suite | 1559 passed | 1614 passed (1513 in the parallel part, 101 in the serial part) | no baseline case missing; 55 added, all from the new guard file `tests/test_ci_parallel.py` |
| Keycloak suite | 265 passed | 265 passed (three shards) | none missing, none added |
| Migration step | 6 passed | 6 passed | same IDs |
| Rate-limit regression | 59 passed, three times | 59 passed, three times | same IDs |

No case failed, errored or was skipped in any of these runs. The realm without the security provider is refused with the same message (`400 … Unexpected error when handling authentication request`). Totals per full run: 2007 test executions before, 2062 after (+55).

Two inventories are therefore in play: the **historical baseline** (2007 executions, main suite 1559) and the **INFRA-CI-02 inventory** (2062, main suite 1614). Durations of the two are not like for like. Later packages add tests again (REC-01: its report states the numbers).

## 10. Targets

Targets of the specification are goals, not acceptance thresholds. Medians of section 8.

| Level | Goal (section 7) | Earlier goal (section 4) | Measured | Goal of section 7 reached |
|---|---|---|---|---|
| FAST | 10–30 s | 10–60 s | 40 s | no |
| TARGETED | 15–60 s | 1–3 min | 11–45 s (8.5) | yes, for the measured selections; the small ones were already below it before |
| Python suite (main tests step) | 30–90 s | 1–2 min | 90 s in a full run [90–107] | at the median only, with no margin |
| Keycloak | 1–3 min | identity job 3–5 min | 3 min 41 s (profile); identity job in a full run 4 min 20 s | no |
| Full local | 2–3 min | 2–3 min | 4 min 22 s (4 min 16 s after the network fix) | **no** |
| GitHub full | – | 4–6 min | 5 min 56 s, 6 min 27 s and 7 min 59 s (section 11) | **one of three runs** |

**Why the full run is still above 3 minutes.** Jobs run in parallel, so the longest job decides: `identity` (about 260 s), then `test` (about 217 s).

- `identity`: starting the Keycloak instances (two nodes about 65 s, verification instances and import about 35 s) and the sharded tests (120 s; one file of about 110 s runs on a single instance) follow one another.
- `test`: tests 90 s, rate-limit regression 54 s (three repetitions required), mypy 17 s, worker servers 12 s, client generation 8 s.

Options **not implemented**, each with its price: split the longest Keycloak file between two instances (needs proof that its tests are independent); start the Keycloak instances while earlier steps run (measured once: small gain, slower node start); start the worker servers concurrently (about 8 s of the `test` job); move the rate-limit regression into its own job (changes the job set of the workflow and its guard test, and runs a timing test beside more load; owner decision). Even together, reaching 3 minutes is not assured.

## 11. GitHub

Three runs of the INFRA-CI-02 workflow (4 workers, 2 shards on the 4-CPU runner), against the baseline of section 4.3. **Three runs on shared GitHub infrastructure do not establish a typical duration, and the baseline of the green runs has a smaller test inventory.**

| Measure (s) | Historical baseline (median, five green runs) | `2f387c6`, run 46016787516 | `f1a6e56`, run 46018469751 | `1357d89`, run 46020259401 | Median [range] of the three |
|---|---|---|---|---|---|
| Run duration | 553 [461–683] | 356 | 387 | **479** | 387 [356–479] |
| Main tests step | 362 (495 on `81fa391`, current inventory then) | 159 | 242 | 154 | 159 [154–242] |
| Job "Lint, types, tests" | about 610–700 (four runs with the then current inventory) | 272 | 365 | 267 | 272 [267–365] |
| Identity job | 434 | 351 | 383 | **477** | 383 [351–477] |
| Step "Keycloak spike and OIDC tests" | not extracted | 166 | 183 | 225 | 183 [166–225] |
| Step "Start two Keycloak nodes" | about 40 (review) | 72 | 82 | **113** | 82 [72–113] |

Against the historical green-run median the three runs were 36 %, 30 % and **13 %** shorter. The goal of 4–6 minutes was met by **one of the three** (5 min 56 s) and missed by two (6 min 27 s, 7 min 59 s). In the third run the identity job was slower than the baseline median (within the baseline's range, 414–550 in the review's figures). A likely reason is contention on the 4-CPU runner between more simultaneous Keycloak instances; this was not isolated or measured. No improvement of GitHub durations is promised.

## 12. Not measured

- Cold caches (first run on an empty Docker and uv cache).
- Behaviour with more than two simultaneous CI runs, or beside a heavy unrelated job.
- The separate effect of tmpfs, and of each individual change on the final result.
- More than three GitHub runs of the INFRA-CI-02 workflow.
