from typing import Annotated

import pytest
from app.api.app import create_app
from app.core.errors import BadRequest, PreconditionFailed
from app.core.pagination import (
    MAX_LIMIT,
    CursorPage,
    PageParams,
    decode_cursor,
    encode_cursor,
    page_params,
    paginate,
)
from app.core.versioning import check_version, format_etag, if_match_version
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


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


def test_cursor_round_trip() -> None:
    token = encode_cursor({"created_at": "2026-11-24T10:00:00Z", "id": 7, "ok": True, "n": None})
    assert decode_cursor(token) == {
        "created_at": "2026-11-24T10:00:00Z",
        "id": 7,
        "ok": True,
        "n": None,
    }


@pytest.mark.parametrize(
    "token",
    ["", "!!!", "bm90LWpzb24", "W10", "eyJhIjp7fX0", "x" * 600],  # junk, non-json, list, nested
)
def test_bad_cursors_are_rejected(token: str) -> None:
    with pytest.raises(BadRequest) as err:
        decode_cursor(token)
    assert err.value.code == "invalid_cursor"


def test_paginate_uses_extra_row_and_no_total() -> None:
    rows = [{"id": i} for i in range(6)]
    page = paginate(rows, 5, lambda r: {"id": r["id"]})
    assert len(page.items) == 5
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor) == {"id": 4}
    last = paginate(rows[:5], 5, lambda r: {"id": r["id"]})
    assert last.next_cursor is None
    assert "total" not in CursorPage[int].model_fields


def test_page_params_defaults_and_limits(client: TestClient) -> None:
    assert client.get("/p").json() == {"limit": 25, "cursor": None}
    assert client.get(f"/p?limit={MAX_LIMIT}").status_code == 200
    for bad in ("0", str(MAX_LIMIT + 1), "-1", "abc"):
        r = client.get(f"/p?limit={bad}")
        assert r.status_code == 422
        assert r.json()["code"] == "validation_error"


def test_if_match_required_and_parsed(client: TestClient) -> None:
    assert client.put("/v").status_code == 428
    assert client.put("/v").json()["code"] == "precondition_required"
    ok = client.put("/v", headers={"If-Match": format_etag(3)})
    assert ok.json() == {"version": 3}
    for bad in ("3", 'W/"3"', "*", '"abc"', '"-1"'):
        r = client.put("/v", headers={"If-Match": bad})
        assert r.status_code == 400, bad
        assert r.json()["code"] == "invalid_if_match"


def test_version_mismatch_is_412() -> None:
    check_version(2, 2)
    with pytest.raises(PreconditionFailed) as err:
        check_version(3, 2)
    assert err.value.code == "version_mismatch"
