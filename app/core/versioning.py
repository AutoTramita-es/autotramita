"""Optimistic concurrency via ETag / If-Match (ADR-004, AT-03 final design 7).

Resources expose an integer ``version``. Updates must send ``If-Match: "<version>"``.
"""

from __future__ import annotations

import re
from typing import Annotated

from app.core.errors import BadRequest, PreconditionFailed, PreconditionRequired
from fastapi import Header

_STRONG_ETAG = re.compile(r'^"(\d{1,18})"$')


def format_etag(version: int) -> str:
    return f'"{version}"'


def if_match_version(if_match: Annotated[str | None, Header()] = None) -> int:
    """Dependency: the version the client last saw. Missing header is 428."""
    if if_match is None:
        raise PreconditionRequired("Send If-Match with the current version of the resource.")
    match = _STRONG_ETAG.fullmatch(if_match.strip())
    if not match:
        raise BadRequest("If-Match must be a quoted version number.", code="INVALID_IF_MATCH")
    return int(match.group(1))


def check_version(current: int, expected: int) -> None:
    if current != expected:
        raise PreconditionFailed(
            "The resource changed; reload it and retry.", code="VERSION_MISMATCH"
        )


def ensure_updated(rowcount: int) -> None:
    """After ``UPDATE ... WHERE id = :id AND version = :expected``: zero rows means that
    another writer changed the row first (the caller has already shown the row is visible)."""
    if rowcount == 0:
        raise PreconditionFailed(
            "The resource changed; reload it and retry.", code="VERSION_MISMATCH"
        )
