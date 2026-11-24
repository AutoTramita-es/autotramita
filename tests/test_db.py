import uuid

import pytest
from app.core.config import DatabaseCredentials, Settings
from app.core.db import RequestContext, apply_context, build_url, session_scope
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session


def settings() -> Settings:
    return Settings.model_construct(
        postgres_host="db.example",
        postgres_port=5433,
        postgres_db="d",
        postgres_user="u",
        postgres_password=SecretStr("p"),
    )


def test_build_url_escapes_password_and_hides_it() -> None:
    creds = DatabaseCredentials(user="u", password=SecretStr("p@ss/word:1"))
    url = build_url(settings(), creds)
    assert url.password == "p@ss/word:1"
    assert "p@ss/word:1" not in url.render_as_string(hide_password=True)
    assert url.drivername == "postgresql+psycopg"
    assert (url.host, url.port, url.database) == ("db.example", 5433, "d")


def read(session: Session, name: str) -> str:
    return str(session.execute(text("SELECT current_setting(:n, true)"), {"n": name}).scalar())


def test_context_is_visible_inside_transaction(scratch_engine: Engine) -> None:
    tenant, user, branch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ctx = RequestContext(user_id=user, tenant_id=tenant, branch_ids=(branch,))
    with session_scope(scratch_engine, ctx) as s:
        assert read(s, "app.tenant_id") == str(tenant)
        assert read(s, "app.user_id") == str(user)
        assert read(s, "app.branch_ids") == str(branch)


def test_context_does_not_leak_across_pooled_connections(scratch_engine: Engine) -> None:
    ctx = RequestContext(tenant_id=uuid.uuid4())
    with session_scope(scratch_engine, ctx) as s:
        pid_first = s.execute(text("SELECT pg_backend_pid()")).scalar()
    # Same pool, very likely the same physical connection; context must be gone.
    with Session(scratch_engine) as s2:
        pid_second = s2.execute(text("SELECT pg_backend_pid()")).scalar()
        assert pid_first == pid_second
        assert read(s2, "app.tenant_id") in ("", "None")


def test_commit_inside_scope_drops_context(scratch_engine: Engine) -> None:
    ctx = RequestContext(tenant_id=uuid.uuid4())
    with Session(scratch_engine) as s:
        apply_context(s, ctx)
        s.commit()
        assert read(s, "app.tenant_id") in ("", "None")


def test_failed_scope_rolls_back(scratch_engine: Engine) -> None:
    with scratch_engine.begin() as c:
        c.execute(text("CREATE TABLE t (id int)"))
    with pytest.raises(RuntimeError), session_scope(scratch_engine) as s:
        s.execute(text("INSERT INTO t VALUES (1)"))
        raise RuntimeError("boom")
    with scratch_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM t")).scalar() == 0
