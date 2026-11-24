"""Alembic environment. Migrations run as the database owner role only."""

from alembic import context
from app.core.config import get_settings
from app.core.db import create_db_engine
from sqlalchemy import Connection

target_metadata = None  # Schema is managed with explicit SQL migrations.


def _run(connection: Connection) -> None:
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
