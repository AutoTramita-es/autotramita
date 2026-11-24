"""Structured JSON logging with redaction of secrets and personal identifiers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.request_context import get_request_id

REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(
    r"(authorization|cookie|password|passwd|secret|token|api[-_]?key|signing[-_]?key|idempotency[-_]?key|"
    r"nif|nie|vin|iban|card|cvv)",
    re.IGNORECASE,
)


def redact(value: Any) -> Any:
    """Return a copy with values of sensitive keys replaced, recursively."""
    if isinstance(value, dict):
        return {
            k: REDACTED if _SENSITIVE_KEY.search(str(k)) else redact(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload["fields"] = redact(extra)
        if record.exc_info:
            # Exception type only: messages and tracebacks may contain data or SQL parameters.
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
