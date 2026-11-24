from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.dbroles import RoleNames, create_roles
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from tests.conftest import RoleEnv

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(engine: Engine) -> tuple[Config, object]:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    conn = engine.connect()
    cfg.attributes["connection"] = conn
    return cfg, conn


def migrate(engine: Engine, action: str, revision: str) -> None:
    cfg, conn = alembic_config(engine)
    try:
        getattr(command, action)(cfg, revision)
        conn.commit()  # type: ignore[attr-defined]
    finally:
        conn.close()  # type: ignore[attr-defined]


def test_role_names_are_validated() -> None:
    with pytest.raises(ValueError):
        RoleNames.for_base('x"; DROP ROLE y; --')


def test_roles_have_safe_attributes(role_env: RoleEnv) -> None:
    with role_env.admin_engine().connect() as c:
        rows = c.execute(
            text(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                "rolbypassrls "
                "FROM pg_roles WHERE rolname = ANY(:n)"
            ),
            {"n": list(role_env.names.all())},
        ).all()
    assert len(rows) == 4
    for row in rows:
        assert not any(row[1:]), row


def test_roles_require_distinct_passwords(pg_admin_url: str) -> None:
    import psycopg

    names = RoleNames.for_base("at_dup_check")
    same = {k: "x" * 40 for k in ("owner", "app", "worker", "platform")}
    with psycopg.connect(pg_admin_url, autocommit=True) as admin, pytest.raises(ValueError):
        create_roles(admin, names, same)


def test_only_owner_owns_and_creates_objects(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    with owner.begin() as c:
        c.execute(text("CREATE TABLE widgets (id int primary key)"))
    for kind in ("app", "worker", "platform"):
        with role_env.engine(kind).connect() as c, pytest.raises(ProgrammingError):
            c.execute(text("CREATE TABLE intruder (id int)"))
    with role_env.admin_engine().connect() as c:
        table_owner = c.execute(
            text("SELECT tableowner FROM pg_tables WHERE tablename='widgets'")
        ).scalar()
        schema_owner = c.execute(
            text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public'")
        ).scalar()
    assert table_owner == role_env.names.owner
    assert schema_owner == role_env.names.owner


def test_default_privileges_app_and_worker_yes_platform_no(role_env: RoleEnv) -> None:
    with role_env.engine("owner").begin() as c:
        c.execute(text("CREATE TABLE widgets (id int primary key)"))
    for kind in ("app", "worker"):
        with role_env.engine(kind).begin() as c:
            c.execute(text("INSERT INTO widgets VALUES (1) ON CONFLICT DO NOTHING"))
            assert c.execute(text("SELECT count(*) FROM widgets")).scalar() == 1
    with role_env.engine("platform").connect() as c, pytest.raises(ProgrammingError):
        c.execute(text("SELECT * FROM widgets"))


def test_public_has_no_access(role_env: RoleEnv, pg_admin_url: str) -> None:
    import psycopg

    stranger = f"{role_env.names.owner}_stranger"
    with psycopg.connect(pg_admin_url, autocommit=True) as admin:
        admin.execute(f"CREATE ROLE \"{stranger}\" LOGIN PASSWORD 'pw-{stranger}'")
        try:
            allowed = admin.execute(
                "SELECT has_database_privilege(%s, %s, 'CONNECT')", (stranger, role_env.database)
            ).fetchone()
            assert allowed == (False,)
        finally:
            admin.execute(f'DROP ROLE "{stranger}"')


def test_baseline_up_and_down(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    migrate(owner, "upgrade", "head")
    with role_env.engine("app").begin() as c:
        c.execute(
            text("SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true)")
        )
        assert (
            str(c.execute(text("SELECT app_tenant_id()")).scalar())
            == "00000000-0000-0000-0000-000000000001"
        )
        assert c.execute(text("SELECT app_user_id()")).scalar() is None
        assert c.execute(text("SELECT app_branch_ids()")).scalar() == []
    with role_env.engine("app").connect() as c, pytest.raises(ProgrammingError):
        c.execute(text("SELECT * FROM schema_migrations.alembic_version"))
    migrate(owner, "downgrade", "base")
    with role_env.admin_engine().connect() as c:
        left = c.execute(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'app\\_%'")).scalar()
    assert left == 0
