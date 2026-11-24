"""Fixtures for the Keycloak integration tests. They run only in the dedicated CI job (marker
``keycloak``) against a disposable container; a missing variable fails the run in CI."""

import os
from collections.abc import Iterator

import pytest
from tests.conftest import RoleEnv
from tests.identity.kc import OPEN_BROWSERS, Admin, BackchannelSink, Browser, Env, SmtpSink
from tests.identity.rig import Rig
from tests.test_roles_and_migrations import migrate


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.environ.get("CI"):
        pytest.fail(f"{name} must be set in CI")
    pytest.skip(f"{name} not set; Keycloak integration test skipped")


@pytest.fixture(scope="session")
def env() -> Env:
    return Env(
        base_url=_require("TEST_KEYCLOAK_URL").rstrip("/"),
        admin_user=_require("TEST_KEYCLOAK_ADMIN_USER"),
        admin_password=_require("TEST_KEYCLOAK_ADMIN_PASSWORD"),
        web_secret=_require("AT_WEB_CLIENT_SECRET"),
        svc_secret=_require("AT_ADMIN_SVC_CLIENT_SECRET"),
    )


@pytest.fixture(scope="session")
def admin(env: Env) -> Iterator[Admin]:
    client = Admin(env)
    yield client
    client.close()


@pytest.fixture(scope="session")
def smtp() -> Iterator[SmtpSink]:
    sink = SmtpSink()
    sink.start()
    yield sink
    sink.stop()


@pytest.fixture(scope="session")
def backchannel() -> Iterator[BackchannelSink]:
    sink = BackchannelSink()
    sink.start()
    yield sink
    sink.stop()


@pytest.fixture
def browser(env: Env) -> Iterator[Browser]:
    b = Browser(env)
    yield b
    b.close()


@pytest.fixture(autouse=True)
def close_scripted_browsers() -> Iterator[None]:
    """Every scripted browser is closed after its test, even when the test failed midway."""
    yield
    while OPEN_BROWSERS:
        OPEN_BROWSERS.pop().close()


@pytest.fixture
def rig(env: Env, role_env: RoleEnv, redis_url: str) -> Iterator[Rig]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = Rig(env, role_env, redis_url)
    yield harness
    harness.close()
