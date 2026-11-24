"""Fixtures for the Keycloak integration tests. They run only in the dedicated CI job (marker
``keycloak``) against a disposable container; a missing variable fails the run in CI."""

import os
from collections.abc import Iterator

import pytest
from tests.identity.kc import Admin, BackchannelSink, Browser, Env, SmtpSink


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
