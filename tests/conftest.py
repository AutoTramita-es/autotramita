"""Shared fixtures. Integration tests need a throwaway PostgreSQL 16 and Redis.

Local: start disposable containers and export TEST_PG_ADMIN_URL (superuser) and
TEST_REDIS_URL. In CI (``CI`` set) a missing variable fails the run instead of skipping.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("CI"):
        pytest.fail(f"{name} must be set in CI")
    pytest.skip(f"{name} not set; integration test skipped")


@pytest.fixture(scope="session")
def pg_admin_url() -> str:
    return _require("TEST_PG_ADMIN_URL")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return _require("TEST_REDIS_URL")


@pytest.fixture
def scratch_database(pg_admin_url: str) -> Iterator[str]:
    """A fresh empty database owned by the superuser; dropped afterwards."""
    name = f"at_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(
        pg_admin_url.replace("postgresql://", "postgresql+psycopg://"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield name
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def scratch_engine(pg_admin_url: str, scratch_database: str) -> Iterator[Engine]:
    url = make_url(pg_admin_url.replace("postgresql://", "postgresql+psycopg://"))
    engine = create_engine(url.set(database=scratch_database))
    yield engine
    engine.dispose()
