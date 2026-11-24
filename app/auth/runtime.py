"""Authentication runtime (F2-T06): the collaborators the web sign-in handlers need, built once
and attached to the application. Everything is injectable so tests use a fake identity
provider and real PostgreSQL/Redis, and the contract can be exported without any of it."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from ipaddress import IPv4Network, IPv6Network
from urllib.parse import urlsplit

import redis
from app.auth.errors import AuthNotConfigured
from app.auth.membership import DenyAllAuthorizer, MembershipAuthorizer
from app.auth.sessions.models import ClientType, SessionPolicy
from app.auth.settings import AuthSettings
from app.auth.tokens import (
    IdTokenValidator,
    JwksCache,
    LogoutTokenValidator,
    TokenValidator,
    http_jwks_fetcher,
)
from app.auth.web.oidc_flow import (
    FlowStore,
    JtiStore,
    OidcEndpoints,
    TokenExchanger,
    http_token_exchanger,
)
from app.core.db import create_session_factory
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

IPNetwork = IPv4Network | IPv6Network


@dataclass
class AuthRuntime:
    settings: AuthSettings
    access_validator: TokenValidator
    id_validator: IdTokenValidator
    logout_validator: LogoutTokenValidator
    flows: FlowStore
    jti: JtiStore
    exchanger: TokenExchanger
    endpoints: OidcEndpoints
    factory: sessionmaker[Session]
    policy: SessionPolicy
    trusted_proxies: Sequence[IPNetwork] = ()
    # F2 ships no memberships: the only production authorizer says no to everything (D18).
    membership: MembershipAuthorizer = field(default_factory=DenyAllAuthorizer)
    clock: Callable[[], float] = field(default=time.time)

    @classmethod
    def build(
        cls,
        settings: AuthSettings,
        redis_client: redis.Redis,
        engine: Engine,
        *,
        namespace: str,
        trusted_proxies: Sequence[IPNetwork] = (),
    ) -> AuthRuntime:
        jwks = JwksCache(
            http_jwks_fetcher(settings.jwks_endpoint, settings.jwks_timeout_seconds),
            ttl_seconds=settings.jwks_cache_seconds,
            min_refresh_seconds=settings.jwks_min_refresh_seconds,
        )
        return cls(
            settings=settings,
            access_validator=TokenValidator(settings, jwks),
            id_validator=IdTokenValidator(settings, jwks),
            logout_validator=LogoutTokenValidator(settings, jwks),
            flows=FlowStore(
                redis_client, namespace=namespace, ttl_seconds=settings.flow_ttl_seconds
            ),
            jti=JtiStore(redis_client, namespace=namespace),
            exchanger=http_token_exchanger(settings),
            endpoints=OidcEndpoints(settings),
            factory=create_session_factory(engine),
            policy=SessionPolicy.from_settings(settings),
            trusted_proxies=trusted_proxies,
        )

    # --- origins: which of our sites a request belongs to --------------------------------------
    @property
    def origins(self) -> frozenset[str]:
        found = {self.settings.web_origin, self.settings.admin_origin}
        return frozenset(origin for origin in found if origin)

    def site_for(self, request: Request) -> tuple[str, ClientType]:
        """Match the Host header against the configured origins; never trust a free-form one."""
        host = request.headers.get("host", "")
        for origin, client in (
            (self.settings.web_origin, ClientType.WEB),
            (self.settings.admin_origin, ClientType.ADMIN_WEB),
        ):
            if origin and urlsplit(origin).netloc == host:
                return origin, client
        raise AuthNotConfigured("This host does not serve sign-in.", code="UNKNOWN_ORIGIN")

    def callback_uri(self, origin: str) -> str:
        return f"{origin}/api/v1/auth/callback"


def runtime_of(request: Request) -> AuthRuntime:
    runtime: AuthRuntime | None = request.app.state.auth
    if runtime is None or runtime.settings.web_client_secret is None:
        raise AuthNotConfigured()
    return runtime
