"""Shared fixtures. Integration tests need a throwaway PostgreSQL 16 and Redis.

Local: start disposable containers and export TEST_PG_ADMIN_URL (superuser) and
TEST_REDIS_URL. In CI (``CI`` set) a missing variable fails the run instead of skipping.

The suite runs in two parts (INFRA-CI-02): most tests in parallel pytest-xdist workers, then the
tests listed in ``tests/serial_tests.py`` alone. Every test creates its own databases and roles.
Workers additionally share nothing: each has a PostgreSQL server of its own, because roles are
global to a server and migrations inspect all of them, and a Redis logical database of its own.
"""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from app.core.dbroles import RoleNames, create_roles, harden
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from tests.serial_tests import SPLIT_FILES, is_serial
from xdist.remote import Producer  # type: ignore[import-untyped]  # xdist ships no types
from xdist.scheduler import LoadFileScheduling  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


@pytest.hookimpl(tryfirst=True)  # before ``-m`` deselects
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        function = getattr(item, "originalname", item.name)
        if item.path.is_relative_to(ROOT) and is_serial(
            item.path.relative_to(ROOT).as_posix(), function
        ):
            item.add_marker(pytest.mark.serial)


class FileScheduling(LoadFileScheduling):  # type: ignore[misc]
    """``--dist loadfile``, except that the tests of ``SPLIT_FILES`` are separate work units."""

    def _split_scope(self, nodeid: str) -> str:
        file = str(super()._split_scope(nodeid))
        return nodeid if file in SPLIT_FILES else file


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config: pytest.Config, log: Producer) -> FileScheduling | None:
    return FileScheduling(config, log) if config.getoption("dist") == "loadfile" else None


def worker_redis_url(url: str, worker: str | None, workers_url: str | None) -> str:
    """The Redis URL of one xdist worker. The first worker and serial runs use the configured
    database; worker ``gwN`` uses logical database N of the server of the additional workers."""
    if worker is None or worker == "gw0":
        return url
    if not workers_url:
        raise ValueError(
            "parallel workers need Redis databases of their own: set TEST_REDIS_WORKERS_URL "
            "(a server with enough logical databases) or run pytest without -n"
        )
    return urlunsplit(urlsplit(workers_url)._replace(path=f"/{int(worker.removeprefix('gw'))}"))


def worker_pg_url(url: str, worker: str | None, port_base: str | None) -> str:
    """The PostgreSQL URL of one xdist worker. The first worker and serial runs use the
    configured server; worker ``gwN`` uses the one on port ``port_base + N``. Sharing a server is
    refused: it fails at random, when one worker drops a role another one is looking at."""
    if worker is None or worker == "gw0":
        return url
    if not port_base:
        raise ValueError(
            "parallel workers need a PostgreSQL server each: set TEST_PG_WORKER_PORT_BASE "
            "(worker gwN connects to that port + N) or run pytest without -n"
        )
    parts = urlsplit(url)
    credentials, at, _ = parts.netloc.rpartition("@")
    port = int(port_base) + int(worker.removeprefix("gw"))
    return urlunsplit(parts._replace(netloc=f"{credentials}{at}{parts.hostname}:{port}"))


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("CI"):
        pytest.fail(f"{name} must be set in CI")
    pytest.skip(f"{name} not set; integration test skipped")


@pytest.fixture(scope="session")
def pg_admin_url() -> str:
    return worker_pg_url(
        _require("TEST_PG_ADMIN_URL"),
        os.environ.get("PYTEST_XDIST_WORKER"),
        os.environ.get("TEST_PG_WORKER_PORT_BASE"),
    )


@pytest.fixture(scope="session")
def redis_url() -> str:
    return worker_redis_url(
        _require("TEST_REDIS_URL"),
        os.environ.get("PYTEST_XDIST_WORKER"),
        os.environ.get("TEST_REDIS_WORKERS_URL"),
    )


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
    # Every engine handed out is disposed at teardown, so no pooled connection is ever left
    # to the garbage collector (that raised ResourceWarning, which CI now treats as an error).
    _engines: list[Engine] = field(default_factory=list, compare=False, repr=False)

    def url(self, kind: str) -> URL:
        role = getattr(self.names, kind)
        return _sa_url(self.admin_url).set(
            username=role, password=self.passwords[kind], database=self.database
        )

    def engine(self, kind: str) -> Engine:
        engine = create_engine(self.url(kind))
        self._engines.append(engine)
        return engine

    def admin_engine(self) -> Engine:
        engine = create_engine(
            _sa_url(self.admin_url).set(database=self.database), isolation_level="AUTOCOMMIT"
        )
        self._engines.append(engine)
        return engine

    def dispose_engines(self) -> None:
        while self._engines:
            self._engines.pop().dispose()


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
    env = RoleEnv(names, passwords, database, pg_admin_url)
    try:
        yield env
    finally:
        env.dispose_engines()
        with psycopg.connect(pg_admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            for role in names.all():
                admin.execute(f'DROP ROLE IF EXISTS "{role}"')
