"""Host side of the docker stand-in. A CI step may start only the images named by the workflow,
mount only paths of its own workspace, and use only the isolated network namespace of its job
(`--network host`, as written in ci.yml) or no network at all. It may build exactly one image,
the AutoTramita Keycloak image, from a directory of its own workspace, from base images the
workflow names by digest, without network and without the build cache, from a Dockerfile that
pulls nothing else. It may save that image into its workspace for the scanner. Only the pinned
Trivy image reaches a network, and only to download its vulnerability databases into the
workspace (the job's egress network); every scan runs without network. Anything else is refused.

No Docker socket is ever mounted into a container that runs repository code.
"""

from __future__ import annotations

import json
import os
import re
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
RUNNER_UID = 1001
# The scanner: its downloads are the only network access a started container gets.
SCANNER = re.compile(r"aquasec/trivy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}")
SCANNER_DOWNLOADS = (
    ["--cache-dir", "/cache", "image", "--download-db-only", "--no-progress"],
    ["--cache-dir", "/cache", "image", "--download-java-db-only", "--no-progress"],
)
# Dockerfile instructions that would reach past the pinned base images or the sandbox.
FROM_LINE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
COPY_FROM = re.compile(r"--from=(\S+)", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"^\s*ADD\b|--network|--security|--mount=type=(?:ssh|secret|cache)|--privileged",
    re.IGNORECASE,
)


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
    egress: str = ""  # the job's egress network, only for the scanner's downloads
    created: set[str] = field(default_factory=set)
    built: dict[str, str] = field(default_factory=dict)  # name in ci.yml -> tag of this job
    saved: list[Path] = field(default_factory=list)  # image archives written for the scanner

    def command(self, argv: list[str]) -> list[str]:
        if not argv:
            raise Refused("empty docker command")
        verb, rest = argv[0], argv[1:]
        if verb == "run":
            return self._run(rest)
        if verb == "build":
            return self._build(rest)
        if verb == "save":
            return self._save(rest)
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
        context = self._context(args[index], BUILDABLE[tag])
        self._check_dockerfile(context / "Dockerfile")
        actual = f"{self.prefix}-{tag}"
        self.built[tag] = actual
        return [*out, "--no-cache", "--tag", actual, str(context)]

    def _context(self, given: str, expected: str) -> Path:
        """The build context: exactly the expected directory of the job's source tree, reached
        without any symbolic link (resolving both sides would accept a link pointing out)."""
        source = self.workspace / "src"
        wanted = source / expected
        if os.path.normpath(given) != str(wanted):
            raise Refused(f"build context {given!r} is not allowed")
        current = source
        for part in Path(expected).parts:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise Refused(f"build context {given!r} is not allowed")
        if source.resolve() not in wanted.resolve().parents:
            raise Refused(f"build context {given!r} is not allowed")
        return wanted

    def _check_dockerfile(self, path: Path) -> None:
        """Nothing in the Dockerfile may pull past the pinned images or leave the sandbox: no
        parser directive (a ``syntax`` frontend is an image), no ADD (it downloads), no
        ``--network``/``--security``/ssh, secret or cache mounts, FROM and ``COPY --from`` only
        the two build arguments or a stage of the same file, every ARG default an allowed image."""
        if path.is_symlink() or not path.is_file():
            raise Refused("the Dockerfile must be a regular file")
        stages: set[str] = set()
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if line.startswith("#"):
                if re.match(r"#\s*\w+\s*=", line):
                    raise Refused(f"Dockerfile line {number}: parser directives are not allowed")
                continue
            if FORBIDDEN.search(line):
                raise Refused(f"Dockerfile line {number}: {line.split()[0]} is not allowed")
            if line.upper().startswith("ARG ") and "=" in line:
                name, _, default = line[4:].partition("=")
                if name.strip() not in BUILD_ARGS or default.strip() not in self.images:
                    raise Refused(f"Dockerfile line {number}: ARG default is not an allowed image")
            match = FROM_LINE.match(line)
            if line.upper().startswith("FROM"):
                if not match or match.group(1) not in {f"${{{a}}}" for a in BUILD_ARGS}:
                    raise Refused(f"Dockerfile line {number}: FROM must name a build argument")
                if match.group(2):
                    stages.add(match.group(2).lower())
            for source in COPY_FROM.findall(line):
                if source.lower() not in stages:
                    raise Refused(f"Dockerfile line {number}: COPY --from must name a stage")

    def _save(self, args: list[str]) -> list[str]:
        """``save --output <workspace file> <image built by this job>``, for the scanner."""
        if len(args) != 3 or args[0] not in ("-o", "--output"):
            raise Refused("docker save needs --output <file> and the built image")
        image = self.built.get(args[2])
        if image is None:
            raise Refused(f"image {args[2]!r} was not built by this job")
        target = Path(os.path.normpath(args[1]))
        parent = target.parent
        if (
            not target.is_absolute()
            or target.exists()
            or target.is_symlink()
            or parent.is_symlink()
            or not parent.is_dir()
            or self.workspace not in Path(os.path.realpath(parent)).parents
        ):
            raise Refused(f"output {args[1]!r} is not allowed")
        self.saved.append(target)
        return ["docker", "save", "--output", str(target), image]

    def finish(self, argv: list[str]) -> None:
        """After a successful command: an archive written by the daemon (as root) is handed to the
        step's user, read only."""
        if argv and argv[0] == "save" and self.saved:
            target = self.saved[-1]
            os.chown(target, RUNNER_UID, RUNNER_UID)
            os.chmod(target, 0o444)

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
                if value == "host":
                    network = f"container:{self.netns}"
                elif value == "none":
                    network = "none"
                else:
                    raise Refused(f"network {value!r} is not allowed")
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
        command = args[index + 1 :]
        if SCANNER.fullmatch(image) and command in SCANNER_DOWNLOADS:
            # The only container with a network: the pinned scanner fetching its databases.
            if "--network" in args[:index] or not self.egress:
                raise Refused("the scanner downloads only through the job's egress network")
            if sum(1 for a in args[:index] if a in ("-v", "--volume")) != 1:
                raise Refused("the scanner download mounts exactly its cache")
            network = self.egress
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
            if code == 0:
                self.policy.finish(argv)
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
