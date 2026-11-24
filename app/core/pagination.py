"""Cursor pagination conventions (ADR-004): limit plus opaque cursor, no invented totals.

A cursor is opaque to clients but NOT trusted: it is decoded strictly and its values must
always be bound as query parameters, never concatenated. It carries no authorization; row
level security and endpoint authorization apply to every page.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from typing import Annotated, Any

from app.core.errors import BadRequest
from fastapi import Query
from pydantic import BaseModel

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 512

CursorValue = str | int | float | bool | None


class PageParams(BaseModel):
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=cursor)


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(values: dict[str, CursorValue]) -> str:
    raw = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    if len(token) > MAX_CURSOR_LENGTH:
        raise ValueError("cursor too long")
    return token


def decode_cursor(token: str) -> dict[str, CursorValue]:
    """Strictly decode a cursor; any problem is a 400 ``invalid_cursor``."""
    invalid = BadRequest("The cursor is not valid.", code="invalid_cursor")
    if not token or len(token) > MAX_CURSOR_LENGTH:
        raise invalid
    try:
        padded = token + "=" * (-len(token) % 4)
        data: Any = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeError):
        raise invalid from None
    if not isinstance(data, dict):
        raise invalid
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str | int | float | bool | None):
            raise invalid
    return data


def paginate[T](
    rows: Sequence[T], limit: int, make_cursor: Callable[[T], dict[str, CursorValue]]
) -> CursorPage[T]:
    """``rows`` must be fetched with ``LIMIT limit + 1``; the extra row proves a next page."""
    if len(rows) > limit:
        page = list(rows[:limit])
        return CursorPage(items=page, next_cursor=encode_cursor(make_cursor(page[-1])))
    return CursorPage(items=list(rows), next_cursor=None)
