"""F1-T04: role SQL (scripts/db/harden.sql) and Alembic on a disposable PostgreSQL 16.

Evidence for AC03 (migration up/down) and AC04 (role safety). Everything runs on the
throwaway database of ``role_env``; nothing touches shared servers.
"""

import psycopg
import pytest
from app.core.dbroles import harden
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from tests.conftest import RoleEnv, _sa_url
from tests.test_roles_and_migrations import migrate

RUNTIME = ("app", "worker", "platform")
# Technical (non-business) tables allowed to exist after upgrade head. F1 ships none (the
# idempotency table is a test fixture); any table in public would be a business table.
NON_BUSINESS_TABLES: set[str] = set()
TABLE_PRIVS = "ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']"


def scalar(env: RoleEnv, sql: str, **params: object) -> object:
    with env.admin_engine().connect() as c:
        return c.execute(text(sql), params).scalar()


def rows(env: RoleEnv, sql: str, **params: object) -> list[tuple[object, ...]]:
    with env.admin_engine().connect() as c:
        return [tuple(r) for r in c.execute(text(sql), params).all()]


def run_harden(env: RoleEnv) -> None:
    url = _sa_url(env.admin_url).set(database=env.database).render_as_string(hide_password=False)
    with psycopg.connect(url.replace("+psycopg", ""), autocommit=True) as conn:
        harden(conn, env.database, env.names)


def acl_snapshot(env: RoleEnv) -> list[list[tuple[object, ...]]]:
    return [
        rows(
            env,
            "SELECT nspname, pg_get_userbyid(nspowner), nspacl::text FROM pg_namespace "
            "WHERE nspname IN ('public','schema_migrations') ORDER BY 1",
        ),
        rows(
            env,
            "SELECT pg_get_userbyid(defaclrole), defaclnamespace::regnamespace::text, "
            "defaclobjtype, defaclacl::text FROM pg_default_acl ORDER BY 1,2,3",
        ),
        rows(env, "SELECT datacl::text FROM pg_database WHERE datname = current_database()"),
    ]


def schema_objects(env: RoleEnv) -> tuple[set[str], set[str]]:
    tables = {
        str(r[0])
        for r in rows(
            env,
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')",
        )
    }
    functions = {
        str(r[0])
        for r in rows(
            env,
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public'",
        )
    }
    return tables, functions


# --- role SQL: idempotent, least privilege -------------------------------------------------


def test_role_sql_is_idempotent(role_env: RoleEnv) -> None:
    first = acl_snapshot(role_env)
    run_harden(role_env)
    run_harden(role_env)
    assert acl_snapshot(role_env) == first


def test_role_attributes_and_no_memberships(role_env: RoleEnv) -> None:
    names = list(role_env.names.all())
    for row in rows(
        role_env,
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
        "rolinherit, rolcanlogin FROM pg_roles WHERE rolname = ANY(:n)",
        n=names,
    ):
        assert row[1:6] == (False,) * 5, row
        assert row[6] is False, row  # NOINHERIT
        assert row[7] is True, row
    members = scalar(
        role_env,
        "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid IN (m.roleid, m.member) "
        "WHERE r.rolname = ANY(:n)",
        n=names,
    )
    assert members == 0  # no role can SET ROLE into another through membership


def test_public_has_no_schema_or_database_privileges(role_env: RoleEnv) -> None:
    assert (
        scalar(
            role_env,
            "SELECT count(*) FROM pg_namespace n, aclexplode(n.nspacl) a "
            "WHERE n.nspname IN ('public','schema_migrations') AND a.grantee = 0",
        )
        == 0
    )
    assert (
        scalar(
            role_env,
            "SELECT count(*) FROM pg_database d, aclexplode(d.datacl) a "
            "WHERE d.datname = current_database() AND a.grantee = 0",
        )
        == 0
    )


def test_schema_and_database_privileges_per_role(role_env: RoleEnv) -> None:
    def has(role: str, sql: str) -> object:
        return scalar(role_env, sql, r=getattr(role_env.names, role), d=role_env.database)

    assert has("owner", "SELECT has_schema_privilege(:r, 'public', 'CREATE')") is True
    assert has("owner", "SELECT has_schema_privilege(:r, 'schema_migrations', 'CREATE')") is True
    for role in RUNTIME:
        assert has(role, "SELECT has_schema_privilege(:r, 'public', 'USAGE')") is True
        assert has(role, "SELECT has_schema_privilege(:r, 'public', 'CREATE')") is False
        assert has(role, "SELECT has_schema_privilege(:r, 'schema_migrations', 'USAGE')") is False
        assert has(role, "SELECT has_schema_privilege(:r, 'schema_migrations', 'CREATE')") is False
        assert has(role, "SELECT has_database_privilege(:r, :d, 'CONNECT')") is True
        assert has(role, "SELECT has_database_privilege(:r, :d, 'CREATE')") is False
        assert has(role, "SELECT has_database_privilege(:r, :d, 'TEMPORARY')") is False


def test_default_privileges_are_scoped_to_owner_app_and_worker(role_env: RoleEnv) -> None:
    acl = rows(
        role_env,
        "SELECT pg_get_userbyid(d.defaclrole), d.defaclobjtype, a.grantee, a.privilege_type "
        "FROM pg_default_acl d, aclexplode(d.defaclacl) a",
    )
    assert acl, "default privileges are expected"
    oids = {
        r[0]: r[1]
        for r in rows(
            role_env,
            "SELECT rolname, oid::int FROM pg_roles WHERE rolname = ANY(:n)",
            n=list(role_env.names.all()),
        )
    }
    by_oid = {v: k for k, v in oids.items()}
    for definer, _objtype, grantee, _priv in acl:
        assert definer == role_env.names.owner  # only the owner's future objects are covered
        assert grantee != 0  # nothing for PUBLIC
        assert by_oid.get(grantee) != role_env.names.platform  # no blanket platform grant
    tables = {
        (by_oid.get(g), p)
        for _d, t, g, p in acl
        if t == "r" and by_oid.get(g) != role_env.names.owner
    }
    assert tables == {
        (role, priv)
        for role in (role_env.names.app, role_env.names.worker)
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }


# --- runtime roles: no DDL, no escalation, no platform blanket access ----------------------


def attempt(engine: Engine, sql: str) -> None:
    with engine.connect() as c, pytest.raises(DBAPIError):
        c.execute(text(sql))
    engine.dispose()


@pytest.mark.parametrize("kind", RUNTIME)
def test_runtime_roles_cannot_run_ddl_or_escalate(role_env: RoleEnv, kind: str) -> None:
    with role_env.engine("owner").begin() as c:
        c.execute(text("CREATE TABLE t04 (id int primary key)"))
    owner = role_env.names.owner
    statements = [
        "CREATE TABLE intruder (id int)",
        "CREATE SCHEMA intruder",
        "CREATE FUNCTION intruder() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        "ALTER TABLE t04 ADD COLUMN x int",
        "ALTER TABLE t04 DISABLE ROW LEVEL SECURITY",
        "DROP TABLE t04",
        "TRUNCATE t04",
        "CREATE ROLE intruder",
        f'SET ROLE "{owner}"',
        f'SET SESSION AUTHORIZATION "{owner}"',
        "CREATE TABLE schema_migrations.intruder (id int)",
    ]
    for sql in statements:
        attempt(role_env.engine(kind), sql)
    assert "t04" in schema_objects(role_env)[0]
    assert "intruder" not in schema_objects(role_env)[0]


def test_platform_has_no_table_privileges(role_env: RoleEnv) -> None:
    migrate(role_env.engine("owner"), "upgrade", "head")
    with role_env.engine("owner").begin() as c:
        c.execute(text("CREATE TABLE t04 (id int primary key)"))
    count = scalar(
        role_env,
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, "
        f"unnest({TABLE_PRIVS}) p WHERE n.nspname = 'public' AND c.relkind IN ('r','p') "
        "AND has_table_privilege(:r, c.oid, p)",
        r=role_env.names.platform,
    )
    assert count == 0


# --- Alembic: owner only, up / down / up, no business tables -------------------------------


@pytest.mark.parametrize("kind", RUNTIME)
def test_migrations_refuse_non_owner_roles(role_env: RoleEnv, kind: str) -> None:
    engine = role_env.engine(kind)
    with pytest.raises(RuntimeError, match="owner role"):
        migrate(engine, "upgrade", "head")
    engine.dispose()
    assert schema_objects(role_env) == (set(), set())


def test_migrations_refuse_unhardened_database(scratch_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="owner role"):
        migrate(scratch_engine, "upgrade", "head")


def test_upgrade_downgrade_upgrade_and_schema_contents(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")

    migrate(owner, "upgrade", "head")
    tables_up, functions_up = schema_objects(role_env)
    assert tables_up == NON_BUSINESS_TABLES  # no business tables
    assert {"app_user_id", "app_tenant_id", "app_branch_ids"} <= functions_up
    assert (
        scalar(
            role_env,
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner <> :o",
            o=role_env.names.owner,
        )
        == 0
    )
    assert (
        scalar(
            role_env,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT (c.relrowsecurity "
            "AND c.relforcerowsecurity)",
        )
        == 0
    )

    migrate(owner, "downgrade", "base")
    assert schema_objects(role_env) == (set(), set())
    assert scalar(role_env, "SELECT count(*) FROM schema_migrations.alembic_version") == 0

    migrate(owner, "upgrade", "head")
    assert schema_objects(role_env) == (tables_up, functions_up)
    owner.dispose()
