"""Host side of the docker stand-in. A CI step may start only the images named by the workflow,
mount only paths of its own workspace, and use only the isolated network namespace of its job
(`--network host`, as written in ci.yml) or no network at all. It may build exactly one image,
the AutoTramita Keycloak image, from a directory of its own workspace, from base images the
workflow names by digest, without network. Anything else is refused.

No Docker socket is ever mounted into a container that runs repository code.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

RUNNER_USER = "1001:1001"
# The only image a step may build, and the only build arguments it may pass (each must be one
# of the pinned images named by the workflow).
BUILDABLE = {"autotramita-keycloak:ci": "identity/keycloak"}
BUILD_ARGS = frozenset({"KEYCLOAK_IMAGE", "JDK_IMAGE"})


class Refused(Exception):
    """The request is outside the policy."""


@dataclass
class Policy:
    prefix: str  # name prefix of every container this job may create
    labels: dict[str, str]
    netns: str  # id of the container that owns the job's network namespace
    workspace: Path
    read_only_roots: tuple[Path, ...]
    images: frozenset[str]
    created: set[str] = field(default_factory=set)
    built: dict[str, str] = field(default_factory=dict)  # name in ci.yml -> tag of this job

    def command(self, argv: list[str]) -> list[str]:
        if not argv:
            raise Refused("empty docker command")
        verb, rest = argv[0], argv[1:]
        if verb == "run":
            return self._run(rest)
        if verb == "build":
            return self._build(rest)
        if verb == "logs" and len(rest) == 1:
            return ["docker", "logs", self._own(rest[0])]
        if verb == "rm" and len(rest) == 2 and rest[0] == "-f":
            return ["docker", "rm", "-f", self._own(rest[1])]
        raise Refused(f"docker {' '.join(argv[:2])} is not allowed in Local CI")

    def _own(self, name: str) -> str:
        full = f"{self.prefix}-{name}"
        if full not in self.created:
            raise Refused(f"container {name!r} was not created by this job")
        return full

    def _volume(self, spec: str) -> str:
        parts = spec.split(":")
        if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "ro"):
            raise Refused(f"mount {spec!r} is not allowed")
        source, target = parts[0], parts[1]
        if not source.startswith("/") or not target.startswith("/") or "," in spec:
            raise Refused(f"mount {spec!r} is not allowed")
        resolved = Path(os.path.realpath(source))
        if self.workspace not in resolved.parents:
            raise Refused(f"mount source {source!r} is outside the job workspace")
        read_only = len(parts) == 3 or resolved in self.read_only_roots
        return f"{resolved}:{target}" + (":ro" if read_only else "")

    def _build(self, args: list[str]) -> list[str]:
        out = ["docker", "build", "--network", "none"]
        for key, value in self.labels.items():
            out += ["--label", f"{key}={value}"]
        tag = ""
        index = 0
        while index < len(args) and args[index].startswith("-"):
            flag = args[index]
            if index + 1 >= len(args):
                raise Refused(f"flag {flag} has no value")
            value = args[index + 1]
            if flag in ("-t", "--tag"):
                if value not in BUILDABLE or tag:
                    raise Refused(f"image {value!r} may not be built in Local CI")
                tag = value
            elif flag == "--build-arg":
                key, _, image = value.partition("=")
                if key not in BUILD_ARGS or image not in self.images:
                    raise Refused(f"build argument {value!r} is not allowed")
                out += ["--build-arg", value]
            else:
                raise Refused(f"docker build flag {flag} is not allowed in Local CI")
            index += 2
        if not tag or index != len(args) - 1:
            raise Refused("docker build needs one --tag and one context directory")
        context = Path(os.path.realpath(args[index]))
        if context != (self.workspace / "src" / BUILDABLE[tag]).resolve():
            raise Refused(f"build context {args[index]!r} is not allowed")
        actual = f"{self.prefix}-{tag}"
        self.built[tag] = actual
        return [*out, "--tag", actual, str(context)]

    def _run(self, args: list[str]) -> list[str]:
        out = ["docker", "run", "--security-opt", "no-new-privileges:true"]
        for key, value in self.labels.items():
            out += ["--label", f"{key}={value}"]
        name = ""
        network = "none"
        index = 0
        while index < len(args) and args[index].startswith("-"):
            flag = args[index]
            if flag in ("-d", "--detach", "--rm"):
                out.append(flag)
                index += 1
                continue
            if index + 1 >= len(args):
                raise Refused(f"flag {flag} has no value")
            value = args[index + 1]
            if flag == "--name":
                if not value.replace("-", "").replace("_", "").isalnum():
                    raise Refused(f"container name {value!r} is not allowed")
                name = value
            elif flag == "--network":
                if value != "host":
                    raise Refused(f"network {value!r} is not allowed")
                network = f"container:{self.netns}"
            elif flag in ("-e", "--env"):
                if "=" not in value:
                    raise Refused("environment values must be explicit")
                out += ["-e", value]
            elif flag in ("-v", "--volume"):
                out += ["-v", self._volume(value)]
            elif flag in ("-u", "--user"):
                if value != RUNNER_USER:
                    raise Refused(f"user {value!r} is not allowed")
                out += ["--user", value]
            else:
                raise Refused(f"docker run flag {flag} is not allowed in Local CI")
            index += 2
        if index >= len(args):
            raise Refused("no image given")
        image = self.built.get(args[index], args[index])
        if image not in self.images and image not in self.built.values():
            raise Refused(f"image {image!r} is not named by the workflow or the contract script")
        full = f"{self.prefix}-{name or f'anon{len(self.created)}'}"
        self.created.add(full)
        return [*out, "--name", full, "--network", network, image, *args[index + 1 :]]


class Broker:
    """Serves the request files of one job until stopped."""

    def __init__(self, directory: Path, policy: Policy) -> None:
        self.directory = directory
        self.policy = policy
        self.refusals: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._process and self._process.poll() is None:
            self._process.kill()
        self._thread.join(timeout=10)

    def _serve(self) -> None:
        while not self._stop.is_set():
            for request in sorted(self.directory.glob("*.req")):
                self._handle(request)
            time.sleep(0.1)

    def _handle(self, request: Path) -> None:
        try:
            # The request directory is writable by test code: never follow a link out of it.
            if request.is_symlink():
                raise Refused("request must be a regular file")
            argv = json.loads(request.read_text(encoding="utf-8"))["argv"]
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                raise Refused("malformed request")
            command = self.policy.command(argv)
            self._process = subprocess.Popen(  # noqa: S603
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace"
            )
            stdout, stderr = self._process.communicate()
            code = self._process.returncode
        except Refused as refusal:
            self.refusals.append(str(refusal))
            stdout, stderr, code = "", f"Local CI refused: {refusal}\n", 125
        except (OSError, ValueError, KeyError) as error:
            stdout, stderr, code = "", f"Local CI broker error: {error}\n", 125
        request.unlink(missing_ok=True)
        response = request.with_suffix(".res")
        temporary = request.with_suffix(".part")
        temporary.unlink(missing_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"stdout": stdout, "stderr": stderr, "code": code}, handle)
        os.replace(temporary, response)
