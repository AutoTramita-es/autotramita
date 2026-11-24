"""Per-request correlation id (contextvar) shared by logging and error responses."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id(incoming: str | None) -> str:
    """Accept a well-formed incoming id, otherwise generate one (prevents log injection)."""
    if incoming and _SAFE.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()
