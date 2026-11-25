"""Fixtures of the platform-grant tests (F2-T10)."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from app.core.db import create_session_factory
from app.core.pagination import CursorCodec
from tests.auth.fake_admin import FakeAdmin, RecordingNotifier
from tests.auth.web_harness import build_web
from tests.conftest import RoleEnv
from tests.platform.rig import PlatformRig
from tests.test_roles_and_migrations import migrate


@pytest.fixture
def rig(role_env: RoleEnv, redis_url: str) -> Iterator[PlatformRig]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    web = build_web(role_env, redis_url, AUTH_SECURITY_HMAC_KEY="k" * 32)
    web.clock.now = time.time()  # token times are ages relative to the real clock
    admin, notifier = FakeAdmin(), RecordingNotifier()
    web.runtime.admin, web.runtime.notifier = admin, notifier
    web.runtime.platform_factory = create_session_factory(role_env.engine("platform"))
    web.runtime.cursor_codec = CursorCodec(b"c" * 32)
    yield PlatformRig(role_env, web, admin, notifier)
    web.close()
