"""Pytest plugin of the Local CI runner. It is loaded with ``PYTEST_PLUGINS`` so that the
commands of ci.yml stay unchanged, and it does two things in the outermost pytest process only:

* gives every invocation a JUnit XML file (unless the command already names one) and records it;
* on request (``ATCI_INFRA=only|exclude``) keeps only the tests that do, or do not, depend on
  the PostgreSQL/Redis fixtures. This splits the suite for the fast and integration profiles;
  deselected tests are reported as deselected, never as skipped.

The outer process removes the variables that load the plugin from its environment once they
have been read, so nested pytest processes started by tests (the token mutation test) are
exactly as untouched as on GitHub.

With pytest-xdist the outer process is a controller that runs no test and starts workers: it
leaves the variables for them. A worker applies the split, removes the variables before its
first test, records nothing itself and reports its deselected count to the controller, which
writes the one record of the run.
"""

import json
import os
import uuid
from typing import Any

import pytest

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
INFRA_FIXTURES = frozenset({"pg_admin_url", "redis_url"})


def _forget_plugin() -> None:
    os.environ.pop("PYTEST_PLUGINS", None)
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p != PLUGIN_DIR]
    if any(paths):
        os.environ["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        os.environ.pop("PYTHONPATH", None)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: Any) -> None:
    config._atci_deselected = 0
    worker = hasattr(config, "workerinput")
    controller = not worker and bool(getattr(config.option, "numprocesses", None))
    read = os.environ.get if controller else os.environ.pop
    config._atci_infra = read("ATCI_INFRA", None)
    directory = read("ATCI_JUNIT_DIR", None)
    config._atci_junit = None if worker else directory
    if not controller:
        _forget_plugin()
    if directory and not worker and not config.option.xmlpath:
        config.option.xmlpath = os.path.join(directory, f"pytest-{uuid.uuid4().hex[:12]}.xml")


def pytest_sessionfinish(session: Any) -> None:
    output = getattr(session.config, "workeroutput", None)
    if output is not None:
        output["atci_deselected"] = session.config._atci_deselected


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any) -> None:
    # Every worker collects the same tests, so each reports the same count.
    count = getattr(node, "workeroutput", {}).get("atci_deselected")
    if count is not None:
        node.config._atci_deselected = count


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    mode = config._atci_infra
    if not mode:
        return
    if mode not in ("only", "exclude"):
        raise pytest.UsageError(f"ATCI_INFRA must be 'only' or 'exclude', not {mode!r}")
    keep: list[Any] = []
    drop: list[Any] = []
    for item in items:
        needs_infra = bool(INFRA_FIXTURES & set(getattr(item, "fixturenames", ())))
        (keep if needs_infra == (mode == "only") else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def pytest_deselected(items: list[Any]) -> None:
    if items:
        items[0].config._atci_deselected += len(items)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: Any) -> None:
    directory = config._atci_junit
    if not directory or not config.option.xmlpath:
        return
    record = {
        "xml": os.path.abspath(config.option.xmlpath),
        "deselected": config._atci_deselected,
    }
    with open(os.path.join(directory, "manifest.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
