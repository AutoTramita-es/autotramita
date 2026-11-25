"""Guard rails of the Local CI runner, checked without Docker: it must refuse what it cannot
reproduce, never report PASS for something that did not run, and never let a CI step reach
outside its workspace. Run: python3 scripts/ci/selftest.py
"""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

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
