"""Shared fixtures. Integration tests need a throwaway PostgreSQL 16 and Redis.

Local: start disposable containers and export TEST_PG_ADMIN_URL (superuser) and
TEST_REDIS_URL. In CI (``CI`` set) a missing variable fails the run instead of skipping.
"""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from app.core.dbroles import RoleNames, create_roles, harden
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url


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


def _sa_url(admin_url: str) -> URL:
    return make_url(admin_url.replace("postgresql://", "postgresql+psycopg://"))


@dataclass(frozen=True)
class RoleEnv:
    """A scratch database with the four-role model applied."""

    names: RoleNames
    passwords: dict[str, str]
    database: str
    admin_url: str

    def url(self, kind: str) -> URL:
        role = getattr(self.names, kind)
        return _sa_url(self.admin_url).set(
            username=role, password=self.passwords[kind], database=self.database
        )

    def engine(self, kind: str) -> Engine:
        return create_engine(self.url(kind))

    def admin_engine(self) -> Engine:
        return create_engine(
            _sa_url(self.admin_url).set(database=self.database), isolation_level="AUTOCOMMIT"
        )


@pytest.fixture
def role_env(pg_admin_url: str) -> Iterator[RoleEnv]:
    """Fresh database owned by the owner role, with roles created and hardened."""
    base = f"at_{uuid.uuid4().hex[:10]}"
    names = RoleNames.for_base(base)
    passwords = {
        k: uuid.uuid4().hex + uuid.uuid4().hex for k in ("owner", "app", "worker", "platform")
    }
    database = f"{base}_db"
    with psycopg.connect(pg_admin_url, autocommit=True) as admin:
        create_roles(admin, names, passwords)
        admin.execute(f'CREATE DATABASE "{database}" OWNER "{names.owner}"')
    db_url = _sa_url(pg_admin_url).set(database=database).render_as_string(hide_password=False)
    with psycopg.connect(db_url.replace("+psycopg", ""), autocommit=True) as conn:
        harden(conn, database, names)
    try:
        yield RoleEnv(names, passwords, database, pg_admin_url)
    finally:
        with psycopg.connect(pg_admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            for role in names.all():
                admin.execute(f'DROP ROLE IF EXISTS "{role}"')
