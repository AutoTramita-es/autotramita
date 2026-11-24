"""Cursor pagination conventions (ADR-004): limit plus opaque cursor, no invented totals.

Encoding (owner-approved for F1-T06): ``base64url(payload) "." base64url(HMAC-SHA256)``.
The payload binds the cursor to the tenant, a hash of the filters, the sort and the position
(last row), and is signed with the secret ``CURSOR_SIGNING_KEY``; a changed cursor, another
tenant, other filters, another sort or another key is rejected as ``INVALID_CURSOR`` without
saying which. The cursor carries no authorization: row level security and endpoint
authorization apply to every page. Position values must be bound as query parameters, never
concatenated into SQL.

Sorting must be deterministic: callers name the ``tie_breaker`` (a unique key, usually the
id) and it must be the last sort field, otherwise rows with equal sort values could be skipped
or repeated across pages. The tie-breaker is part of the signed binding.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from app.core.canonical import canonical_json, sha256_hex
from app.core.errors import BadRequest
from fastapi import Query
from pydantic import BaseModel

if TYPE_CHECKING:
    from app.core.config import Settings

DEFAULT_LIMIT = 25
MIN_LIMIT = 1
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 1024
MIN_KEY_BYTES = 32

CursorValue = str | int | float | bool | None
_VERSION = 1
_DOMAIN = b"autotramita.cursor.v1\n"
_SORT_FIELD = re.compile(r"^-?[a-z][a-z0-9_]*$")


class PageParams(BaseModel):
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None


def page_params(
    limit: Annotated[int, Query(ge=MIN_LIMIT, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=cursor)


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _invalid() -> BadRequest:
    return BadRequest("The cursor is not valid.", code="INVALID_CURSOR")


def _sort_names(sort: Sequence[str]) -> list[str]:
    names = [s.removeprefix("-") for s in sort]
    if not sort or any(not _SORT_FIELD.fullmatch(s) for s in sort) or len(set(names)) != len(names):
        raise ValueError("sort must list unique field names, optionally prefixed with '-'")
    return names


class CursorCodec:
    """Creates and verifies signed cursors. Needs a secret key of at least 32 bytes."""

    def __init__(self, key: bytes) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(f"The cursor signing key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key

    @classmethod
    def from_settings(cls, settings: Settings) -> CursorCodec:
        secret = settings.cursor_signing_key
        if secret is None:
            raise RuntimeError("CURSOR_SIGNING_KEY is not configured in this environment.")
        return cls(secret.get_secret_value().encode("utf-8"))

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self._key, _DOMAIN + payload, hashlib.sha256).digest()

    @staticmethod
    def _binding(
        tenant_id: UUID | None,
        filters: Mapping[str, Any],
        sort: Sequence[str],
        tie_breaker: str,
    ) -> dict[str, Any]:
        if _sort_names(sort)[-1] != tie_breaker:
            raise ValueError("the last sort field must be the unique tie_breaker")
        return {
            "u": tie_breaker,
            "v": _VERSION,
            "t": str(tenant_id) if tenant_id else None,
            "f": sha256_hex(canonical_json(dict(filters))),
            "s": list(sort),
        }

    def encode(
        self,
        *,
        tenant_id: UUID | None,
        filters: Mapping[str, Any],
        sort: Sequence[str],
        tie_breaker: str,
        position: Mapping[str, CursorValue],
    ) -> str:
        names = _sort_names(sort)
        if set(position) != set(names):
            raise ValueError("position must contain exactly the sort fields")
        payload = canonical_json(
            {**self._binding(tenant_id, filters, sort, tie_breaker), "p": dict(position)}
        )
        token = f"{_b64(payload)}.{_b64(self._mac(payload))}"
        if len(token) > MAX_CURSOR_LENGTH:
            raise ValueError("cursor too long")
        return token

    def decode(
        self,
        token: str,
        *,
        tenant_id: UUID | None,
        filters: Mapping[str, Any],
        sort: Sequence[str],
        tie_breaker: str,
    ) -> dict[str, CursorValue]:
        """Return the position, or raise 400 ``INVALID_CURSOR`` for any problem."""
        if not token or len(token) > MAX_CURSOR_LENGTH:
            raise _invalid()
        try:
            body, signature = token.split(".")
            payload, mac = _unb64(body), _unb64(signature)
            if not hmac.compare_digest(mac, self._mac(payload)):
                raise _invalid()
            data: Any = json.loads(payload)
        except (ValueError, UnicodeError, binascii.Error):
            raise _invalid() from None
        expected = self._binding(tenant_id, filters, sort, tie_breaker)
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
            raise _invalid()
        position = data.get("p")
        names = _sort_names(sort)
        if not isinstance(position, dict) or set(position) != set(names):
            raise _invalid()
        if any(not isinstance(v, str | int | float | bool | None) for v in position.values()):
            raise _invalid()
        return position


def paginate[T](
    rows: Sequence[T],
    limit: int,
    *,
    codec: CursorCodec,
    tenant_id: UUID | None,
    filters: Mapping[str, Any],
    sort: Sequence[str],
    tie_breaker: str,
    position_of: Callable[[T], Mapping[str, CursorValue]],
) -> CursorPage[T]:
    """``rows`` must be fetched with ``LIMIT limit + 1``; the extra row proves a next page."""
    if len(rows) > limit:
        page = list(rows[:limit])
        cursor = codec.encode(
            tenant_id=tenant_id,
            filters=filters,
            sort=sort,
            tie_breaker=tie_breaker,
            position=position_of(page[-1]),
        )
        return CursorPage(items=page, next_cursor=cursor)
    return CursorPage(items=list(rows), next_cursor=None)
