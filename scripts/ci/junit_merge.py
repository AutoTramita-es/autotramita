"""Joins the JUnit files of a test suite that ran as several pytest processes into the one file
the workflow's test count step reads. Standard library only."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

COUNTS = ("tests", "failures", "errors", "skipped")


def merge(sources: Sequence[Path], target: Path) -> dict[str, int]:
    """Writes every test case of ``sources`` into ``target`` and returns the summed counts.
    A missing or unreadable source raises: a part that left no result must never disappear."""
    totals = {key: 0 for key in COUNTS}
    seconds = 0.0
    suite = ET.Element("testsuite", name="pytest")
    for source in sources:
        root = ET.parse(source).getroot()  # noqa: S314  written by our own pytest run
        parts = [root] if root.tag == "testsuite" else root.findall("testsuite")
        if not parts:
            raise ValueError(f"{source} holds no test suite")
        for part in parts:
            for key in COUNTS:
                totals[key] += int(part.get(key, 0))
            seconds += float(part.get("time", 0))
            suite.extend(part)
    for key, value in totals.items():
        suite.set(key, str(value))
    # The sum of the parts; parts that ran at the same time took less wall-clock time.
    suite.set("time", f"{seconds:.3f}")
    root = ET.Element("testsuites")
    root.append(suite)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return totals


def case_ids(source: Path) -> list[str]:
    """``classname::name`` of every test case, in file order (repeats are kept)."""
    root = ET.parse(source).getroot()  # noqa: S314  written by our own pytest run
    return [f"{case.get('classname')}::{case.get('name')}" for case in root.iter("testcase")]
