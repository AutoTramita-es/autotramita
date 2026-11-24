"""JSON conventions for API models (ADR-004): snake_case, UUID, ISO 8601 UTC, ISO 4217,
Decimal as JSON string. Business schemas derive from ``ApiModel`` and use these types."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

_SNAKE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


class ApiModel(BaseModel):
    """Base for request and response models: unknown fields rejected, snake_case enforced."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for name in cls.model_fields:
            if not _SNAKE.fullmatch(name):
                raise TypeError(f"{cls.__name__}.{name} must be snake_case")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    AfterValidator(_to_utc),
    PlainSerializer(_iso_utc, return_type=str, when_used="json"),
]
"""Timezone-aware timestamp, normalized to UTC, serialized as ISO 8601 with ``Z``."""

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO 4217 alphabetic code (format only; no list of valid codes is enforced in F1)."""


def _decimal_in(value: Any) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("amount must be a decimal string, not a binary number")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str) and _DECIMAL.fullmatch(value):
        try:
            parsed = Decimal(value)
        except InvalidOperation:  # pragma: no cover - regex already guarantees a valid literal
            raise ValueError("amount must be a decimal string") from None
    else:
        raise ValueError("amount must be a decimal string")
    if not parsed.is_finite():
        raise ValueError("amount must be finite")
    return parsed


DecimalString = Annotated[
    Decimal,
    BeforeValidator(_decimal_in),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["1234.50"]}),
]
"""Exact decimal, exchanged as a JSON string (never as a float)."""
