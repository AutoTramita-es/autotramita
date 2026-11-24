"""Alembic environment. Migrations run as the database owner role only."""

from alembic import context
from app.core.config import get_settings
from app.core.db import create_db_engine
from sqlalchemy import Connection

target_metadata = None  # Schema is managed with explicit SQL migrations.


_OWNER_CHECK = """
SELECT r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb, r.rolreplication,
       r.rolcanlogin, session_user = current_user,
       coalesce((SELECT pg_get_userbyid(nspowner) = current_user FROM pg_namespace
                 WHERE nspname = 'schema_migrations'), false),
       coalesce((SELECT pg_get_userbyid(nspowner) = current_user FROM pg_namespace
                 WHERE nspname = 'public'), false),
       EXISTS (SELECT 1 FROM pg_roles g WHERE g.oid <> r.oid AND pg_has_role(r.oid, g.oid, 'MEMBER')
               AND (g.rolsuper OR g.rolbypassrls OR g.rolcreaterole OR g.rolcreatedb
                    OR g.rolreplication)),
       current_user
FROM pg_roles r WHERE r.rolname = current_user
"""


_RUNTIME_KINDS = ("app", "worker", "platform")
_ROLE_STATE = """
SELECT has_database_privilege(r.oid, current_database(), 'CONNECT'),
       r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
       OR EXISTS (SELECT 1 FROM pg_roles g WHERE g.oid <> r.oid
                  AND pg_has_role(r.oid, g.oid, 'MEMBER'))
FROM pg_roles r WHERE r.rolname = %s
"""
_SUFFIXED = """
SELECT rolname FROM pg_roles WHERE rolname ~ '_(app|worker|platform)$'
    AND has_database_privilege(rolname, current_database(), 'CONNECT')
"""


def _require_runtime_roles(connection: Connection, expected_owner: str) -> None:
    """Migrations grant privileges only to the explicitly configured runtime roles (R07): the
    caller names the app, worker and platform role; each must exist, be able to connect, hold
    no elevated attribute or membership, and no further role of that naming scheme may be able
    to connect to this database. Read-only; refuses before anything is executed."""
    names = context.config.attributes.get("expected_runtime_roles")
    if not isinstance(names, dict) or set(names) != set(_RUNTIME_KINDS):
        raise RuntimeError("migration requires explicitly configured runtime role names")
    values = [names[kind] for kind in _RUNTIME_KINDS]
    if (
        any(not isinstance(name, str) or not name for name in values)
        or len({*values, expected_owner}) != len(values) + 1
    ):
        raise RuntimeError("migration requires three distinct runtime role names")
    for kind in _RUNTIME_KINDS:
        state = connection.exec_driver_sql(_ROLE_STATE, (names[kind],)).one_or_none()
        if not names[kind].endswith("_" + kind) or state is None or not state[0] or state[1]:
            raise RuntimeError("configured runtime role is missing or not least-privileged")
    if set(connection.exec_driver_sql(_SUFFIXED).scalars().all()) != set(values):
        raise RuntimeError("configured runtime role names do not match the database roles")


def _require_owner(connection: Connection, expected: str | None) -> None:
    """Refuse to migrate unless the connection is the least-privileged owner role (R02, R03).

    The connection must be fresh: a caller-owned transaction is rejected without being
    committed or rolled back. The expected owner role name is MANDATORY (engine path: the
    configured owner; supplied connection: ``config.attributes["expected_owner"]``); a missing
    or empty name, or one that differs from the connected role, rejects the migration. The role
    must also log in as itself (no SET ROLE / SET SESSION AUTHORIZATION), own both
    ``schema_migrations`` and ``public`` as prepared by scripts/db/harden.sql, have no
    superuser, BYPASSRLS, CREATEROLE, CREATEDB or REPLICATION attribute, and not be a
    member of a role that does. Runtime roles (app, worker, platform) fail the ownership
    checks. Nothing is executed on rejection beyond this read-only catalog query.
    """
    if not isinstance(expected, str) or not expected:
        raise RuntimeError(
            "Migrations require the expected owner role name (config.attributes"
            "['expected_owner']); none was given, nothing was executed."
        )
    if connection.in_transaction():
        raise RuntimeError(
            "Migrations need a fresh connection without an active transaction; "
            "the caller's transaction was left untouched."
        )
    row = connection.exec_driver_sql(_OWNER_CHECK).one_or_none()
    # Only our own read-only check transaction exists here (none was active on entry).
    connection.rollback()
    if row is None:
        raise RuntimeError("Migration role could not be verified.")
    (*attributes, can_login, same_session, owns_migrations, owns_public, member, current) = row
    if (
        any(attributes)
        or member
        or not (can_login and same_session and owns_migrations and owns_public)
        or current != expected
    ):
        raise RuntimeError(
            "Migrations must run as the expected least-privileged owner role on a hardened "
            "database (owner of schema_migrations and public, no elevated attributes)."
        )


def _run(connection: Connection, expected_owner: str | None) -> None:
    _require_owner(connection, expected_owner)
    assert expected_owner is not None  # noqa: S101 - rejected above otherwise
    _require_runtime_roles(connection, expected_owner)
    connection.rollback()  # only our own read-only checks ran in this transaction
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="schema_migrations",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        # Mandatory: callers supplying a connection must name the owner role they expect.
        _run(supplied, context.config.attributes.get("expected_owner"))
        return
    settings = get_settings()
    # Names are explicitly configured, never discovered by suffix for security decisions.
    context.config.attributes["expected_runtime_roles"] = {
        "app": settings.postgres_user,
        "worker": settings.worker_user,
        "platform": settings.platform_user,
    }
    engine = create_db_engine(settings, role="owner")
    try:
        with engine.connect() as connection:
            _run(connection, settings.role_credentials("owner").user)
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported.")
run_migrations_online()
