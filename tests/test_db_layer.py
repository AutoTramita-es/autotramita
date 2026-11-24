"""F1-T03 database layer: role-specific engines, validated context, transaction boundaries.

Unit tests need no database. Integration tests use the disposable PostgreSQL 16 of
``role_env`` (skipped locally without TEST_PG_ADMIN_URL, mandatory in CI).
"""

import uuid
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import (
    RequestContext,
    create_db_engine,
    create_session_factory,
    session_scope,
)
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import Session, sessionmaker
from tests.conftest import RoleEnv

ROLE_USERS = {
    "owner": "syn_owner",
    "app": "syn_app",
    "worker": "syn_worker",
    "platform": "syn_platform",
}


def synthetic(monkeypatch: pytest.MonkeyPatch, *, all_roles: bool) -> Settings:
    env = {
        "ENVIRONMENT": "test",
        "POSTGRES_HOST": "db.invalid",
        "POSTGRES_DB": "syn_db",
        "POSTGRES_USER": ROLE_USERS["app"],
        "POSTGRES_PASSWORD": "pw-app-1",
        "REDIS_URL": "redis://localhost:6379/0",
    }
    if all_roles:
        for role in ("owner", "worker", "platform"):
            env[f"APP_DB_{role.upper()}_USER"] = ROLE_USERS[role]
            env[f"APP_DB_{role.upper()}_PASSWORD"] = f"pw-{role}-1"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for role in ("OWNER", "WORKER", "PLATFORM"):
        if not all_roles:
            monkeypatch.delenv(f"APP_DB_{role}_USER", raising=False)
            monkeypatch.delenv(f"APP_DB_{role}_PASSWORD", raising=False)
    return Settings()


# --- unit: role selection (no connection is opened) ----------------------------------------


@pytest.mark.parametrize("role", ["app", "worker", "owner", "platform"])
def test_engine_uses_exactly_the_requested_role(monkeypatch: pytest.MonkeyPatch, role: Any) -> None:
    engine = create_db_engine(synthetic(monkeypatch, all_roles=True), role=role)
    assert engine.url.username == ROLE_USERS[role]
    assert engine.url.drivername == "postgresql+psycopg"
    engine.dispose()


def test_default_and_legacy_runtime_role_is_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = synthetic(monkeypatch, all_roles=True)
    for engine in (create_db_engine(settings), create_db_engine(settings, role="runtime")):
        assert engine.url.username == ROLE_USERS["app"]
        engine.dispose()


@pytest.mark.parametrize("role", ["owner", "worker", "platform"])
def test_runtime_settings_cannot_build_other_roles(
    monkeypatch: pytest.MonkeyPatch, role: Any
) -> None:
    settings = synthetic(monkeypatch, all_roles=False)
    create_db_engine(settings).dispose()  # app works with only its own secrets
    with pytest.raises(RuntimeError, match="not configured"):
        create_db_engine(settings, role=role)


def test_engine_repr_hides_password(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_db_engine(synthetic(monkeypatch, all_roles=True), role="worker")
    assert "pw-worker-1" not in repr(engine) + str(engine.url)
    engine.dispose()


def test_creating_an_engine_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    # Host is unresolvable (".invalid"); construction must still succeed without network.
    create_db_engine(synthetic(monkeypatch, all_roles=True), role="platform").dispose()


# --- unit: validated context ---------------------------------------------------------------


def test_context_accepts_uuids_and_freezes_branches() -> None:
    b = uuid.uuid4()
    ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), branch_ids=[b])
    assert ctx.branch_ids == (b,)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": "11111111-1111-1111-1111-111111111111"},
        {"user_id": 5},
        {"tenant_id": "x'); DROP TABLE t;--"},
        {"branch_ids": ["11111111-1111-1111-1111-111111111111"]},
        {"branch_ids": "abc"},
        {"branch_ids": [None]},
    ],
)
def test_context_rejects_raw_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        RequestContext(**kwargs)


# --- integration: transaction boundaries (disposable PostgreSQL 16) ------------------------


def settings_for(env: RoleEnv, monkeypatch: pytest.MonkeyPatch) -> Settings:
    admin = make_url(env.admin_url)
    values = {
        "ENVIRONMENT": "test",
        "POSTGRES_HOST": admin.host or "127.0.0.1",
        "POSTGRES_PORT": str(admin.port or 5432),
        "POSTGRES_DB": env.database,
        "POSTGRES_USER": env.names.app,
        "POSTGRES_PASSWORD": env.passwords["app"],
        "REDIS_URL": "redis://localhost:6379/0",
    }
    for role in ("owner", "worker", "platform"):
        values[f"APP_DB_{role.upper()}_USER"] = getattr(env.names, role)
        values[f"APP_DB_{role.upper()}_PASSWORD"] = env.passwords[role]
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings()


def scalar(session: Session, sql: str, **params: object) -> Any:
    return session.execute(text(sql), params).scalar()


@pytest.mark.parametrize("role", ["owner", "app", "worker", "platform"])
def test_each_role_connects_as_itself(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch, role: Any
) -> None:
    engine = create_db_engine(settings_for(role_env, monkeypatch), role=role)
    with session_scope(engine) as s:
        assert scalar(s, "SELECT current_user") == getattr(role_env.names, role)
    engine.dispose()


def test_context_and_query_share_one_connection_and_transaction(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_db_engine(settings_for(role_env, monkeypatch))
    tenant = uuid.uuid4()
    with session_scope(engine, RequestContext(tenant_id=tenant)) as s:
        row = s.execute(
            text("SELECT pg_backend_pid(), txid_current(), current_setting('app.tenant_id', true)")
        ).one()
        same = s.execute(text("SELECT pg_backend_pid(), txid_current()")).one()
        assert (row[0], row[1]) == (same[0], same[1])
        assert row[2] == str(tenant)
    engine.dispose()


def test_forced_connection_reuse_does_not_carry_context_after_commit_or_rollback(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pool_size=1 without overflow forces every scope onto the same physical connection.
    base = create_db_engine(settings_for(role_env, monkeypatch))
    engine = create_engine(base.url, pool_size=1, max_overflow=0)
    base.dispose()
    ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), branch_ids=(uuid.uuid4(),))
    with session_scope(engine, ctx) as s:
        pid = scalar(s, "SELECT pg_backend_pid()")
    with pytest.raises(RuntimeError), session_scope(engine, ctx) as s:
        assert scalar(s, "SELECT pg_backend_pid()") == pid
        raise RuntimeError("boom")
    for _ in range(2):
        with session_scope(engine) as s:  # no context supplied
            assert scalar(s, "SELECT pg_backend_pid()") == pid
            for name in ("app.tenant_id", "app.user_id", "app.branch_ids"):
                assert scalar(s, "SELECT current_setting(:n, true)", n=name) in ("", None)
    engine.dispose()


def test_commit_and_rollback_semantics(role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = create_db_engine(settings_for(role_env, monkeypatch), role="owner")
    with session_scope(owner) as s:
        s.execute(text("CREATE TABLE t03 (id int)"))
    with session_scope(owner) as s:
        s.execute(text("INSERT INTO t03 VALUES (1)"))
    with pytest.raises(RuntimeError), session_scope(owner) as s:
        s.execute(text("INSERT INTO t03 VALUES (2)"))
        raise RuntimeError("boom")
    with session_scope(owner) as s:
        assert scalar(s, "SELECT array_agg(id) FROM t03") == [1]
    owner.dispose()


def test_database_error_rolls_back_and_releases_connection(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_db_engine(settings_for(role_env, monkeypatch))
    with pytest.raises(DBAPIError), session_scope(engine) as s:
        s.execute(text("SELECT 1/0"))
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    with session_scope(engine) as s:  # connection is usable again
        assert scalar(s, "SELECT 1") == 1
    engine.dispose()


def test_session_closed_after_scope(role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_db_engine(settings_for(role_env, monkeypatch))
    factory = create_session_factory(engine)
    with session_scope(factory, RequestContext(tenant_id=uuid.uuid4())) as s:
        assert s.in_transaction()
    assert not s.in_transaction()
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    engine.dispose()


def test_worker_context_is_independent_of_app(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(role_env, monkeypatch)
    app_engine = create_db_engine(settings, role="app")
    worker_engine = create_db_engine(settings, role="worker")
    t_app, t_worker = uuid.uuid4(), uuid.uuid4()
    with (
        session_scope(app_engine, RequestContext(tenant_id=t_app)) as a,
        session_scope(worker_engine, RequestContext(tenant_id=t_worker)) as w,
    ):
        assert scalar(a, "SELECT current_setting('app.tenant_id', true)") == str(t_app)
        assert scalar(w, "SELECT current_setting('app.tenant_id', true)") == str(t_worker)
        assert scalar(w, "SELECT current_user") == role_env.names.worker
    app_engine.dispose()
    worker_engine.dispose()


def test_runtime_engine_is_not_owner_and_cannot_use_owner(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine: Engine = create_db_engine(settings_for(role_env, monkeypatch))
    with session_scope(engine) as s:
        assert scalar(s, "SELECT current_user") != role_env.names.owner
    with pytest.raises(DBAPIError), session_scope(engine) as s:
        s.execute(text(f'SET ROLE "{role_env.names.owner}"'))
    engine.dispose()


# --- R01: explicit transactions (autobegin disabled) -------------------------------------


def test_factory_disables_autobegin_and_scope_rejects_autobegin_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_db_engine(synthetic(monkeypatch, all_roles=True))
    assert create_session_factory(engine).kw["autobegin"] is False
    with pytest.raises(ValueError, match="autobegin"), session_scope(sessionmaker(engine)):
        pytest.fail("scope must not be entered")
    engine.dispose()


def test_session_outside_scope_cannot_run_any_statement(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_db_engine(settings_for(role_env, monkeypatch))
    with create_session_factory(engine)() as session:
        with pytest.raises(InvalidRequestError, match="Autobegin is disabled"):
            session.execute(text("SELECT 1"))
        assert not session.in_transaction()
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    engine.dispose()


@pytest.mark.parametrize("early", ["commit", "rollback", "close"])
def test_early_transaction_end_rejects_further_statements_and_drops_context(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch, early: str
) -> None:
    # One physical connection: the next scope must reuse it and must see no context.
    base = create_db_engine(settings_for(role_env, monkeypatch))
    engine = create_engine(base.url, pool_size=1, max_overflow=0)
    base.dispose()
    ctx = RequestContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), branch_ids=(uuid.uuid4(),))
    with session_scope(engine, ctx) as s:
        pid = scalar(s, "SELECT pg_backend_pid()")
    with session_scope(engine, ctx) as s:
        getattr(s, early)()
        assert not s.in_transaction()
        with pytest.raises(InvalidRequestError):
            s.execute(text("SELECT current_setting('app.tenant_id', true)"))
        assert not s.in_transaction()  # no new, context-free transaction was started
    assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    with session_scope(engine) as s:
        assert scalar(s, "SELECT pg_backend_pid()") == pid
        for name in ("app.tenant_id", "app.user_id", "app.branch_ids"):
            assert scalar(s, "SELECT current_setting(:n, true)", n=name) in ("", None)
    engine.dispose()


def test_early_commit_persists_and_early_rollback_discards_prior_work(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = create_db_engine(settings_for(role_env, monkeypatch), role="owner")
    with session_scope(owner) as s:
        s.execute(text("CREATE TABLE r01 (id int)"))
    with session_scope(owner) as s:
        s.execute(text("INSERT INTO r01 VALUES (1)"))
        s.commit()
        with pytest.raises(InvalidRequestError):
            s.execute(text("INSERT INTO r01 VALUES (2)"))
    with session_scope(owner) as s:
        s.execute(text("INSERT INTO r01 VALUES (3)"))
        s.rollback()
        with pytest.raises(InvalidRequestError):
            s.execute(text("INSERT INTO r01 VALUES (4)"))
    with session_scope(owner) as s:
        assert scalar(s, "SELECT array_agg(id ORDER BY id) FROM r01") == [1]
    owner.dispose()


def test_scope_commits_at_exit_on_one_connection_and_closes(
    role_env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = create_db_engine(settings_for(role_env, monkeypatch), role="owner")
    with session_scope(owner) as s:
        s.execute(text("CREATE TABLE r01_exit (id int)"))
        s.execute(text("INSERT INTO r01_exit VALUES (7)"))
        assert s.in_transaction()
    assert not s.in_transaction()
    with session_scope(owner) as other:
        assert scalar(other, "SELECT id FROM r01_exit") == 7
    owner.dispose()
