"""Idempotency (O03) on disposable fixtures: replay, conflicts, concurrency, atomicity, scope,
expiration and re-authorization. Unit tests need no database; the rest needs PostgreSQL 16."""

import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Annotated

import pytest
from app.api.app import create_app
from app.core.db import RequestContext, session_scope
from app.core.errors import BadRequest, Conflict, Forbidden, Unauthenticated
from app.core.idempotency import (
    DEFAULT_TTL,
    IdempotentResult,
    StoredResponse,
    execute_idempotent,
    fingerprint,
    idempotency_key,
    purge_expired,
)
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from tests.conftest import RoleEnv
from tests.idempotency_fixture import build_idempotency_fixture

TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()
ACTOR_1, ACTOR_2 = uuid.uuid4(), uuid.uuid4()
# A valid synthetic UUID v4, built from an integer so no secret-like literal is committed.
IDEMPOTENCY_TOKEN_A = str(uuid.UUID(int=0x7B1F0C9E3F5A4D6E9A2B0C1D2E3F4A5B, version=4))
BODY = b'{"name":"widget","qty":2}'


# --- unit: key header and fingerprint ------------------------------------------------------


def test_key_header_validation() -> None:
    assert idempotency_key(IDEMPOTENCY_TOKEN_A) == IDEMPOTENCY_TOKEN_A
    assert idempotency_key("x" * 128) == "x" * 128
    with pytest.raises(BadRequest) as missing:
        idempotency_key(None)
    assert (missing.value.status, missing.value.code) == (400, "IDEMPOTENCY_KEY_REQUIRED")
    for bad in ("short", "has space in it!", "x" * 129, "bad\nkey-123456", ""):
        with pytest.raises(BadRequest) as err:
            idempotency_key(bad)
        assert err.value.code == "IDEMPOTENCY_KEY_INVALID"


def test_fingerprint_is_canonical_and_binds_method_and_operation() -> None:
    base = fingerprint("post", "things.create", b'{"a":1,"b":[1,2],"c":"\xc5\xbe"}')
    assert base == fingerprint("POST", "things.create", b'{ "c": "\xc5\xbe",\n "b":[1,2], "a":1 }')
    assert len(base) == 64
    assert base != fingerprint("PUT", "things.create", b'{"a":1,"b":[1,2],"c":"\xc5\xbe"}')
    assert base != fingerprint("POST", "things.update", b'{"a":1,"b":[1,2],"c":"\xc5\xbe"}')
    assert base != fingerprint("POST", "things.create", b'{"a":2,"b":[1,2],"c":"\xc5\xbe"}')
    assert fingerprint("POST", "o", b"1") != fingerprint("POST", "o", b"1.0")  # numbers as parsed
    assert fingerprint("POST", "o", b"[1,2]") != fingerprint("POST", "o", b"[2,1]")


def test_non_json_bodies_are_hashed_raw_and_do_not_collide_with_json() -> None:
    assert fingerprint("POST", "o", b"not json") == fingerprint("POST", "o", b"not json")
    assert fingerprint("POST", "o", b"not json") != fingerprint("POST", "o", b"not  json")
    assert fingerprint("POST", "o", b'"x"') != fingerprint("POST", "o", b"x")


def test_retention_is_24_hours() -> None:
    assert timedelta(hours=24) == DEFAULT_TTL


def test_idempotency_table_exists_only_as_a_test_fixture() -> None:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)
    # F2 chain: 0002 bootstrap, 0003 audit, 0004 users, 0005-0006 sessions
    assert script.get_heads() == ["0006"]
    for path in (root / "migrations").rglob("*.py"):
        assert "idempotency" not in path.read_text().lower(), path
    assert "CREATE TABLE idempotency_keys" in (root / "tests/idempotency_fixture.py").read_text()


# --- integration: disposable PostgreSQL 16 -------------------------------------------------


@pytest.fixture
def engine(role_env: RoleEnv) -> Iterator[Engine]:
    eng = build_idempotency_fixture(role_env)
    yield eng
    eng.dispose()


def ctx(tenant: uuid.UUID = TENANT_A, actor: uuid.UUID | None = ACTOR_1) -> RequestContext:
    return RequestContext(tenant_id=tenant, user_id=actor)


def things(engine: Engine, tenant: uuid.UUID = TENANT_A) -> int:
    with session_scope(engine, ctx(tenant)) as s:
        return int(s.execute(text("SELECT count(*) FROM idem_things")).scalar_one())


def key_rows(engine: Engine, tenant: uuid.UUID = TENANT_A) -> int:
    with session_scope(engine, ctx(tenant)) as s:
        return int(s.execute(text("SELECT count(*) FROM idempotency_keys")).scalar_one())


class Counter:
    """Handler that creates one business row and counts executions."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, session: Session) -> StoredResponse:
        self.calls += 1
        new_id = session.execute(
            text("INSERT INTO idem_things (name) VALUES ('w') RETURNING id")
        ).scalar_one()
        return StoredResponse(201, {"id": str(new_id)})


def run(
    engine: Engine,
    handler: Callable[[Session], StoredResponse],
    *,
    context: RequestContext | None = None,
    operation: str = "things.create",
    method: str = "POST",
    key: str = IDEMPOTENCY_TOKEN_A,
    body: bytes = BODY,
    authorize: Callable[[], None] = lambda: None,
    ttl: timedelta = timedelta(hours=24),
) -> IdempotentResult:
    return execute_idempotent(
        engine,
        context or ctx(),
        method=method,
        operation=operation,
        key=key,
        body=body,
        authorize=authorize,
        handler=handler,
        ttl=ttl,
    )


def test_first_request_executes_then_identical_request_replays(engine: Engine) -> None:
    handler = Counter()
    first = run(engine, handler)
    reordered = b'{ "qty": 2, "name": "widget" }'  # same JSON, different layout
    second = run(engine, handler, body=reordered)
    assert (first.replayed, second.replayed) == (False, True)
    assert second.response == first.response
    assert first.response.status_code == 201
    assert handler.calls == 1
    assert (things(engine), key_rows(engine)) == (1, 1)


def test_same_key_with_different_payload_is_409_and_does_not_execute(engine: Engine) -> None:
    handler = Counter()
    run(engine, handler)
    with pytest.raises(Conflict) as err:
        run(engine, handler, body=b'{"name":"other"}')
    assert (err.value.status, err.value.code) == (409, "IDEMPOTENCY_KEY_REUSE")
    assert handler.calls == 1
    assert things(engine) == 1


def test_concurrent_in_flight_request_gets_409_then_replay_after_commit(engine: Engine) -> None:
    started, release = threading.Event(), threading.Event()
    results: list[object] = []

    def slow(session: Session) -> StoredResponse:
        session.execute(text("INSERT INTO idem_things (name) VALUES ('slow')"))
        started.set()
        assert release.wait(10)
        return StoredResponse(201, {"ok": True})

    first = threading.Thread(target=lambda: results.append(run(engine, slow)))
    first.start()
    assert started.wait(10)
    fast = Counter()
    with pytest.raises(Conflict) as err:
        run(engine, fast)
    assert (err.value.status, err.value.code) == (409, "IDEMPOTENCY_IN_PROGRESS")
    assert err.value.headers["Retry-After"] == "1"
    release.set()
    first.join(10)
    assert len(results) == 1
    replay = run(engine, fast)
    assert replay.replayed and replay.response.body == {"ok": True}
    assert fast.calls == 0
    assert things(engine) == 1


def test_many_concurrent_identical_requests_execute_exactly_once(engine: Engine) -> None:
    handler = Counter()
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            outcome = "replay" if run(engine, handler).replayed else "executed"
        except Conflict:
            outcome = "conflict"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert outcomes.count("executed") == 1
    assert set(outcomes) <= {"executed", "replay", "conflict"}
    assert handler.calls == 1
    assert (things(engine), key_rows(engine)) == (1, 1)


def test_handler_failure_rolls_back_business_change_and_frees_the_key(engine: Engine) -> None:
    def failing(session: Session) -> StoredResponse:
        session.execute(text("INSERT INTO idem_things (name) VALUES ('half')"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run(engine, failing)
    assert (things(engine), key_rows(engine)) == (0, 0)
    retry = Counter()
    assert run(engine, retry).replayed is False  # the client can simply retry
    assert (things(engine), key_rows(engine)) == (1, 1)


def test_business_change_and_stored_response_are_atomic(engine: Engine) -> None:
    def unstorable(session: Session) -> StoredResponse:
        session.execute(text("INSERT INTO idem_things (name) VALUES ('orphan')"))
        return StoredResponse(201, {"bad": {1, 2}})  # cannot be stored as JSON

    with pytest.raises(TypeError):
        run(engine, unstorable)
    assert (things(engine), key_rows(engine)) == (0, 0)  # no business row without its record


def test_stored_key_is_kept_for_24_hours(engine: Engine) -> None:
    run(engine, Counter())
    with session_scope(engine, ctx()) as s:
        remaining = s.execute(
            text("SELECT expires_at - created_at FROM idempotency_keys")
        ).scalar_one()
    assert remaining == timedelta(hours=24)


def test_expired_key_is_forgotten_and_purgeable(engine: Engine) -> None:
    handler = Counter()
    run(engine, handler, ttl=timedelta(seconds=-1))  # stored, but already expired
    again = run(engine, handler)
    assert again.replayed is False
    assert handler.calls == 2
    assert key_rows(engine) == 1  # the expired row was replaced
    assert run(engine, handler).replayed is True
    run(engine, handler, key="expired-other-key-1", ttl=timedelta(seconds=-1))
    assert purge_expired(engine, ctx()) == 1


def test_scope_is_actor_tenant_operation_and_key(engine: Engine) -> None:
    handler = Counter()
    variants = [
        {},
        {"context": ctx(actor=ACTOR_2)},
        {"context": ctx(TENANT_B)},
        {"operation": "things.other"},
        {"key": "another-key-123456"},
    ]
    for variant in variants:
        assert run(engine, handler, **variant).replayed is False  # type: ignore[arg-type]
    assert handler.calls == len(variants)
    for variant in variants:
        assert run(engine, handler, **variant).replayed is True  # type: ignore[arg-type]
    assert handler.calls == len(variants)
    assert (things(engine, TENANT_A), things(engine, TENANT_B)) == (4, 1)
    assert (key_rows(engine, TENANT_A), key_rows(engine, TENANT_B)) == (4, 1)  # RLS view


def test_replay_is_reauthorized_on_every_request(engine: Engine) -> None:
    handler = Counter()
    calls: list[int] = []

    def allowed() -> None:
        calls.append(1)

    def revoked() -> None:
        raise Forbidden("Access was revoked.")

    run(engine, handler, authorize=allowed)
    assert run(engine, handler, authorize=allowed).replayed is True
    assert len(calls) == 2  # authorization also ran for the replay
    with pytest.raises(Forbidden):
        run(engine, handler, authorize=revoked)  # a stored result is not served any more
    assert handler.calls == 1


def test_actor_and_tenant_are_required(engine: Engine) -> None:
    handler = Counter()
    with pytest.raises(Unauthenticated):
        run(engine, handler, context=RequestContext(tenant_id=TENANT_A))
    with pytest.raises(Forbidden) as err:
        run(engine, handler, context=RequestContext(user_id=ACTOR_1))
    assert err.value.code == "TENANT_CONTEXT_REQUIRED"
    assert handler.calls == 0


def test_forged_tenant_row_is_rejected_by_rls(engine: Engine) -> None:
    with pytest.raises(ProgrammingError), session_scope(engine, ctx(TENANT_A)) as s:
        s.execute(
            text(
                "INSERT INTO idempotency_keys (tenant_id, actor_id, operation, key, fingerprint, "
                "status_code, expires_at) VALUES (:t, :a, 'o', 'k', 'f', 200, now())"
            ),
            {"t": TENANT_B, "a": ACTOR_1},
        )


# --- HTTP: a test-only route (never part of the application) -------------------------------


def make_client(engine: Engine, counter: Counter) -> TestClient:
    app = create_app(db_engine=engine)

    @app.post("/t/things", status_code=201)
    async def create(request: Request, key: Annotated[str, Depends(idempotency_key)]) -> object:
        headers = request.headers
        context = RequestContext(
            tenant_id=uuid.UUID(headers["x-test-tenant"]),
            user_id=uuid.UUID(headers["x-test-user"]) if "x-test-user" in headers else None,
        )

        def authorize() -> None:
            if "x-test-deny" in headers:
                raise Forbidden("Not allowed.")

        result = execute_idempotent(
            engine,
            context,
            method="POST",
            operation="things.create",
            key=key,
            body=await request.body(),
            authorize=authorize,
            handler=counter,
        )
        return JSONResponse(result.response.body, status_code=result.response.status_code)

    return TestClient(app, raise_server_exceptions=False)


def test_http_contract(engine: Engine) -> None:
    counter = Counter()
    client = make_client(engine, counter)
    who = {"x-test-tenant": str(TENANT_A), "x-test-user": str(ACTOR_1)}
    body = {"name": "widget"}

    missing = client.post("/t/things", json=body, headers=who)
    assert (missing.status_code, missing.json()["code"]) == (400, "IDEMPOTENCY_KEY_REQUIRED")
    assert missing.headers["content-type"].startswith("application/problem+json")
    invalid = client.post("/t/things", json=body, headers={**who, "Idempotency-Key": "bad key"})
    assert invalid.json()["code"] == "IDEMPOTENCY_KEY_INVALID"

    headers = {**who, "Idempotency-Key": IDEMPOTENCY_TOKEN_A}
    first = client.post("/t/things", json=body, headers=headers)
    replay = client.post("/t/things", json=body, headers=headers)
    assert (first.status_code, replay.status_code) == (201, 201)
    assert replay.json() == first.json()
    assert counter.calls == 1

    clash = client.post("/t/things", json={"name": "different"}, headers=headers)
    assert (clash.status_code, clash.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSE")
    assert clash.json()["type"].endswith("/idempotency-key-reuse")

    revoked = client.post("/t/things", json=body, headers={**headers, "x-test-deny": "1"})
    assert (revoked.status_code, revoked.json()["code"]) == (403, "FORBIDDEN")

    anonymous = client.post(
        "/t/things",
        json=body,
        headers={"x-test-tenant": str(TENANT_A), "Idempotency-Key": IDEMPOTENCY_TOKEN_A},
    )
    assert (anonymous.status_code, anonymous.json()["code"]) == (401, "UNAUTHENTICATED")
    assert counter.calls == 1
