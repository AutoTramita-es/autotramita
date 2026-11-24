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


def _require_owner(connection: Connection, expected: str | None) -> None:
    """Refuse to migrate unless the connection is the least-privileged owner role (R02, R03).

    The connection must be fresh: a caller-owned transaction is rejected without being
    committed or rolled back. The connected role must be the expected owner (when known),
    log in as itself (no SET ROLE / SET SESSION AUTHORIZATION), own both ``schema_migrations``
    and ``public`` as prepared by scripts/db/harden.sql, have no superuser, BYPASSRLS,
    CREATEROLE, CREATEDB or REPLICATION attribute, and not be a member of a role that does.
    Runtime roles (app, worker, platform) fail the ownership checks. Nothing is executed on
    rejection beyond this read-only catalog query.
    """
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
        or (expected is not None and current != expected)
    ):
        raise RuntimeError(
            "Migrations must run as the expected least-privileged owner role on a hardened "
            "database (owner of schema_migrations and public, no elevated attributes)."
        )


def _run(connection: Connection, expected_owner: str | None) -> None:
    _require_owner(connection, expected_owner)
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
        # Optional: tests and tooling may pass the expected owner role name.
        _run(supplied, context.config.attributes.get("expected_owner"))
        return
    settings = get_settings()
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
