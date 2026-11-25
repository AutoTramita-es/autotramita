"""Shared rig for the Keycloak tests of the application's sign-in (F2-T06, F2-T07): the real
application on real PostgreSQL and Redis, talking to the disposable Keycloak."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from app.api.app import create_app
from app.auth.idp_admin import KeycloakAdmin
from app.auth.runtime import AuthRuntime
from app.auth.settings import AuthSettings
from app.core.config import RateLimitSettings
from app.core.ratelimit import RateLimiter, create_redis
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.auth.fake_admin import RecordingNotifier
from tests.conftest import RoleEnv
from tests.identity.kc import REALM, Browser, Env, Page, TestUser

ORIGIN = "http://127.0.0.1:18080"
API = "/api/v1/auth"
SESSION, FLOW = "at_session", "at_flow"  # unprefixed: the test origin is plain-http loopback
Prove = Callable[[Browser, Page], Page]


class Rig:
    def __init__(self, env: Env, role_env: RoleEnv, redis_url: str) -> None:
        self.env, self.role_env = env, role_env
        settings = AuthSettings.model_validate(
            {
                "AUTH_OIDC_ISSUER": f"{env.base_url}/realms/{REALM}",
                "AUTH_WEB_ORIGIN": ORIGIN,
                "AUTH_COOKIE_SECURE": "false",
                "AUTH_WEB_CLIENT_SECRET": env.web_secret,
                "AUTH_JWKS_MIN_REFRESH_SECONDS": 0,
                "AUTH_ADMIN_CLIENT_SECRET": env.svc_secret,  # F2-T09: the real admin client
                "AUTH_SECURITY_HMAC_KEY": "k" * 32,
            }
        )
        client = create_redis(redis_url)
        engine = role_env.engine("app")
        runtime = AuthRuntime.build(settings, client, engine, namespace=f"kc{id(self)}")
        self.notices = RecordingNotifier()
        runtime.notifier = self.notices
        self.runtime = runtime
        limiter = RateLimiter(client, namespace=f"kc{id(self)}")
        app = create_app(limiter, engine, RateLimitSettings(), runtime)
        self.api = TestClient(app, base_url=ORIGIN, follow_redirects=False)
        self.browser = Browser(env)
        self.extra: list[TestClient] = []

    def close(self) -> None:
        if isinstance(self.runtime.admin, KeycloakAdmin):
            self.runtime.admin.close()
        for client in self.extra:
            client.close()
        self.api.close()
        self.browser.close()

    def rows(self, sql: str) -> list[tuple[Any, ...]]:
        with self.role_env.admin_engine().connect() as c:
            return [tuple(r) for r in c.execute(text(sql))]

    def at_keycloak(
        self,
        url: str,
        user: TestUser | None,
        browser: Browser | None = None,
        prove: Prove | None = None,
    ) -> str:
        """Follow the authorization URL in the scripted browser; sign in when asked, with
        ``prove`` answering the factor question. Returns the callback URL Keycloak redirects
        to."""
        use = browser or self.browser
        use._last = f"{ORIGIN}{API}/callback"
        page = use._settle(use.http.get(url), use._last)
        if page.location is None:
            assert user is not None
            page = use.submit(
                page, {"username": user.email, "password": user.password, "credentialId": ""}
            )
            if prove is not None and page.location is None:
                page = prove(use, page)
        assert page.location and page.location.startswith(f"{ORIGIN}{API}/callback"), page.summary
        return page.location

    def sign_in(
        self,
        user: TestUser,
        return_to: str = "/app",
        client: TestClient | None = None,
        browser: Browser | None = None,
        prove: Prove | None = None,
    ) -> httpx.Response:
        api = client or self.api
        start = api.get(f"{API}/login", params={"return_to": return_to})
        assert start.status_code == 302, start.text
        callback = self.at_keycloak(start.headers["location"], user, browser, prove)
        done: httpx.Response = api.get(callback)
        return done

    def another_client(self) -> TestClient:
        """A second browser tab of the application (own cookie jar, same Keycloak browser)."""
        client = TestClient(self.api.app, base_url=ORIGIN, follow_redirects=False)
        self.extra.append(client)
        return client
