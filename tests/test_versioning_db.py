"""Optimistic locking against real PostgreSQL: concurrent updates, one winner."""

import threading
import uuid

import pytest
from app.core.errors import PreconditionFailed
from app.core.versioning import ensure_updated
from sqlalchemy import CursorResult, Engine, text
from sqlalchemy.orm import Session


def update(engine: Engine, row_id: uuid.UUID, expected: int, name: str) -> None:
    with Session(engine) as session, session.begin():
        result = session.execute(
            text(
                "UPDATE versioned SET name = :n, version = version + 1 "
                "WHERE id = :i AND version = :v"
            ),
            {"n": name, "i": row_id, "v": expected},
        )
        assert isinstance(result, CursorResult)
        ensure_updated(result.rowcount)


@pytest.fixture
def row_id(scratch_engine: Engine) -> uuid.UUID:
    new_id = uuid.uuid4()
    with scratch_engine.begin() as c:
        c.execute(text("CREATE TABLE versioned (id uuid PRIMARY KEY, name text, version int)"))
        c.execute(text("INSERT INTO versioned VALUES (:i, 'start', 1)"), {"i": new_id})
    return new_id


def test_stale_update_is_rejected(scratch_engine: Engine, row_id: uuid.UUID) -> None:
    update(scratch_engine, row_id, 1, "first")
    with pytest.raises(PreconditionFailed) as err:
        update(scratch_engine, row_id, 1, "stale")
    assert err.value.status == 412
    with scratch_engine.connect() as c:
        assert c.execute(text("SELECT name, version FROM versioned")).one() == ("first", 2)


def test_concurrent_updates_have_exactly_one_winner(
    scratch_engine: Engine, row_id: uuid.UUID
) -> None:
    barrier = threading.Barrier(6)
    outcomes: list[str] = []
    lock = threading.Lock()

    def racer(n: int) -> None:
        barrier.wait()
        try:
            update(scratch_engine, row_id, 1, f"writer-{n}")
            outcome = "won"
        except PreconditionFailed:
            outcome = "stale"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=racer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert sorted(outcomes) == ["stale"] * 5 + ["won"]
    with scratch_engine.connect() as c:
        assert c.execute(text("SELECT version FROM versioned")).scalar_one() == 2
