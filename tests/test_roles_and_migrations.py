from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.dbroles import RoleNames, create_roles
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError
from tests.conftest import RoleEnv

ROOT = Path(__file__).resolve().parents[1]


USE_ENGINE_USER = object()  # default: expect the role the engine connects as


def alembic_config(
    engine: Engine, expected_owner: object = USE_ENGINE_USER
) -> tuple[Config, object]:
    cfg = Config(str(ROOT / "alembic.ini"))
    if expected_owner is USE_ENGINE_USER:
        expected_owner = engine.url.username
    if expected_owner is not None:
        cfg.attributes["expected_owner"] = expected_owner
    # The disposable harness uses the project's explicit per-environment role names.
    username = engine.url.username or ""
    if username.endswith("_owner"):
        base = username.removesuffix("_owner")
        cfg.attributes["expected_runtime_roles"] = {
            role: f"{base}_{role}" for role in ("app", "worker", "platform")
        }
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


# --- R02 / R03: migration owner identity and caller-transaction protection -----------------


def try_upgrade(engine: Engine, expected_owner: object = USE_ENGINE_USER) -> None:
    cfg, conn = alembic_config(engine, expected_owner)
    try:
        command.upgrade(cfg, "head")
    finally:
        conn.close()  # type: ignore[attr-defined]


def assert_nothing_migrated(env: RoleEnv) -> None:
    with env.admin_engine().connect() as c:
        assert (
            c.execute(text("SELECT to_regclass('schema_migrations.alembic_version')")).scalar()
            is None
        )
        assert (
            c.execute(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'app\\_%'")).scalar()
            == 0
        )


REJECTED = "least-privileged owner"


def test_migration_accepts_the_expected_owner(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    try_upgrade(owner, expected_owner=role_env.names.owner)
    owner.dispose()


def test_migration_rejects_a_different_expected_owner(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    with pytest.raises(RuntimeError, match=REJECTED):
        try_upgrade(owner, expected_owner=role_env.names.app)
    owner.dispose()
    assert_nothing_migrated(role_env)


@pytest.mark.parametrize("kind", ["app", "worker", "platform"])
def test_migration_rejects_runtime_roles_even_when_they_own_schema_migrations(
    role_env: RoleEnv, kind: str
) -> None:
    role = getattr(role_env.names, kind)
    engine = role_env.engine(kind)
    with pytest.raises(RuntimeError, match=REJECTED):
        try_upgrade(engine)
    with role_env.admin_engine().connect() as c:  # make the runtime role the schema owner
        c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{role}"'))
    with pytest.raises(RuntimeError, match=REJECTED):
        try_upgrade(engine)  # still not the owner of public
    with pytest.raises(RuntimeError, match=REJECTED):
        try_upgrade(engine, expected_owner=role)  # and it is not the owner role by attributes
    engine.dispose()
    with role_env.admin_engine().connect() as c:
        c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{role_env.names.owner}"'))
    assert_nothing_migrated(role_env)


@pytest.mark.parametrize(
    "attributes",
    ["BYPASSRLS", "CREATEROLE", "CREATEDB", "REPLICATION", "SUPERUSER"],
)
def test_migration_rejects_privileged_impostor_owning_both_schemas(
    role_env: RoleEnv, attributes: str
) -> None:
    imp = f"{role_env.names.owner}_imp"
    password = "pw-" + imp
    admin = role_env.admin_engine()
    with admin.connect() as c:
        c.execute(text(f"CREATE ROLE \"{imp}\" LOGIN PASSWORD '{password}' {attributes}"))
        c.execute(text(f'GRANT CONNECT ON DATABASE "{role_env.database}" TO "{imp}"'))
        c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{imp}"'))
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{imp}"'))
    engine = create_engine(role_env.url("owner").set(username=imp, password=password))
    try:
        with pytest.raises(RuntimeError, match=REJECTED):
            try_upgrade(engine, expected_owner=imp)
        with pytest.raises(RuntimeError, match=REJECTED):
            try_upgrade(engine)
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{role_env.names.owner}"'))
            c.execute(text(f'ALTER SCHEMA public OWNER TO "{role_env.names.owner}"'))
            c.execute(text(f'DROP OWNED BY "{imp}"'))
            c.execute(text(f'DROP ROLE "{imp}"'))
    assert_nothing_migrated(role_env)


def test_migration_rejects_owner_that_is_member_of_a_privileged_role(role_env: RoleEnv) -> None:
    helper = f"{role_env.names.owner}_priv"
    admin = role_env.admin_engine()
    with admin.connect() as c:
        c.execute(text(f'CREATE ROLE "{helper}" NOLOGIN BYPASSRLS'))
        c.execute(text(f'GRANT "{helper}" TO "{role_env.names.owner}"'))
    engine = role_env.engine("owner")
    try:
        with pytest.raises(RuntimeError, match=REJECTED):
            try_upgrade(engine, expected_owner=role_env.names.owner)
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'REVOKE "{helper}" FROM "{role_env.names.owner}"'))
            c.execute(text(f'DROP ROLE "{helper}"'))
    assert_nothing_migrated(role_env)


def test_migration_rejects_superuser_connection_after_ownership_transfer(
    role_env: RoleEnv,
) -> None:
    admin = role_env.admin_engine()
    with admin.connect() as c:
        who = c.execute(text("SELECT current_user")).scalar_one()
        c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{who}"'))
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{who}"'))
    try:
        with pytest.raises(RuntimeError, match=REJECTED):
            try_upgrade(admin)
    finally:
        with admin.connect() as c:
            c.execute(text(f'ALTER SCHEMA schema_migrations OWNER TO "{role_env.names.owner}"'))
            c.execute(text(f'ALTER SCHEMA public OWNER TO "{role_env.names.owner}"'))
    assert_nothing_migrated(role_env)


def test_migration_rejects_set_role_session(role_env: RoleEnv) -> None:
    # A superuser that switched to the owner role is not the owner: session_user differs.
    engine = create_engine(
        role_env.admin_engine().url, isolation_level="AUTOCOMMIT"
    )  # superuser login
    cfg, conn = alembic_config(engine, role_env.names.owner)
    try:
        conn.exec_driver_sql(f'SET ROLE "{role_env.names.owner}"')  # type: ignore[attr-defined]
        conn.commit()  # type: ignore[attr-defined]  # reset SQLAlchemy state; SET ROLE persists
        assert not conn.in_transaction()  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match=REJECTED):
            command.upgrade(cfg, "head")
    finally:
        conn.close()  # type: ignore[attr-defined]
        engine.dispose()
    assert_nothing_migrated(role_env)


def test_migration_rejects_caller_transaction_without_touching_it(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    cfg, conn = alembic_config(owner)
    conn.execute(text("CREATE TABLE caller_sentinel (id int)"))  # type: ignore[attr-defined]
    conn.execute(text("INSERT INTO caller_sentinel VALUES (42)"))  # type: ignore[attr-defined]
    try:
        with pytest.raises(RuntimeError, match="fresh connection"):
            command.upgrade(cfg, "head")
        # The caller's transaction is still open and untouched: nothing was committed or lost.
        assert conn.in_transaction()  # type: ignore[attr-defined]
        assert conn.execute(text("SELECT id FROM caller_sentinel")).scalar() == 42  # type: ignore[attr-defined]
        with role_env.admin_engine().connect() as other:
            assert other.execute(text("SELECT to_regclass('caller_sentinel')")).scalar() is None
        conn.rollback()  # type: ignore[attr-defined]
        with role_env.admin_engine().connect() as other:
            assert other.execute(text("SELECT to_regclass('caller_sentinel')")).scalar() is None
    finally:
        conn.close()  # type: ignore[attr-defined]
    assert_nothing_migrated(role_env)
    try_upgrade(owner, expected_owner=role_env.names.owner)  # fresh connection works
    owner.dispose()


def test_migration_lifecycle_on_fresh_owner_connection_up_down_up(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    for action, revision in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        migrate(owner, action, revision)
    owner.dispose()


@pytest.mark.parametrize("missing", [None, "", 5], ids=["none", "empty", "not-a-string"])
def test_expected_owner_is_mandatory_even_for_the_real_owner(
    role_env: RoleEnv, missing: object
) -> None:
    owner = role_env.engine("owner")
    with pytest.raises(RuntimeError, match="expected owner role name"):
        try_upgrade(owner, expected_owner=missing)
    owner.dispose()
    assert_nothing_migrated(role_env)


def test_expected_owner_must_match_the_connected_role_exactly(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    for wrong in (role_env.names.owner.upper(), role_env.names.owner + "x", role_env.names.app):
        with pytest.raises(RuntimeError, match=REJECTED):
            try_upgrade(owner, expected_owner=wrong)
    owner.dispose()
    assert_nothing_migrated(role_env)


@pytest.mark.parametrize("case", ["missing", "wrong", "duplicate"])
def test_f2_migration_requires_explicit_matching_runtime_roles(
    role_env: RoleEnv, case: str
) -> None:
    owner = role_env.engine("owner")
    migrate(owner, "upgrade", "0007")
    cfg, conn = alembic_config(owner)
    if case == "missing":
        cfg.attributes.pop("expected_runtime_roles")
    elif case == "wrong":
        cfg.attributes["expected_runtime_roles"]["worker"] = "wrong_worker"
    else:
        cfg.attributes["expected_runtime_roles"]["worker"] = role_env.names.app
    try:
        with pytest.raises(RuntimeError, match="runtime role"):
            command.upgrade(cfg, "head")
    finally:
        conn.close()  # type: ignore[attr-defined]
    with role_env.admin_engine().connect() as db:
        assert (
            db.execute(
                text("SELECT version_num FROM schema_migrations.alembic_version")
            ).scalar_one()
            == "0007"
        )
