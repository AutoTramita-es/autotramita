"""JSON conventions: snake_case, UUID, ISO 8601 UTC, ISO 4217, Decimal as string."""

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from app.core.types import ApiModel, CurrencyCode, DecimalString, UtcDatetime
from pydantic import ValidationError


class Invoice(ApiModel):
    invoice_id: uuid.UUID
    issued_at: UtcDatetime
    currency: CurrencyCode
    total: DecimalString


def make(**overrides: object) -> Invoice:
    data: dict[str, object] = {
        "invoice_id": uuid.UUID(int=5),
        "issued_at": "2026-11-24T10:00:00+01:00",
        "currency": "EUR",
        "total": "1234.50",
    }
    return Invoice.model_validate({**data, **overrides})


def test_json_output_follows_the_conventions() -> None:
    out = json.loads(make().model_dump_json())
    assert out == {
        "invoice_id": "00000000-0000-0000-0000-000000000005",
        "issued_at": "2026-11-24T09:00:00Z",  # normalized to UTC
        "currency": "EUR",
        "total": "1234.50",  # a string, never a float
    }


def test_timestamps_require_a_timezone_and_are_normalized() -> None:
    assert make(issued_at="2026-11-24T10:00:00Z").issued_at == datetime(
        2026, 11, 24, 10, tzinfo=UTC
    )
    zone = timezone(timedelta(hours=-5))
    assert make(
        issued_at=datetime(2026, 1, 1, 0, 0, tzinfo=zone)
    ).issued_at.utcoffset() == timedelta(0)
    for naive in ("2026-11-24T10:00:00", datetime(2026, 11, 24, 10), "not a date"):
        with pytest.raises(ValidationError):
            make(issued_at=naive)


@pytest.mark.parametrize("value", ["EUR", "USD", "GBP"])
def test_valid_currency_codes(value: str) -> None:
    assert make(currency=value).currency == value


@pytest.mark.parametrize("value", ["eur", "EU", "EURO", "E1R", "", 978])
def test_invalid_currency_codes(value: object) -> None:
    with pytest.raises(ValidationError):
        make(currency=value)


def test_decimals_are_exact_strings() -> None:
    assert make(total="0.10").total == Decimal("0.10")
    assert make(total=3).total == Decimal(3)
    assert make(total=Decimal("1.1")).total == Decimal("1.1")
    for bad in (1.1, True, "1e3", "NaN", "Infinity", "1,5", " 1", "", None, "1.", ".5"):
        with pytest.raises(ValidationError):
            make(total=bad)
    assert Invoice.model_json_schema()["properties"]["total"]["type"] == "string"


def test_unknown_fields_are_rejected_and_names_must_be_snake_case() -> None:
    with pytest.raises(ValidationError):
        make(unexpected="x")
    with pytest.raises(TypeError):

        class Bad(ApiModel):
            camelCase: int
