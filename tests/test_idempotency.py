import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from app.core.db import RequestContext, session_scope
from app.core.errors import Conflict, UnprocessableEntity
from app.core.idempotency import (
    StoredResponse,
    begin,
    complete,
    idempotency_key,
    purge_expired,
    release,
    request_hash,
    scope_for,
)
from sqlalchemy import Engine, text
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
REPLAY_ID = "req-1234567890"
OTHER_ID = "req-other-12345"


@pytest.fixture
def engine(role_env: RoleEnv) -> Iterator[Engine]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    eng = role_env.engine("app")
    yield eng
    eng.dispose()


def ctx(tenant: uuid.UUID | None = TENANT_A) -> RequestContext:
    return RequestContext(tenant_id=tenant)


SCOPE = scope_for(uuid.UUID(int=1), "post", "/api/v1/things")


def test_first_request_owns_the_key_then_replays(engine: Engine) -> None:
    h = request_hash(b'{"a":1,"b":2}')
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    complete(engine, ctx(), scope=SCOPE, key=REPLAY_ID, status_code=201, body={"id": "x"})
    replay = begin(
        engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=request_hash(b'{"b":2,"a":1}')
    )
    assert replay == StoredResponse(status_code=201, body={"id": "x"})


def test_same_key_different_body_is_rejected(engine: Engine) -> None:
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=request_hash(b"{}")) is None
    with pytest.raises(UnprocessableEntity) as err:
        begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=request_hash(b'{"x":1}'))
    assert err.value.code == "idempotency_key_reuse"


def test_in_progress_returns_conflict_with_retry_after(engine: Engine) -> None:
    h = request_hash(b"{}")
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    with pytest.raises(Conflict) as err:
        begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h)
    assert err.value.code == "idempotency_in_progress"
    assert err.value.headers["Retry-After"] == "1"


def test_release_allows_retry_after_server_failure(engine: Engine) -> None:
    h = request_hash(b"{}")
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    release(engine, ctx(), scope=SCOPE, key=REPLAY_ID)
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None


def test_release_never_removes_a_completed_key(engine: Engine) -> None:
    h = request_hash(b"{}")
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    complete(engine, ctx(), scope=SCOPE, key=REPLAY_ID, status_code=200, body={"ok": True})
    release(engine, ctx(), scope=SCOPE, key=REPLAY_ID)
    assert begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is not None


def test_expired_key_is_reusable_and_purged(engine: Engine) -> None:
    h = request_hash(b"{}")
    assert (
        begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h, ttl=timedelta(seconds=-1))
        is None
    )
    assert (
        begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    )  # expired row replaced
    assert (
        begin(
            engine,
            ctx(),
            scope=SCOPE,
            key=OTHER_ID,
            body_hash=h,
            ttl=timedelta(seconds=-1),
        )
        is None
    )
    assert purge_expired(engine, ctx()) == 1


def test_keys_are_isolated_per_tenant_and_context(engine: Engine) -> None:
    h = request_hash(b"{}")
    assert begin(engine, ctx(TENANT_A), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    # Same key in another tenant, and with no tenant context, are independent claims.
    assert begin(engine, ctx(TENANT_B), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    assert begin(engine, ctx(None), scope=SCOPE, key=REPLAY_ID, body_hash=h) is None
    with session_scope(engine, ctx(TENANT_A)) as s:
        assert s.execute(text("SELECT count(*) FROM idempotency_keys")).scalar_one() == 1
    with session_scope(engine, ctx(TENANT_B)) as s:
        assert s.execute(text("SELECT count(*) FROM idempotency_keys")).scalar_one() == 1


def test_forged_tenant_row_is_rejected(engine: Engine) -> None:
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError), session_scope(engine, ctx(TENANT_A)) as s:
        s.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(tenant_id, scope, key, request_hash, state, expires_at) "
                "VALUES (:t, 's', 'k', 'h', 'in_progress', now())"
            ),
            {"t": TENANT_B},
        )


def test_concurrent_requests_exactly_one_wins(engine: Engine) -> None:
    h = request_hash(b"{}")
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            result = begin(engine, ctx(), scope=SCOPE, key=REPLAY_ID, body_hash=h)
            outcome = "owner" if result is None else "replay"
        except Conflict:
            outcome = "conflict"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("owner") == 1
    assert outcomes.count("conflict") == 7


def test_key_header_validation() -> None:
    from app.core.errors import BadRequest

    assert idempotency_key("abcdefgh-12345") == "abcdefgh-12345"
    for bad in (None, "short", "has space in it!", "x" * 129, "bad\nkey-123456"):
        with pytest.raises(BadRequest):
            idempotency_key(bad)
