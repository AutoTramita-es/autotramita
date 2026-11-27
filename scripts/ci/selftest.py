"""Guard rails of the Local CI runner, checked without Docker: it must refuse what it cannot
reproduce, never report PASS for something that did not run, and never let a CI step reach
outside its workspace. Run: python3 scripts/ci/selftest.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

CI_DIR = Path(__file__).resolve().parent
REPO = CI_DIR.parents[1]
sys.path.insert(0, str(CI_DIR / "lib"))

import profiles  # noqa: E402
import report  # noqa: E402
import snapshot  # noqa: E402
import workflow  # noqa: E402
import yaml  # noqa: E402
from broker import Policy, Refused  # noqa: E402

CI_YML = REPO / ".github" / "workflows" / "ci.yml"


class WorkflowCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = yaml.safe_load(CI_YML.read_text())
        self.flow = workflow.load(CI_YML)

    def test_the_full_profile_runs_every_job_and_every_run_step(self) -> None:
        selected = {
            s.job.key: [step.name for step in s.steps] for s in profiles.select("all", self.flow)
        }
        expected = {
            key: [step["name"] for step in job["steps"] if "run" in step]
            for key, job in self.raw["jobs"].items()
        }
        self.assertEqual(selected, expected)

    def test_every_profile_resolves(self) -> None:
        for name in profiles.PROFILES:
            self.assertTrue(profiles.select(name, self.flow), name)

    def test_commands_are_taken_from_the_workflow_unchanged(self) -> None:
        for selection in profiles.select("all", self.flow):
            raw = {
                s["name"]: s["run"]
                for s in self.raw["jobs"][selection.job.key]["steps"]
                if "run" in s
            }
            for step in selection.steps:
                self.assertEqual(step.run, raw[step.name])

    def load_changed(self, change: Any) -> None:
        raw = copy.deepcopy(self.raw)
        change(raw["jobs"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ci.yml"
            path.write_text(yaml.safe_dump(raw))
            workflow.load(path)

    def test_what_cannot_be_reproduced_stops_the_run(self) -> None:
        changes = {
            "job needs": lambda j: j["test"].update(needs="secrets"),
            "matrix": lambda j: j["test"].update(strategy={"matrix": {}}),
            "other runner": lambda j: j["test"].update({"runs-on": "windows-latest"}),
            "unknown action": lambda j: j["test"]["steps"].append(
                {"uses": "actions/cache@" + "0" * 40}
            ),
            "expression": lambda j: j["test"]["steps"].append(
                {"name": "x", "run": "echo ${{ github.sha }}"}
            ),
            "condition": lambda j: j["test"]["steps"].append(
                {"name": "x", "run": "true", "if": "github.ref == 'x'"}
            ),
            "ignored failure": lambda j: j["test"]["steps"].append(
                {"name": "x", "run": "false", "continue-on-error": True}
            ),
            "new service": lambda j: j["test"]["services"].update(minio={"image": "m"}),
        }
        for name, change in changes.items():
            with self.subTest(name), self.assertRaises(workflow.Unsupported):
                self.load_changed(change)

    def test_a_renamed_step_is_noticed_by_the_partial_profiles(self) -> None:
        job = self.flow.jobs["test"]
        with self.assertRaises(workflow.Unsupported):
            job.step("No such step")


class BrokerPolicy(unittest.TestCase):
    IMAGE = "example/image:1@sha256:" + "a" * 64

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.ws = Path(self.temporary.name).resolve() / "ws"
        (self.ws / "src").mkdir(parents=True)
        (self.ws / "escape").symlink_to("/")
        self.policy = Policy(
            "atci-run-job", {"com.autotramita.ci": "1"}, "netns-id", self.ws,
            (self.ws / "src",), frozenset({self.IMAGE}),
        )  # fmt: skip

    def test_the_workflow_form_is_rewritten_into_the_isolated_namespace(self) -> None:
        command = self.policy.command(
            ["run", "-d", "--name", "keycloak", "--network", "host",
             "-v", f"{self.ws}/src:/repo", self.IMAGE, "start-dev"]
        )  # fmt: skip
        self.assertIn("container:netns-id", command)
        self.assertNotIn("host", command)
        self.assertIn("atci-run-job-keycloak", command)
        self.assertIn(f"{self.ws}/src:/repo:ro", command)
        self.assertEqual(self.policy.command(["rm", "-f", "keycloak"])[-1], "atci-run-job-keycloak")

    def test_a_container_without_a_network_flag_gets_none(self) -> None:
        command = self.policy.command(["run", "--rm", self.IMAGE])
        self.assertEqual(command[command.index("--network") + 1], "none")

    def test_everything_else_is_refused(self) -> None:
        run = ["run", "--rm"]
        requests = [
            [*run, "--privileged", "true", self.IMAGE],
            [*run, "--pid", "host", self.IMAGE],
            [*run, "--network", "bridge", self.IMAGE],
            [*run, "-p", "5432:5432", self.IMAGE],
            [*run, "--user", "0:0", self.IMAGE],
            [*run, "-v", "/:/host", self.IMAGE],
            [*run, "-v", "/var/run/docker.sock:/var/run/docker.sock", self.IMAGE],
            [*run, "-v", f"{self.ws}/escape:/host", self.IMAGE],
            [*run, "-v", f"{self.ws}/src/../..:/host", self.IMAGE],
            [*run, "-v", "atci-uv-cache:/cache", self.IMAGE],
            [*run, "alpine"],
            ["rm", "-f", "postgres"],
            ["logs", "infra-redis"],
            ["exec", "postgres", "sh"],
            ["ps"],
            ["system", "prune", "-f"],
        ]  # fmt: skip
        for request in requests:
            with self.subTest(" ".join(request)), self.assertRaises(Refused):
                self.policy.command(request)

    SCANNER = "aquasec/trivy:0.76.2@sha256:" + "b" * 64
    DOCKERFILE = (
        "# AutoTramita Keycloak image\n"
        f"ARG KEYCLOAK_IMAGE={IMAGE}\n"
        f"ARG JDK_IMAGE={IMAGE}\n"
        "FROM ${KEYCLOAK_IMAGE} AS keycloak\n"
        "FROM ${JDK_IMAGE} AS build\n"
        "COPY --from=keycloak /opt/keycloak/lib/lib /keycloak-lib\n"
        "RUN /provider/build.sh /keycloak-lib /x.jar\n"
        "FROM ${KEYCLOAK_IMAGE}\n"
        "COPY --from=build --chown=1000:0 /x.jar /opt/keycloak/providers/x.jar\n"
        "USER 1000\n"
    )

    def context(self, dockerfile: str | None = None) -> Path:
        context = self.ws / "src" / "identity" / "keycloak"
        context.mkdir(parents=True, exist_ok=True)
        (context / "Dockerfile").write_text(dockerfile or self.DOCKERFILE)
        return context

    def build(self, context: Path | str) -> list[str]:
        return self.policy.command(
            ["build", "--build-arg", f"KEYCLOAK_IMAGE={self.IMAGE}",
             "--tag", "autotramita-keycloak:ci", str(context)]
        )  # fmt: skip

    def test_only_the_keycloak_image_is_built_from_its_directory_without_network(self) -> None:
        context = self.context()
        command = self.build(context)
        self.assertEqual(command[:4], ["docker", "build", "--network", "none"])
        self.assertIn("--no-cache", command)  # nothing is taken from, or left for, other builds
        self.assertEqual(command[-2:], ["atci-run-job-autotramita-keycloak:ci", str(context)])
        started = self.policy.command(["run", "-d", "--name", "kc", "autotramita-keycloak:ci"])
        self.assertIn("atci-run-job-autotramita-keycloak:ci", started)

    def test_every_other_build_is_refused(self) -> None:
        context = self.context()
        tag = ["--tag", "autotramita-keycloak:ci"]
        requests = [
            ["build", "--tag", "other:1", str(context)],
            ["build", *tag, str(self.ws / "src")],
            ["build", *tag, str(self.ws / "escape")],
            ["build", *tag, f"{context}/../.."],  # traversal to another directory
            ["build", *tag, "--build-arg", "KEYCLOAK_IMAGE=alpine", str(context)],
            ["build", *tag, "--build-arg", f"OTHER={self.IMAGE}", str(context)],
            ["build", *tag, "--network", "host", str(context)],
            ["build", *tag, "--file", "/tmp/Dockerfile", str(context)],  # noqa: S108
            ["build", *tag],
            ["build", str(context)],
            ["run", "--rm", "autotramita-keycloak:ci"],  # not built by this job
        ]  # fmt: skip
        for request in requests:
            with self.subTest(" ".join(request)), self.assertRaises(Refused):
                self.policy.command(request)

    def test_the_repository_dockerfile_passes_with_the_images_ci_yml_names(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        workflow = (repo / ".github" / "workflows" / "ci.yml").read_text()
        images = set(re.findall(r"[a-z0-9./_-]+:[\w.-]+@sha256:[0-9a-f]{64}", workflow))
        policy = Policy(
            "atci-run-job", {"com.autotramita.ci": "1"}, "netns-id", self.ws,
            (self.ws / "src",), frozenset(images),
        )  # fmt: skip
        context = self.context((repo / "identity" / "keycloak" / "Dockerfile").read_text())
        policy.command(["build", "--tag", "autotramita-keycloak:ci", str(context)])

    def test_a_context_reached_through_a_link_is_refused(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "Dockerfile").write_text(self.DOCKERFILE)
        (self.ws / "src" / "identity").mkdir(parents=True)
        (self.ws / "src" / "identity" / "keycloak").symlink_to(outside)
        with self.assertRaises(Refused):
            self.build(self.ws / "src" / "identity" / "keycloak")
        linked = self.ws / "src" / "identity" / "keycloak"
        linked.unlink()
        linked.mkdir()
        (linked / "Dockerfile").symlink_to(outside / "Dockerfile")
        with self.assertRaises(Refused):
            self.build(linked)

    def test_a_dockerfile_that_reaches_past_the_pinned_images_is_refused(self) -> None:
        bad = {
            "syntax frontend": "# syntax=docker/dockerfile:1\n",
            "remote ADD": "ADD https://example.test/x.jar /x.jar\n",
            "local ADD": "ADD x.jar /x.jar\n",
            "host network": "RUN --network=host true\n",
            "insecure": "RUN --security=insecure true\n",
            "ssh": "RUN --mount=type=ssh true\n",
            "secret": "RUN --mount=type=secret,id=x true\n",
            "shared cache": "RUN --mount=type=cache,target=/c true\n",
            "other image": "FROM alpine:3\n",
            "image digest": f"FROM {self.IMAGE}\n",
            "copy from image": "COPY --from=alpine:3 /bin/sh /sh\n",
            "other default": "ARG JDK_IMAGE=alpine:3\n",
        }
        for label, line in bad.items():
            with self.subTest(label), self.assertRaises(Refused):
                self.build(self.context(self.DOCKERFILE + line))

    def test_the_built_image_is_saved_only_into_the_workspace(self) -> None:
        self.build(self.context())
        temp = self.ws / "runner_temp"
        temp.mkdir()
        command = self.policy.command(
            ["save", "--output", str(temp / "image.tar"), "autotramita-keycloak:ci"]
        )
        self.assertEqual(
            command,
            ["docker", "save", "--output", str(temp / "image.tar"),
             "atci-run-job-autotramita-keycloak:ci"],
        )  # fmt: skip
        (temp / "taken").write_text("x")
        (temp / "link").symlink_to("/etc")
        for request in (
            ["save", "--output", "/tmp/image.tar", "autotramita-keycloak:ci"],  # noqa: S108
            ["save", "--output", str(temp / "taken"), "autotramita-keycloak:ci"],
            ["save", "--output", str(temp / "link" / "x.tar"), "autotramita-keycloak:ci"],
            ["save", "--output", "relative.tar", "autotramita-keycloak:ci"],
            ["save", "--output", str(temp / "x.tar"), self.IMAGE],  # not built by this job
            ["save", str(temp / "x.tar"), "autotramita-keycloak:ci"],
        ):
            with self.subTest(" ".join(request)), self.assertRaises(Refused):
                self.policy.command(request)

    def scanner_policy(self, egress: str) -> Policy:
        return Policy(
            "atci-run-job", {"com.autotramita.ci": "1"}, "netns-id", self.ws,
            (self.ws / "src",), frozenset({self.IMAGE, self.SCANNER}), egress=egress,
        )  # fmt: skip

    def test_only_the_pinned_scanner_downloads_and_only_its_databases(self) -> None:
        cache = self.ws / "runner_temp" / "trivy"
        cache.mkdir(parents=True)
        policy = self.scanner_policy("atci-run-job-egress")
        mount = ["-v", f"{cache}:/cache"]
        download = ["--cache-dir", "/cache", "image", "--download-db-only", "--no-progress"]
        command = policy.command(["run", "--rm", *mount, self.SCANNER, *download])
        self.assertEqual(command[command.index("--network") + 1], "atci-run-job-egress")
        scan = ["--cache-dir", "/cache", "image", "--input", "/image.tar", "--offline-scan"]
        offline = policy.command(["run", "--rm", "--network", "none", *mount, self.SCANNER, *scan])
        self.assertEqual(offline[offline.index("--network") + 1], "none")
        refused = [
            (policy, ["run", "--rm", "--network", "host", *mount, self.SCANNER, *download]),
            (policy, ["run", "--rm", self.SCANNER, *download]),  # no cache mount
            (policy, ["run", "--rm", *mount, *mount, self.SCANNER, *download]),
            (self.scanner_policy(""), ["run", "--rm", *mount, self.SCANNER, *download]),
        ]
        for which, request in refused:
            with self.subTest(" ".join(request)), self.assertRaises(Refused):
                which.command(request)
        # anything else, the same arguments included, gets no network
        for request in (
            ["run", "--rm", *mount, self.IMAGE, *download],
            ["run", "--rm", *mount, self.SCANNER, *download, "--db-repository", "evil.test/db"],
        ):
            with self.subTest(" ".join(request)):
                command = policy.command(request)
                self.assertEqual(command[command.index("--network") + 1], "none")


def summary(status: str = report.PASS, **suite: int) -> dict[str, Any]:
    counts = {"tests": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0, **suite}
    return {
        "jobs": [
            {
                "key": "test",
                "checks": [{"name": "c", "status": status}],
                "suites": [{"file": "a.xml", **counts}],
            }
        ]
    }


class Verdict(unittest.TestCase):
    def test_pass_needs_every_check_executed_and_passed(self) -> None:
        self.assertEqual(report.verdict(summary())[0], report.PASS)
        for status in (report.FAIL, report.NOT_RUN):
            self.assertEqual(report.verdict(summary(status))[0], report.FAIL)

    def test_skips_failures_empty_suites_and_empty_runs_are_not_a_pass(self) -> None:
        for suite in ({"skipped": 1}, {"failed": 1}, {"errors": 1}, {"tests": 0}):
            with self.subTest(suite):
                self.assertEqual(report.verdict(summary(**suite))[0], report.FAIL)
        self.assertEqual(report.verdict({"jobs": []})[0], report.FAIL)
        self.assertEqual(report.verdict({**summary(), "interrupted": True})[0], report.FAIL)
        self.assertEqual(report.verdict({**summary(), "error": "x"})[0], report.FAIL)


class WorkerBudget(unittest.TestCase):
    GIB = 1024**3

    def test_simultaneous_runs_share_the_workers_and_memory_limits_them(self) -> None:
        import runner

        alone = runner.worker_budget(0, 32, 100 * self.GIB)
        self.assertEqual(alone, runner.pytest_phases.AUTO_LIMIT)
        self.assertEqual(runner.worker_budget(1, 32, 100 * self.GIB), alone // 2)
        self.assertEqual(runner.worker_budget(20, 32, 100 * self.GIB), 2)
        self.assertEqual(runner.worker_budget(0, 32, 8 * self.GIB), 4)
        self.assertEqual(runner.worker_budget(0, 4, 100 * self.GIB), 4)

    def test_a_targeted_run_takes_few_workers(self) -> None:
        import runner

        alone = runner.worker_budget(0, 32, 100 * self.GIB, targeted=True)
        self.assertEqual(alone, runner.TARGETED_WORKERS)
        self.assertEqual(runner.worker_budget(20, 32, 100 * self.GIB, targeted=True), 2)

    def test_a_busy_host_gets_fewer_workers_but_never_fewer_than_four(self) -> None:
        import runner

        limit = runner.pytest_phases.AUTO_LIMIT
        self.assertEqual(runner.worker_budget(0, 32, 100 * self.GIB, load=8.0), min(limit, 20))
        self.assertEqual(runner.worker_budget(0, 32, 100 * self.GIB, load=22.0), 6)
        self.assertEqual(runner.worker_budget(0, 32, 100 * self.GIB, load=90.0), 4)


class EgressNetwork(unittest.TestCase):
    FULL = "Error response from daemon: all predefined address pools have been fully subnetted"

    def create(self, answers: list[str], wait: float) -> int:
        """Runs create_network against a Docker that answers with these errors ('' = created)."""
        import runner

        calls = []

        def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            error = answers[min(len(calls), len(answers) - 1)]
            calls.append(args)
            return subprocess.CompletedProcess(args, 1 if error else 0, "", error)

        with (
            mock.patch.object(runner, "docker", docker),
            mock.patch.object(runner, "NETWORK_RETRY_SECONDS", 0.01),
            mock.patch.object(runner, "say", lambda message: None),
        ):
            runner.create_network("atci-x-egress", ["--label", "a=1"], "job", wait)
        self.assertEqual(calls[-1], ("network", "create", "--label", "a=1", "atci-x-egress"))
        return len(calls)

    def test_a_job_waits_for_a_free_subnet(self) -> None:
        self.assertEqual(self.create([self.FULL, self.FULL, ""], 30), 3)

    def test_the_wait_ends_in_a_failure(self) -> None:
        with self.assertRaises(RuntimeError):
            self.create([self.FULL], 0.05)

    def test_another_error_fails_at_once(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            self.create(["permission denied", ""], 30)


class ShardComparison(unittest.TestCase):
    MARK = "== all shards: tests=5 failures=0 errors=0 skipped=0 ==\n"

    def summary(self, *lines: str, mark: bool = True) -> list[str]:
        import compare

        text = "".join(f"{line} in 1.50s\n" for line in lines) + (self.MARK if mark else "")
        return compare.evidence(text)["pytest summary"]

    def test_another_split_of_the_same_tests_is_equal(self) -> None:
        two = self.summary("2 passed, 9 deselected", "3 passed")
        three = self.summary("1 passed, 9 deselected", "3 passed", "1 passed")
        self.assertEqual(two, three)

    def test_a_missing_or_failed_test_is_a_difference(self) -> None:
        base = self.summary("2 passed, 9 deselected", "3 passed")
        for other in (
            ("2 passed, 9 deselected", "2 passed"),
            ("2 passed, 9 deselected", "2 passed", "1 failed"),
            ("2 passed, 8 deselected", "3 passed"),
            ("2 passed, 9 deselected", "3 passed, 1 skipped"),
        ):
            self.assertNotEqual(base, self.summary(*other), other)

    def test_other_tests_of_the_same_number_are_a_difference(self) -> None:
        import compare

        line = "== inventory: all 5 selected tests have exactly one result, sha256={} =="
        ours = compare.evidence("5 passed in 1.50s\n" + line.format("a" * 64) + "\n")
        theirs = compare.evidence("5 passed in 1.50s\n" + line.format("b" * 64) + "\n")
        self.assertEqual(ours["pytest summary"], theirs["pytest summary"])
        self.assertTrue(ours["test inventory"])
        self.assertNotEqual(ours["test inventory"], theirs["test inventory"])
        missing = compare.evidence("5 passed in 1.50s\n")
        self.assertNotEqual(ours["test inventory"], missing["test inventory"])

    def test_a_job_without_shards_is_compared_run_by_run(self) -> None:
        self.assertEqual(
            self.summary("2 passed", "3 passed", mark=False), ["2 passed", "3 passed"]
        )


class Workspaces(unittest.TestCase):
    def test_cleanup_looks_at_every_place_a_workspace_can_be(self) -> None:
        import runner

        roots = runner.work_roots()
        self.assertIn(runner.TMPFS_WORK, roots)
        self.assertIn(runner.STATE / "work", roots)

    def test_a_directory_of_another_user_is_refused(self) -> None:
        import runner

        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "work"
            link.symlink_to("/")
            with self.assertRaises((SystemExit, OSError)):
                runner.private_directory(link)


class Ownership(unittest.TestCase):
    """Cleanup and locks (INFRA-CI-02-REC-01). Every path is below a temporary directory and
    Docker is a stand-in: nothing here can reach a real run or workspace."""

    MINE = "20260101-000000-aaaaaa"
    OTHER = "20260101-000000-bbbbbb"

    def setUp(self) -> None:
        import runner

        self.runner = runner
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.state = self.base / "state-a"
        self.other_state = self.base / "state-b"
        self.shared = self.base / "shm-work"
        for directory in (self.state, self.other_state, self.shared):
            directory.mkdir(mode=0o700)
        self.listings: dict[str, list[str]] = {}
        self.removed: list[tuple[str, ...]] = []
        self.said: list[str] = []
        patches = {
            "STATE": self.state,
            "TMPFS_WORK": self.shared,
            "RESULTS": self.base / "results",
            "ACTIVITY_LOCK": self.base / "host" / "activity.lock",
            "docker": self.docker,
            "say": self.said.append,
        }
        for name, value in patches.items():
            patcher = mock.patch.object(runner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def docker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        out = ""
        if "rm" in args[:2]:
            self.removed.append(args)
        elif args[0] == "ps":
            out = "\n".join(self.listings.get("containers", []))
        elif args[:2] == ("network", "ls"):
            out = "\n".join(self.listings.get("networks", []))
        elif args[:2] == ("image", "ls") and f"label={self.runner.LABEL}.run" in args:
            out = "\n".join(x.split("|")[0] for x in self.listings.get("images", []))
        elif args[:2] == ("image", "inspect"):
            owners = dict(
                (x.split("\t")[0], x.split("|")[1]) for x in self.listings.get("images", [])
            )
            out = owners[args[2]] + "\n"
        elif args[:2] == ("volume", "ls"):
            out = "atci-uv-cache"
        return subprocess.CompletedProcess(args, 0, out, "")

    def clean(self, state: Path | None = None, **options: Any) -> None:
        import argparse

        values = {"dry_run": False, "caches": False, "results_older_than": None, **options}
        with mock.patch.object(self.runner, "STATE", state or self.state):
            self.runner.cleanup(argparse.Namespace(**values))

    def workspace(self, run: str, state: Path | None = None, root: Path | None = None) -> Path:
        with mock.patch.object(self.runner, "STATE", state or self.state):
            self.runner.claim_workspace(root or self.shared, run)
        directory = (root or self.shared) / run
        (directory / "data").write_text("x")
        return directory

    def lock(self, run: str, state: Path | None = None) -> Any:
        """The context of a running run of ``state``."""
        from contextlib import contextmanager

        @contextmanager
        def held() -> Any:
            with mock.patch.object(self.runner, "STATE", state or self.state):
                lock = self.runner.run_lock(run)
                lock.__enter__()
            try:
                yield
            finally:
                lock.__exit__(None, None, None)

        return held()

    def test_a_cleanup_removes_the_finished_workspaces_of_its_own_state_only(self) -> None:
        mine = self.workspace(self.MINE)
        theirs = self.workspace(self.OTHER, state=self.other_state)
        self.clean()
        self.assertFalse(mine.exists())
        self.assertTrue((theirs / "data").exists())
        self.clean(state=self.other_state)
        self.assertFalse(theirs.exists())

    def test_another_state_directory_never_removes_an_active_workspace(self) -> None:
        active = self.workspace(self.MINE)
        with self.lock(self.MINE):
            self.clean(state=self.other_state)  # cannot see this run's lock
            self.assertTrue((active / "data").exists())
            self.clean()  # sees it
            self.assertTrue((active / "data").exists())
        self.clean()
        self.assertFalse(active.exists())

    def test_what_cannot_be_proven_ours_is_kept(self) -> None:
        run = self.runner
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "precious").write_text("x")
        record = json.dumps({"run": self.MINE, "state": str(self.state)})
        (outside / run.OWNER_FILE).write_text(record)
        cases: dict[str, Path] = {}
        # a link with a run's name to a directory that even carries a matching record
        (self.shared / self.MINE).symlink_to(outside)
        cases["link"] = self.shared / self.MINE

        def directory(name: str, owner: str | None) -> Path:
            made = self.shared / name
            made.mkdir()
            (made / "data").write_text("x")
            if owner is not None:
                (made / run.OWNER_FILE).write_text(owner)
            return made

        def owner(name: str) -> str:
            return json.dumps({"run": name, "state": str(self.state)})

        names = [f"20260101-000000-{n:06x}" for n in range(1, 8)]
        cases["no record"] = directory(names[0], None)
        cases["unreadable record"] = directory(names[1], "{")
        cases["record of another run"] = directory(names[2], owner(self.OTHER))
        cases["foreign name"] = directory("keep-me", owner("keep-me"))
        cases["linked record"] = directory(names[3], None)
        (outside / "record").write_text(owner(names[3]))
        (cases["linked record"] / run.OWNER_FILE).symlink_to(outside / "record")
        cases["writable by others"] = directory(names[4], owner(names[4]))
        cases["writable by others"].chmod(0o777)
        cases["incomplete record"] = directory(names[5], json.dumps({"run": names[5]}))
        cases["file"] = self.shared / names[6]
        cases["file"].write_text("x")
        self.clean()
        for label, path in cases.items():
            with self.subTest(label):
                self.assertTrue(os.path.lexists(path))
        self.assertEqual((outside / "precious").read_text(), "x")

    def test_a_workspace_or_record_of_another_user_is_kept(self) -> None:
        mine = self.workspace(self.MINE)
        someone = os.getuid() + 1
        with mock.patch.object(self.runner.os, "getuid", return_value=someone):
            self.assertIn("another user", self.runner.foreign_workspace(mine) or "")
            self.assertIsNone(self.runner.read_owner(mine))
            self.clean()
        self.assertTrue(mine.exists())

    def test_an_unsafe_workspace_root_is_not_entered(self) -> None:
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        for label in ("link", "open to others"):
            with self.subTest(label):
                kept = self.workspace(self.MINE, root=elsewhere)
                root = elsewhere
                if label == "link":
                    self.shared.rmdir()
                    self.shared.symlink_to(elsewhere)
                    root = self.shared
                else:
                    elsewhere.chmod(0o777)
                with mock.patch.object(self.runner, "TMPFS_WORK", root):
                    self.clean()
                self.assertTrue((kept / "data").exists())
                self.assertTrue(any("keeping everything below" in line for line in self.said))
                self.said.clear()
                elsewhere.chmod(0o700)
                if label == "link":
                    self.shared.unlink()
                    self.shared.mkdir(mode=0o700)
                self.runner.shutil.rmtree(kept)

    def test_a_run_never_takes_an_existing_directory_as_its_workspace(self) -> None:
        (self.shared / self.MINE).mkdir()
        with self.assertRaises(FileExistsError):
            self.runner.claim_workspace(self.shared, self.MINE)
        self.shared.chmod(0o777)
        with self.assertRaises(RuntimeError):
            self.runner.claim_workspace(self.shared, self.OTHER)

    def test_containers_networks_and_images_of_other_state_directories_are_kept(self) -> None:
        mine, theirs = str(self.state), str(self.other_state)
        running = "20260101-000000-cccccc"
        for kind in ("containers", "networks"):
            self.listings[kind] = [
                f"{kind}-mine\tatci-{self.MINE}-x\t{self.MINE}\t{mine}",
                f"{kind}-theirs\tatci-{self.OTHER}-x\t{self.OTHER}\t{theirs}",
                f"{kind}-unlabelled\tatci-{self.OTHER}-y\t{self.OTHER}\t",
                f"{kind}-running\tatci-{running}-x\t{running}\t{mine}",
                f"{kind}-foreign\tinfra-redis\t{self.MINE}\t{mine}",
            ]
        self.listings["images"] = [
            f"i-mine\tatci-{self.MINE}-k|{self.MINE}\t{mine}",
            f"i-theirs\tatci-{self.OTHER}-k|{self.OTHER}\t{theirs}",
        ]
        with self.lock(running):
            self.clean()
        self.assertEqual(
            self.removed,
            [
                ("rm", "-f", "-v", "containers-mine"),
                ("network", "rm", "networks-mine"),
                ("image", "rm", "-f", "i-mine"),
            ],
        )

    def test_everything_a_run_creates_carries_its_state_directory(self) -> None:
        job = mock.Mock(key="test")
        run = mock.Mock(run_id=self.MINE, work=self.shared, directory=self.base / "results")
        labels = self.runner.JobRun(run, mock.Mock(job=job)).labels()
        self.assertEqual(labels[self.runner.STATE_LABEL], str(self.state))
        compose = yaml.safe_load((REPO / "compose.ci.yml").read_text())
        for name, service in compose["services"].items():
            with self.subTest(name):
                self.assertIn(self.runner.STATE_LABEL, service["labels"])

    def test_caches_stay_while_a_run_of_any_state_directory_lives(self) -> None:
        volume = ("volume", "rm", "atci-uv-cache")
        with self.runner.host_activity() as running:  # a run of another state directory
            self.assertTrue(running)
            self.clean(caches=True)
        self.assertNotIn(volume, self.removed)
        self.clean(caches=True)
        self.assertIn(volume, self.removed)

    def test_a_lock_removed_while_a_run_takes_it_is_taken_again(self) -> None:
        import fcntl

        real, calls = fcntl.flock, []
        path = self.state / "locks" / f"{self.MINE}.lock"

        def flock(handle: Any, operation: int) -> None:
            real(handle, operation)
            if operation == fcntl.LOCK_EX and not calls:
                path.unlink()  # a cleanup removed it between open and lock
            calls.append(operation)

        with mock.patch.object(self.runner.fcntl, "flock", flock):
            lock = self.runner.run_lock(self.MINE)
            lock.__enter__()
        try:
            self.assertTrue(self.runner.is_active(self.MINE))
        finally:
            lock.__exit__(None, None, None)
        self.assertFalse(path.exists())

    def test_a_held_lock_is_never_removed(self) -> None:
        path = self.state / "locks" / f"{self.MINE}.lock"
        with self.lock(self.MINE):
            self.runner.remove_stale_lock(path)
            self.assertTrue(self.runner.is_active(self.MINE))
        path.write_text("stale")
        self.runner.remove_stale_lock(path)
        self.assertFalse(path.exists())

    def test_old_results_another_state_directory_may_be_writing_are_kept(self) -> None:
        results = self.base / "results"

        def result(name: str, state: Path | None, finished: bool) -> Path:
            directory = results / name
            directory.mkdir(parents=True)
            if state:
                with mock.patch.object(self.runner, "STATE", state):
                    self.runner.write_owner(directory, name)
            if finished:
                (directory / "summary.json").write_text("{}")
            os.utime(directory, (0, 0))
            return directory

        running = result(self.MINE, self.other_state, finished=False)
        unknown = result("20260101-000000-000001", None, finished=False)
        mine = result("20260101-000000-000002", self.state, finished=False)
        done = result("20260101-000000-000003", self.other_state, finished=True)
        self.clean(results_older_than=1)
        self.assertEqual(
            [p.exists() for p in (running, unknown, mine, done)], [True, True, False, False]
        )


class StateDirectory(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def test_an_unsafe_state_directory_is_refused_and_left_as_it_is(self) -> None:
        import runner

        opened = self.base / "open"
        opened.mkdir()
        opened.chmod(0o1777)
        target = self.base / "target"
        target.mkdir(mode=0o700)
        (self.base / "link").symlink_to(target)
        (self.base / "dangling").symlink_to(self.base / "nowhere")
        (self.base / "file").write_text("x")
        cases = {
            "relative": Path("state"),
            "root": Path("/"),
            "top level": Path("/tmp"),  # noqa: S108
            "not normalised": self.base / "target" / ".." / "target",
            "open to others": opened,
            "link": self.base / "link",
            "below a link": self.base / "link" / "state",
            "dangling link": self.base / "dangling",
            "file": self.base / "file",
        }
        modes = {p: p.stat().st_mode for p in (opened, target, Path("/"), Path("/tmp"))}  # noqa: S108
        for label, path in cases.items():
            with self.subTest(label), self.assertRaises(SystemExit):
                runner.private_directory(path)
        for path, mode in modes.items():
            self.assertEqual(path.stat().st_mode, mode, path)
        self.assertFalse((self.base / "nowhere").exists())

    def test_a_new_state_directory_is_private(self) -> None:
        import runner

        made = self.base / "a" / "state"
        runner.private_directory(made)
        runner.private_directory(made)
        self.assertEqual(made.stat().st_mode & 0o777, 0o700)


class RunReport(unittest.TestCase):
    @staticmethod
    def suite(source: str, tests: int, deselected: int) -> dict[str, Any]:
        zero = {"failed": 0, "errors": 0, "skipped": 0}
        return {"source_name": source, "tests": tests, "passed": tests,
                "deselected": deselected, **zero}  # fmt: skip

    def test_the_parts_of_a_suite_are_counted_as_one(self) -> None:
        found = report.primary_suites(
            [
                self.suite("junit-parallel.xml", 90, 30),  # 120 collected: 20 are left out
                self.suite("junit-serial.xml", 10, 110),
                self.suite("junit-identity-primary.xml", 50, 0),
                self.suite("junit-identity-shard1.xml", 40, 7),
            ]
        )
        main, identity = found["junit.xml"], found["junit-identity.xml"]
        self.assertEqual((main["tests"], main["deselected"]), (100, 20))
        self.assertEqual((identity["tests"], identity["deselected"]), (90, 7))


class Redaction(unittest.TestCase):
    def test_credentials_and_tokens_are_removed(self) -> None:
        redact = report.Redactor(
            [{"X_PASSWORD": "pw-value-123", "DB_URL": "postgresql://u:url-secret-9@h/db"}]
        )
        token = ".".join(("eyJ" + "a" * 20, "b" * 20, "c" * 20))
        text = redact(f"pw-value-123 url-secret-9 {token} Bearer {'d' * 30} redis://:zzz@h/0")
        for secret in ("pw-value-123", "url-secret-9", token, "d" * 30, ":zzz@"):
            self.assertNotIn(secret, text)

    def test_token_identifiers_in_keycloak_event_lines_are_removed(self) -> None:
        line = 'type="X", token_id="id-1", refresh_token_id="id-2", refresh_token_sub="id-3"'
        text = report.Redactor([])(line + ', code_id="id-4", realmName="kept"')
        for identifier in ("id-1", "id-2", "id-3", "id-4"):
            self.assertNotIn(identifier, text)
        self.assertIn('realmName="kept"', text)


class Snapshots(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "dev")
        (self.repo / ".gitignore").write_text(".secrets/\n")
        (self.repo / "a.txt").write_text("one\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "c")

    def git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True
        )
        return done.stdout

    def test_a_clean_tree_is_identified_by_the_commit_tree(self) -> None:
        taken = snapshot.take(self.repo, None)
        self.assertFalse(taken.dirty)
        self.assertEqual(taken.tree, self.git("rev-parse", "HEAD^{tree}").strip())

    def test_uncommitted_files_are_tested_secrets_are_not_and_the_index_is_untouched(self) -> None:
        (self.repo / "a.txt").write_text("two\n")
        (self.repo / "new.py").write_text("x = 1\n")
        (self.repo / ".env").write_text("A=1\n")
        (self.repo / "server.key").write_text("k\n")
        (self.repo / ".secrets").mkdir()
        (self.repo / ".secrets" / "db").write_text("s\n")
        before = self.git("status", "--porcelain")
        taken = snapshot.take(self.repo, None)
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertTrue(taken.dirty)
        files = self.git("ls-tree", "-r", "--name-only", taken.tree).split()
        self.assertEqual(files, [".gitignore", "a.txt", "new.py"])
        self.assertEqual(sorted(taken.excluded), [".env", "server.key"])
        target = Path(self.temporary.name) / "copy"
        snapshot.materialise(taken, target)
        self.assertEqual((target / "a.txt").read_text(), "two\n")
        self.assertTrue((target / "new.py").exists())
        self.assertFalse((target / ".env").exists())

    def test_only_the_history_github_would_have_is_copied(self) -> None:
        first = self.git("rev-parse", "HEAD").strip()
        identity = ("-c", "user.name=t", "-c", "user.email=t@example.test")
        self.git("checkout", "-q", "-b", "private")
        (self.repo / "local-only.txt").write_text("unpushed\n")
        self.git("add", "-A")
        self.git(*identity, "commit", "-qm", "unpushed")
        private = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "dev")
        self.git(*identity, "commit", "-qm", "later", "--allow-empty")
        target = Path(self.temporary.name) / "old"
        snapshot.materialise(snapshot.take(self.repo, first), target)
        run = ["git", "-C", str(target)]
        history = subprocess.run(
            [*run, "rev-list", "--all"], check=True, capture_output=True, text=True
        ).stdout.split()
        self.assertEqual(history, [first])
        missing = subprocess.run([*run, "cat-file", "-e", private], capture_output=True)
        self.assertNotEqual(missing.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
