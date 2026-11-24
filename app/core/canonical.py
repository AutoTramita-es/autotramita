"""Canonical JSON used for request fingerprints and cursor filter binding.

Format (owner-approved for F1-T06): UTF-8, object keys sorted, no insignificant whitespace,
non-ASCII characters kept as is, NaN/Infinity rejected, numbers exactly as parsed (``1`` and
``1.0`` differ). UUID, Decimal, date and datetime values are rendered as strings.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _default(value: object) -> str:
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Cannot canonicalize {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_default,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
