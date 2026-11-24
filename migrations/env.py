"""Alembic environment. Migrations run as the database owner role only."""

from alembic import context
from app.core.config import get_settings
from app.core.db import create_db_engine
from sqlalchemy import Connection

target_metadata = None  # Schema is managed with explicit SQL migrations.


def _require_owner(connection: Connection) -> None:
    """Refuse to migrate unless the connected role owns the hardened migration schema.

    The runtime roles (app, worker, platform) and superusers do not own it, so migrations
    can only run as the owner role on a database prepared with scripts/db/harden.sql.
    """
    row = connection.exec_driver_sql(
        "SELECT pg_get_userbyid(nspowner) = current_user FROM pg_namespace "
        "WHERE nspname = 'schema_migrations'"
    ).one_or_none()
    if row is None or not row[0]:
        raise RuntimeError(
            "Migrations must run as the owner role on a hardened database "
            "(schema_migrations owned by the connected role)."
        )
    connection.commit()  # end the read-only check; Alembic starts its own transaction


def _run(connection: Connection) -> None:
    _require_owner(connection)
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
        _run(supplied)
        return
    engine = create_db_engine(get_settings(), role="owner")
    try:
        with engine.connect() as connection:
            _run(connection)
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported.")
run_migrations_online()
