"""The content under test is a git tree: either of a commit (``--ref``) or of the working tree,
including uncommitted and untracked (not ignored) files. Each job gets its own clone of it, so
files edited while CI runs do not change the result, and CI cannot write into the real tree.

Only git objects are added to the source repository; its index, refs and files are untouched.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Untracked files with these names are never copied into a CI workspace, ignored or not.
SENSITIVE = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*secret*.json",
    "credentials*.json",
)
# Check out LFS pointers, as actions/checkout does without `lfs: true`.
NO_LFS = (
    "-c",
    "filter.lfs.smudge=cat",
    "-c",
    "filter.lfs.clean=cat",
    "-c",
    "filter.lfs.process=",
    "-c",
    "filter.lfs.required=false",
    "-c",
    "core.hooksPath=/dev/null",
)


@dataclass
class Snapshot:
    source: Path
    commit: str  # HEAD, or the commit named by --ref
    branch: str
    tree: str  # identity of the content under test
    dirty: bool
    changes: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", **(env or {})},
    )
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.rstrip("\n")


def take(source: Path, ref: str | None) -> Snapshot:
    branch = git(source, "rev-parse", "--abbrev-ref", "HEAD")
    if ref:
        commit = git(source, "rev-parse", "--verify", f"{ref}^{{commit}}")
        tree = git(source, "rev-parse", f"{commit}^{{tree}}")
        return Snapshot(source, commit, branch, tree, dirty=False)
    commit = git(source, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory(prefix="atci-index-") as temporary:
        index = Path(temporary) / "index"
        real = Path(git(source, "rev-parse", "--absolute-git-dir")) / "index"
        shutil.copy2(real, index)
        env = {"GIT_INDEX_FILE": str(index)}
        untracked = git(source, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        excluded = [
            path
            for path in untracked
            if path
            and not path.endswith(".example")
            and any(fnmatch.fnmatch(Path(path).name.lower(), pattern) for pattern in SENSITIVE)
        ]
        pathspec = [".", *[f":(exclude,literal){path}" for path in excluded]]
        git(source, "-c", "core.hooksPath=/dev/null", "add", "-A", "--", *pathspec, env=env)
        tree = git(source, "write-tree", env=env)
    changes = git(source, "diff-tree", "-r", "--name-status", commit, tree).splitlines()
    return Snapshot(source, commit, branch, tree, bool(changes), changes, excluded)


def history_refs(snapshot: Snapshot) -> dict[str, str]:
    """The refs a full-history checkout on GitHub would have for this commit: the tested branch
    at the commit, the other branches of origin as last fetched, and the tags. Other local
    refs (unpushed branches, stashes, editor checkpoints) are neither copied nor scanned."""
    listing = git(
        snapshot.source,
        "for-each-ref",
        "--format=%(refname) %(objectname) %(symref)",
        "refs/remotes/origin",
        "refs/tags",
    )
    refs: dict[str, str] = {}
    for line in listing.splitlines():
        name, target, *symbolic = line.split()
        if not symbolic and name != f"refs/remotes/origin/{snapshot.branch}":
            refs[name] = target
    branch = snapshot.branch if snapshot.branch != "HEAD" else "ci-snapshot"
    refs[f"refs/heads/{branch}"] = snapshot.commit
    refs[f"refs/remotes/origin/{branch}"] = snapshot.commit
    return refs


def materialise(snapshot: Snapshot, target: Path) -> None:
    """A new repository holding only the history of ``history_refs`` (for the secret scan) and
    the files of the snapshot tree. Nothing else of the source object store is copied."""
    refs = history_refs(snapshot)
    subprocess.run(  # noqa: S603
        ["git", "init", "--quiet", str(target)], check=True, capture_output=True
    )
    wanted = "".join(f"{sha}\n" for sha in sorted({*refs.values(), snapshot.tree}))
    with tempfile.TemporaryFile() as pack:
        subprocess.run(  # noqa: S603
            ["git", "-C", str(snapshot.source), "pack-objects", "--revs", "--stdout", "-q"],
            input=wanted.encode(),
            stdout=pack,
            stderr=subprocess.PIPE,
            check=True,
        )
        pack.seek(0)
        subprocess.run(  # noqa: S603
            ["git", "-C", str(target), "index-pack", "--stdin", "--fix-thin"],
            stdin=pack,
            capture_output=True,
            check=True,
        )
    for name, sha in refs.items():
        git(target, "update-ref", name, sha)
    branch = snapshot.branch if snapshot.branch != "HEAD" else "ci-snapshot"
    git(target, *NO_LFS, "checkout", "--quiet", "--force", branch)
    git(target, *NO_LFS, "read-tree", "--reset", "-u", snapshot.tree)


def export(target: Path, destination: Path) -> None:
    """Plain files of the snapshot, without history, for the scan of uncommitted content."""
    destination.mkdir()
    git(target, *NO_LFS, "checkout-index", "--all", f"--prefix={destination}/")
