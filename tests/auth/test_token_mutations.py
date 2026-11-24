"""AC-TOK-07: every check of the access-token validator is necessary.

Each ``if ...: raise`` of ``verify_signed`` and ``TokenValidator._check_claims`` is switched off
in turn in a throw-away copy of the sources, and the ordinary token tests are run against that
copy. A mutant the tests do not notice fails here. Nothing in the working tree is changed."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app" / "auth" / "tokens.py"
TARGETS = {("verify_signed",), ("TokenValidator", "_check_claims")}


def checks(tree: ast.Module) -> list[tuple[str, ast.If]]:
    found: list[tuple[str, ast.If]] = []

    def walk(node: ast.AST, path: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = path
            if isinstance(child, ast.ClassDef | ast.FunctionDef):
                inner = (*path, child.name)
            if isinstance(child, ast.If) and isinstance(child.body[0], ast.Raise):  # noqa: SIM102
                if path in TARGETS:
                    found.append((f"{path[-1]}:{ast.unparse(child.test)}", child))
            walk(child, inner)

    walk(tree, ())
    return found


NAMES = [name for name, _ in checks(ast.parse(SOURCE.read_text()))]


def mutant(index: int) -> str:
    tree = ast.parse(SOURCE.read_text())
    checks(tree)[index][1].test = ast.Constant(value=False)
    return ast.unparse(tree)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    copy = tmp_path_factory.mktemp("mutants")
    for folder in ("app", "tests"):
        shutil.copytree(ROOT / folder, copy / folder, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", copy / "pyproject.toml")
    return copy


def run_token_tests(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
            "tests/auth/test_tokens.py",
        ],
        cwd=sandbox,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(sandbox)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )  # fmt: skip


def test_the_unmutated_copy_passes_and_the_checks_are_found(sandbox: Path) -> None:
    assert len(NAMES) >= 14, NAMES
    (sandbox / "app" / "auth" / "tokens.py").write_text(ast.unparse(ast.parse(SOURCE.read_text())))
    done = run_token_tests(sandbox)
    assert done.returncode == 0, done.stdout[-2000:]


@pytest.mark.parametrize("index", range(len(NAMES)), ids=NAMES)
def test_switching_off_a_check_is_noticed_by_the_token_tests(sandbox: Path, index: int) -> None:
    (sandbox / "app" / "auth" / "tokens.py").write_text(mutant(index))
    done = run_token_tests(sandbox)
    assert done.returncode == 1, f"no test noticed that '{NAMES[index]}' was removed"
