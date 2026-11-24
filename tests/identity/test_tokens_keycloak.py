"""F2-T02: the token validator against real Keycloak tokens (AC-TOK-01, AC-KC-05 follow-up).
Runs only in the ``keycloak`` CI job."""

import time

import httpx
import pytest
from app.auth.errors import TokenInvalid, TokenRejection
from app.auth.settings import AuthSettings
from app.auth.tokens import JwksCache, TokenValidator, http_jwks_fetcher
from tests.identity.kc import MOBILE_REDIRECT, REALM, Admin, Browser, Env, pkce_pair

pytestmark = pytest.mark.keycloak


def _validator(env: Env, *, azp: str = "at-mobile", clock: object = time.time) -> TokenValidator:
    settings = AuthSettings.model_validate(
        {
            "AUTH_OIDC_ISSUER": f"{env.base_url}/realms/{REALM}",
            "AUTH_OIDC_ALLOWED_AZP": azp,
            "AUTH_JWKS_MIN_REFRESH_SECONDS": 0,
        }
    )
    cache = JwksCache(
        http_jwks_fetcher(settings.jwks_endpoint, settings.jwks_timeout_seconds),
        ttl_seconds=settings.jwks_cache_seconds,
        min_refresh_seconds=0,
    )
    return TokenValidator(settings, cache, clock=clock)  # type: ignore[arg-type]


def _access_token(env: Env, admin: Admin, client: str = "at-mobile") -> tuple[str, str]:
    user = admin.create_user()
    b = Browser(env)
    verifier, challenge = pkce_pair()
    redirect = (
        MOBILE_REDIRECT if client == "at-mobile" else "http://127.0.0.1:18080/api/v1/auth/callback"
    )
    page = b.login(user, client_id=client, redirect_uri=redirect, challenge=challenge)
    tokens = b.token(client, page.require_code(), redirect, verifier=verifier)
    b.close()
    return str(tokens["access_token"]), user.id


def test_real_access_token_validates_and_matches_the_user(env: Env, admin: Admin) -> None:
    token, user_id = _access_token(env, admin)
    verified = _validator(env).validate(token)
    assert verified.subject == user_id
    assert verified.client_id == "at-mobile" and verified.session_id
    assert verified.email and verified.email_verified is True


def test_token_of_another_client_or_in_the_future_or_past_is_rejected(
    env: Env, admin: Admin
) -> None:
    token, _ = _access_token(env, admin)
    with pytest.raises(TokenInvalid) as wrong_azp:
        _validator(env, azp="at-other").validate(token)
    assert wrong_azp.value.reason is TokenRejection.AUTHORIZED_PARTY
    with pytest.raises(TokenInvalid) as expired:
        _validator(env, clock=lambda: time.time() + 3600).validate(token)
    assert expired.value.reason is TokenRejection.EXPIRED
    web_token, _ = _access_token(env, admin, client="at-web")
    with pytest.raises(TokenInvalid) as web:
        _validator(env).validate(web_token)  # web tokens are never accepted as bearer here
    assert web.value.reason is TokenRejection.AUTHORIZED_PARTY


def test_tampered_real_token_is_rejected(env: Env, admin: Admin) -> None:
    token, _ = _access_token(env, admin)
    head, body, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    with pytest.raises(TokenInvalid) as caught:
        _validator(env).validate(f"{head}.{body}.{flipped}")
    assert caught.value.reason is TokenRejection.SIGNATURE


def test_rotation_new_realm_key_is_picked_up_without_restart(env: Env, admin: Admin) -> None:
    validator = _validator(env)
    old, _ = _access_token(env, admin)
    assert validator.validate(old)
    created = admin.master(
        "POST",
        "/components",
        json={
            "name": "rsa-t02-rotated",
            "providerId": "rsa-generated",
            "providerType": "org.keycloak.keys.KeyProvider",
            "config": {
                "priority": ["300"],
                "enabled": ["true"],
                "active": ["true"],
                "keySize": ["2048"],
            },
        },
    )
    assert created.status_code == 201, created.text
    component = created.headers["Location"].rsplit("/", 1)[1]
    try:
        new, _ = _access_token(env, admin)
        assert validator.validate(new)  # unknown kid -> refetch -> accepted
        assert validator.validate(old)  # the previous key is still published
    finally:
        admin.master("DELETE", f"/components/{component}")
    assert (
        httpx.get(f"{env.base_url}/realms/{REALM}/protocol/openid-connect/certs").status_code == 200
    )
