"""OpenID Connect authorization-code flow with PKCE, server side (F2-T06, D03, D25).

* ``FlowStore`` keeps ``state`` -> nonce, PKCE verifier, binding and purpose in Redis for a few
  minutes and hands each entry out exactly once (``GETDEL``): a replayed callback finds nothing.
* The browser also receives a random binding in a short-lived cookie. Without it a callback
  produced by somebody else's sign-in (login CSRF, session fixation) is refused.
* Tokens are exchanged here, read once and discarded; nothing of them reaches the browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import redis
from app.auth.errors import AuthCallbackRejected, IdentityProviderUnavailable
from app.auth.settings import AuthSettings
from app.core.errors import ServiceUnavailable

logger = logging.getLogger(__name__)
_STATE_FORMAT_LENGTH = 32


def new_state() -> str:
    return secrets.token_urlsafe(24)  # 32 url-safe characters


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def new_binder() -> str:
    return secrets.token_urlsafe(24)


def binder_digest(binder: str) -> str:
    return hashlib.sha256(binder.encode()).hexdigest()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def _unavailable() -> ServiceUnavailable:
    return ServiceUnavailable(
        "Sign-in state is temporarily unavailable.",
        code="AUTH_STATE_UNAVAILABLE",
        headers={"Retry-After": "5"},
    )


class FlowStore:
    def __init__(self, client: redis.Redis, *, namespace: str, ttl_seconds: int) -> None:
        self._client, self._namespace, self._ttl = client, namespace, ttl_seconds

    def _key(self, kind: str, value: str) -> str:
        return f"auth:{self._namespace}:{kind}:{hashlib.sha256(value.encode()).hexdigest()[:40]}"

    def put(self, state: str, data: dict[str, Any]) -> None:
        try:
            self._client.set(self._key("flow", state), json.dumps(data), ex=self._ttl)
        except redis.RedisError:
            logger.error("auth flow store unavailable")
            raise _unavailable() from None

    def take(self, state: object) -> dict[str, Any] | None:
        """Return the stored flow and delete it atomically, or ``None`` (unknown, used, expired)."""
        if not isinstance(state, str) or len(state) != _STATE_FORMAT_LENGTH:
            return None
        try:
            raw = self._client.getdel(self._key("flow", state))
        except redis.RedisError:
            logger.error("auth flow store unavailable")
            raise _unavailable() from None
        if not raw:
            return None
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None


class JtiStore:
    """Remembers back-channel ``logout_token`` ids so each is accepted once (D25)."""

    def __init__(self, client: redis.Redis, *, namespace: str) -> None:
        self._client, self._namespace = client, namespace

    def first_use(self, jti: str, *, ttl_seconds: int) -> bool:
        key = f"auth:{self._namespace}:jti:{hashlib.sha256(jti.encode()).hexdigest()[:40]}"
        try:
            return bool(self._client.set(key, "1", nx=True, ex=max(ttl_seconds, 1)))
        except redis.RedisError:
            logger.error("auth jti store unavailable")
            raise _unavailable() from None


class TokenExchanger(Protocol):
    def __call__(self, *, code: str, redirect_uri: str, verifier: str) -> str:
        """Exchange the code and return the raw ID token."""
        ...


def http_token_exchanger(settings: AuthSettings) -> TokenExchanger:
    endpoint = f"{settings.issuer}/protocol/openid-connect/token"
    secret = settings.web_client_secret

    def exchange(*, code: str, redirect_uri: str, verifier: str) -> str:
        if secret is None:
            raise IdentityProviderUnavailable()
        try:
            response = httpx.post(
                endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.web_client_id,
                    "client_secret": secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
                timeout=settings.token_endpoint_timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise IdentityProviderUnavailable() from None
        if response.status_code >= 500:
            raise IdentityProviderUnavailable()
        if response.status_code != 200:
            raise AuthCallbackRejected()
        try:
            body = response.json()
        except ValueError:
            raise AuthCallbackRejected() from None
        token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise AuthCallbackRejected()
        return token

    return exchange


class OidcEndpoints:
    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        challenge: str,
        acr_values: str | None = None,
        prompt: str | None = None,
        max_age: int | None = None,
        kc_action: str | None = None,
    ) -> str:
        params: dict[str, str] = {
            "client_id": self._settings.web_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if acr_values:
            params["acr_values"] = acr_values
        if prompt:
            params["prompt"] = prompt
        if max_age is not None:
            params["max_age"] = str(max_age)
        if kc_action:  # application-initiated action (D37): password change, second factor
            params["kc_action"] = kc_action
        return f"{self._settings.issuer}/protocol/openid-connect/auth?{urlencode(params)}"

    def end_session_url(self, post_logout_redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._settings.web_client_id,
                "post_logout_redirect_uri": post_logout_redirect_uri,
            }
        )
        return f"{self._settings.issuer}/protocol/openid-connect/logout?{query}"


Clock = Callable[[], float]
