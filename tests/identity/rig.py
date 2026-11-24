"""Shared rig for the Keycloak tests of the application's sign-in (F2-T06, F2-T07): the real
application on real PostgreSQL and Redis, talking to the disposable Keycloak."""

from __future__ import annotations

from typing import Any

import httpx
from app.api.app import create_app
from app.auth.runtime import AuthRuntime
from app.auth.settings import AuthSettings
from app.core.config import RateLimitSettings
from app.core.ratelimit import RateLimiter, create_redis
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import RoleEnv
from tests.identity.kc import REALM, Browser, Env, TestUser

ORIGIN = "http://127.0.0.1:18080"
API = "/api/v1/auth"
SESSION, FLOW = "at_session", "at_flow"  # unprefixed: the test origin is plain-http loopback


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
            }
        )
        client = create_redis(redis_url)
        engine = role_env.engine("app")
        runtime = AuthRuntime.build(settings, client, engine, namespace=f"kc{id(self)}")
        limiter = RateLimiter(client, namespace=f"kc{id(self)}")
        app = create_app(limiter, engine, RateLimitSettings(), runtime)
        self.api = TestClient(app, base_url=ORIGIN, follow_redirects=False)
        self.browser = Browser(env)

    def close(self) -> None:
        self.api.close()
        self.browser.close()

    def rows(self, sql: str) -> list[tuple[Any, ...]]:
        with self.role_env.admin_engine().connect() as c:
            return [tuple(r) for r in c.execute(text(sql))]

    def at_keycloak(self, url: str, user: TestUser | None) -> str:
        """Follow the authorization URL in the scripted browser; sign in when asked. Returns
        the callback URL Keycloak redirects to."""
        self.browser._last = f"{ORIGIN}{API}/callback"
        page = self.browser._settle(self.browser.http.get(url), self.browser._last)
        if page.location is None:
            assert user is not None
            page = self.browser.submit(
                page, {"username": user.email, "password": user.password, "credentialId": ""}
            )
        assert page.location and page.location.startswith(f"{ORIGIN}{API}/callback"), page.summary
        return page.location

    def sign_in(self, user: TestUser, return_to: str = "/app") -> httpx.Response:
        start = self.api.get(f"{API}/login", params={"return_to": return_to})
        assert start.status_code == 302, start.text
        callback = self.at_keycloak(start.headers["location"], user)
        done: httpx.Response = self.api.get(callback)
        return done
