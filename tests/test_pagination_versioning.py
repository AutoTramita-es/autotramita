import uuid
from collections.abc import Mapping
from typing import Annotated, Any

import pytest
from app.api.app import create_app
from app.core.config import Settings
from app.core.errors import BadRequest, PreconditionFailed
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_CURSOR_LENGTH,
    MAX_LIMIT,
    CursorCodec,
    CursorPage,
    CursorValue,
    PageParams,
    page_params,
    paginate,
)
from app.core.versioning import check_version, ensure_updated, format_etag, if_match_version
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

KEY = b"synthetic-cursor-signing-key-0123456789"
TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()
FILTERS = {"status": "open", "q": "ž"}
SORT = ("-created_at", "id")


@pytest.fixture
def codec() -> CursorCodec:
    return CursorCodec(KEY)


def token(codec: CursorCodec, **overrides: Any) -> str:
    args: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "filters": FILTERS,
        "sort": SORT,
        "tie_breaker": "id",
        "position": {"created_at": "2026-11-24T10:00:00Z", "id": "7"},
    }
    return codec.encode(**{**args, **overrides})


def decode(codec: CursorCodec, value: str, **overrides: Any) -> Mapping[str, CursorValue]:
    args: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "filters": FILTERS,
        "sort": SORT,
        "tie_breaker": "id",
    }
    return codec.decode(value, **{**args, **overrides})


def reject(codec: CursorCodec, value: str, **overrides: Any) -> None:
    with pytest.raises(BadRequest) as err:
        decode(codec, value, **overrides)
    assert (err.value.status, err.value.code) == (400, "INVALID_CURSOR")


# --- cursor: round trip, integrity and binding ---------------------------------------------


def test_round_trip_is_opaque_and_signed(codec: CursorCodec) -> None:
    value = token(codec)
    assert decode(codec, value) == {"created_at": "2026-11-24T10:00:00Z", "id": "7"}
    assert value.count(".") == 1 and len(value) <= MAX_CURSOR_LENGTH
    assert "open" not in value and "2026" not in value  # base64: not readable as plain text


def test_tampered_cursors_are_rejected(codec: CursorCodec) -> None:
    value = token(codec)
    body, signature = value.split(".")
    flipped = ("A" if body[10] != "A" else "B").join([body[:10], body[11:]])
    for bad in (
        f"{flipped}.{signature}",  # payload changed
        f"{body}.{signature[:-2]}AA",  # signature changed
        body,  # no signature
        f"{body}.",  # empty signature
        f"{body}.{signature}.extra",
        f".{signature}",
        "",
        "!!!.???",
        "x" * (MAX_CURSOR_LENGTH + 1),
        "bm90LWpzb24.bm90LWpzb24",  # valid base64, wrong signature
    ):
        reject(codec, bad)


def test_cursor_signed_with_another_key_is_rejected(codec: CursorCodec) -> None:
    other = CursorCodec(b"another-synthetic-signing-key-abcdef0123456789")
    reject(codec, token(other))


def test_cursor_is_bound_to_tenant_filters_and_sort(codec: CursorCodec) -> None:
    value = token(codec)
    reject(codec, value, tenant_id=TENANT_B)  # cross-tenant replay
    reject(codec, value, tenant_id=None)
    reject(codec, value, filters={**FILTERS, "status": "closed"})
    reject(codec, value, filters={"status": "open"})
    reject(codec, value, sort=("created_at", "id"))  # direction changed
    reject(codec, value, sort=("status", "-created_at", "id"))  # other sort
    assert decode(codec, value, filters={"q": "ž", "status": "open"})  # key order is irrelevant


def test_position_must_match_the_sort_fields(codec: CursorCodec) -> None:
    for position in ({"id": "7"}, {"created_at": "x", "id": "7", "extra": 1}, {}):
        with pytest.raises(ValueError):
            token(codec, position=position)
    for sort in ((), ("id", "id"), ("-",), ("Bad Field",)):
        with pytest.raises(ValueError):
            token(codec, sort=sort, position={})


def test_sort_must_end_with_the_declared_unique_tie_breaker(codec: CursorCodec) -> None:
    with pytest.raises(ValueError):  # created_at is not unique and must not be the last key
        token(codec, sort=("id", "created_at"), tie_breaker="id")
    with pytest.raises(ValueError):
        token(codec, tie_breaker="created_at")
    value = token(codec)
    with pytest.raises(ValueError):  # a non-unique last key is refused when verifying, too
        decode(codec, value, tie_breaker="created_at")


def test_signing_key_is_required_and_strong(codec: CursorCodec) -> None:
    with pytest.raises(ValueError):
        CursorCodec(b"too-short")
    with pytest.raises(ValueError):
        CursorCodec(b"")
    with pytest.raises(TypeError):
        CursorCodec()  # type: ignore[call-arg]  # there is no default or built-in key
    with pytest.raises(RuntimeError, match="CURSOR_SIGNING_KEY"):
        CursorCodec.from_settings(Settings.model_construct(cursor_signing_key=None))
    configured = Settings.model_construct(cursor_signing_key=SecretStr(KEY.decode()))
    assert decode(
        CursorCodec.from_settings(configured), token(CursorCodec.from_settings(configured))
    )


# --- pagination: boundaries, determinism, no totals ----------------------------------------


def make_rows(count: int) -> list[dict[str, Any]]:
    # Many equal sort values on purpose; "id" is the unique tie-breaker.
    return [
        {"id": f"{i:04d}", "created_at": f"2026-11-24T10:{i // 7:02d}:00Z"} for i in range(count)
    ]


def walk(codec: CursorCodec, rows: list[dict[str, Any]], limit: int) -> list[str]:
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    sort = ("created_at", "id")
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(rows) + 2):
        start = 0
        if cursor:
            position = codec.decode(
                cursor, tenant_id=TENANT_A, filters=FILTERS, sort=sort, tie_breaker="id"
            )
            key = (position["created_at"], position["id"])
            start = next(
                (i for i, r in enumerate(ordered) if (r["created_at"], r["id"]) > key), len(ordered)
            )
        fetched = ordered[start : start + limit + 1]  # LIMIT limit + 1
        page = paginate(
            fetched,
            limit,
            codec=codec,
            tenant_id=TENANT_A,
            filters=FILTERS,
            sort=sort,
            tie_breaker="id",
            position_of=lambda r: {"created_at": r["created_at"], "id": r["id"]},
        )
        seen += [r["id"] for r in page.items]
        cursor = page.next_cursor
        if cursor is None:
            return seen
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("limit", [1, 3, 7, 25, 100])
def test_pages_are_complete_unique_and_deterministic(codec: CursorCodec, limit: int) -> None:
    rows = make_rows(57)
    expected = [r["id"] for r in sorted(rows, key=lambda r: (r["created_at"], r["id"]))]
    first = walk(codec, rows, limit)
    assert first == expected  # nothing skipped or repeated despite equal sort values
    assert walk(codec, rows, limit) == first  # same input, same pages


def test_exact_multiple_of_limit_ends_without_extra_page(codec: CursorCodec) -> None:
    assert walk(codec, make_rows(20), 10) == [r["id"] for r in make_rows(20)]
    assert walk(codec, [], 10) == []


def test_next_cursor_only_when_more_rows_exist_and_no_total(codec: CursorCodec) -> None:
    kwargs: dict[str, Any] = {
        "codec": codec,
        "tenant_id": TENANT_A,
        "filters": {},
        "sort": ("id",),
        "tie_breaker": "id",
        "position_of": lambda r: {"id": r["id"]},
    }
    rows = [{"id": str(i)} for i in range(6)]
    page = paginate(rows, 5, **kwargs)
    assert len(page.items) == 5 and page.next_cursor is not None
    assert codec.decode(
        page.next_cursor, tenant_id=TENANT_A, filters={}, sort=("id",), tie_breaker="id"
    ) == {"id": "4"}
    assert paginate(rows[:5], 5, **kwargs).next_cursor is None
    assert "total" not in CursorPage[int].model_fields
    assert "total" not in page.model_dump()


def make_app() -> FastAPI:
    app = create_app()

    @app.get("/p")
    def _p(params: Annotated[PageParams, Depends(page_params)]) -> PageParams:
        return params

    @app.put("/v")
    def _v(version: Annotated[int, Depends(if_match_version)]) -> dict[str, int]:
        return {"version": version}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(make_app())


def test_page_params_defaults_and_boundaries(client: TestClient) -> None:
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (25, 100)
    assert client.get("/p").json() == {"limit": 25, "cursor": None}
    for ok in ("1", "25", str(MAX_LIMIT)):
        assert client.get(f"/p?limit={ok}").status_code == 200
    for bad in ("0", str(MAX_LIMIT + 1), "-1", "abc", ""):
        r = client.get(f"/p?limit={bad}")
        assert r.status_code == 422, bad
        assert r.json()["code"] == "VALIDATION_ERROR"
    too_long = client.get("/p", params={"cursor": "x" * (MAX_CURSOR_LENGTH + 1)})
    assert too_long.status_code == 422


# --- optimistic locking: ETag / If-Match ---------------------------------------------------


def test_if_match_required_and_parsed(client: TestClient) -> None:
    missing = client.put("/v")
    assert (missing.status_code, missing.json()["code"]) == (428, "PRECONDITION_REQUIRED")
    ok = client.put("/v", headers={"If-Match": format_etag(3)})
    assert ok.json() == {"version": 3}
    for bad in ("3", 'W/"3"', "*", '"abc"', '"-1"', '""', '"1","2"'):
        r = client.put("/v", headers={"If-Match": bad})
        assert r.status_code == 400, bad
        assert r.json()["code"] == "INVALID_IF_MATCH"


def test_stale_version_is_412() -> None:
    check_version(2, 2)
    with pytest.raises(PreconditionFailed) as err:
        check_version(3, 2)
    assert (err.value.status, err.value.code) == (412, "VERSION_MISMATCH")
    ensure_updated(1)
    with pytest.raises(PreconditionFailed):
        ensure_updated(0)


def test_missing_key_never_yields_an_unsigned_cursor_or_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURSOR_SIGNING_KEY", raising=False)
    for key, value in {
        "ENVIRONMENT": "test",
        "POSTGRES_HOST": "h",
        "POSTGRES_DB": "d",
        "POSTGRES_USER": "u",
        "POSTGRES_PASSWORD": "p",
        "REDIS_URL": "redis://localhost/0",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    assert settings.cursor_signing_key is None  # no default secret
    with pytest.raises(RuntimeError, match="CURSOR_SIGNING_KEY"):
        CursorCodec.from_settings(settings)
    unsigned = "eyJ2IjoxfQ"  # a payload without signature, or with an empty one, is not accepted
    other = CursorCodec(KEY)
    for forged in (unsigned, f"{unsigned}.", f"{unsigned}.AAAA"):
        reject(other, forged)
