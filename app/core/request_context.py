"""Per-request correlation id (contextvar) shared by logging and error responses."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id(incoming: str | None) -> str:
    """Request ids are UUIDs: accept a well-formed incoming one, otherwise generate a UUID v4
    (anything else could inject data into logs)."""
    if incoming and len(incoming) <= 36:
        try:
            return str(uuid.UUID(incoming))
        except ValueError:
            pass
    return str(uuid.uuid4())


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()
