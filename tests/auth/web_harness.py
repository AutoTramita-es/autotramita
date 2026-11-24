"""Test harness for the web sign-in (F2-T06): the real application on real PostgreSQL 16 and
Redis 7, with a fake identity provider (local keys, a code-exchange double that also verifies
PKCE). Used by the API tests and, with a different exchanger, by the Keycloak tests."""

from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from app.api.app import create_app
from app.auth.errors import AuthCallbackRejected
from app.auth.runtime import AuthRuntime
from app.auth.sessions.models import SessionPolicy
from app.auth.settings import AuthLimitSettings, AuthSettings
from app.auth.tokens import IdTokenValidator, JwksCache, LogoutTokenValidator
from app.auth.web.oidc_flow import FlowStore, JtiStore, OidcEndpoints
from app.core.config import RateLimitSettings
from app.core.db import create_session_factory
from app.core.ratelimit import RateLimiter, create_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.auth.fake_idp import ISSUER, NOW, Clock, FakeIdp
from tests.conftest import RoleEnv

WEB_HOST = "autotramita.example"
ADMIN_HOST = "admin.autotramita.example"
CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"
SUBJECT = "7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11"
SID = "5d1c5b7e-0f0c-4f5a-8f0a-9b0c1d2e3f40"
SESSION_COOKIE = "__Host-at_session"
FLOW_COOKIE = "__Host-at_flow"


class FakeExchanger:
    """Stands in for Keycloak's token endpoint: hands out the prepared ID token once per code
    and enforces PKCE (S256 of the verifier equals the challenge) and the redirect URI."""

    def __init__(self) -> None:
        self.issued: dict[str, tuple[str, str, str]] = {}

    def issue(self, token: str, *, challenge: str, redirect_uri: str) -> str:
        code = uuid.uuid4().hex
        self.issued[code] = (token, challenge, redirect_uri)
        return code

    def __call__(self, *, code: str, redirect_uri: str, verifier: str) -> str:
        entry = self.issued.pop(code, None)
        if entry is None:
            raise AuthCallbackRejected()
        token, challenge, expected = entry
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        if digest.rstrip(b"=").decode() != challenge or redirect_uri != expected:
            raise AuthCallbackRejected()
        return token


@dataclass
class Web:
    env: RoleEnv
    idp: FakeIdp
    exchanger: FakeExchanger
    runtime: AuthRuntime
    app: FastAPI
    settings: AuthSettings
    clock: Clock
    clients: list[TestClient] = field(default_factory=list)

    def client(self, host: str = WEB_HOST, user_agent: str = CHROME, **kw: Any) -> TestClient:
        c = TestClient(
            self.app,
            base_url=f"https://{host}",
            follow_redirects=False,
            headers={"user-agent": user_agent},
            **kw,
        )
        self.clients.append(c)
        return c

    def start(self, client: TestClient, return_to: str | None = None) -> dict[str, str]:
        params = {} if return_to is None else {"return_to": return_to}
        response = client.get("/api/v1/auth/login", params=params)
        assert response.status_code == 302, response.text
        query = parse_qs(urlparse(response.headers["location"]).query)
        return {k: v[0] for k, v in query.items()}

    def code_for(
        self,
        query: dict[str, str],
        *,
        sub: str = SUBJECT,
        sid: str = SID,
        email: str = "person@example.test",
        verified: bool = True,
        acr: str = "loa1",
        nonce: str | None = None,
        **claims: Any,
    ) -> str:
        token = self.idp.sign(
            self.idp.id_claims(
                nonce or query["nonce"],
                sub=sub,
                sid=sid,
                email=email,
                email_verified=verified,
                acr=acr,
                **claims,
            )
        )
        return self.exchanger.issue(
            token, challenge=query["code_challenge"], redirect_uri=query["redirect_uri"]
        )

    def sign_in(
        self, client: TestClient, *, return_to: str | None = None, **identity: Any
    ) -> httpx.Response:
        query = self.start(client, return_to)
        code = self.code_for(query, **identity)
        callback: httpx.Response = client.get(
            "/api/v1/auth/callback", params={"code": code, "state": query["state"]}
        )
        return callback

    def rows(self, sql: str, **params: Any) -> list[tuple[Any, ...]]:
        with self.env.admin_engine().connect() as c:
            return [tuple(r) for r in c.execute(text(sql), params)]

    def close(self) -> None:
        for c in self.clients:
            c.close()


def build_web(
    env: RoleEnv,
    redis_url: str,
    *,
    limits: AuthLimitSettings | None = None,
    redis_for_limiter: str | None = None,
    **settings_overrides: Any,
) -> Web:
    values: dict[str, Any] = {
        "AUTH_OIDC_ISSUER": ISSUER,
        "AUTH_WEB_ORIGIN": f"https://{WEB_HOST}",
        "AUTH_ADMIN_ORIGIN": f"https://{ADMIN_HOST}",
        "AUTH_WEB_CLIENT_SECRET": "test-secret-not-real",
        **settings_overrides,
    }
    settings = AuthSettings.model_validate(values)
    idp, clock, exchanger = FakeIdp(), Clock(NOW), FakeExchanger()
    cache = JwksCache(idp.fetch, ttl_seconds=600, min_refresh_seconds=0)
    namespace = f"t{uuid.uuid4().hex[:10]}"
    client = create_redis(redis_url)
    runtime = AuthRuntime(
        settings=settings,
        id_validator=IdTokenValidator(settings, cache, clock=clock),
        logout_validator=LogoutTokenValidator(settings, cache, clock=clock),
        flows=FlowStore(client, namespace=namespace, ttl_seconds=settings.flow_ttl_seconds),
        jti=JtiStore(client, namespace=namespace),
        exchanger=exchanger,
        endpoints=OidcEndpoints(settings),
        factory=create_session_factory(env.engine("app")),
        policy=SessionPolicy.from_settings(settings),
        clock=clock,
    )
    limiter = RateLimiter(create_redis(redis_for_limiter or redis_url), namespace=namespace)
    app = create_app(limiter, env.engine("app"), RateLimitSettings(), runtime, limits)
    return Web(env, idp, exchanger, runtime, app, settings, clock)
