"""F2-T02 / AC-TOK-01..08 and AC-AUTH settings: token validation without a network.

Every rejection test builds a token that is valid except for exactly one property and asserts
the specific rejection reason, so removing any single check makes at least one test fail."""

import logging
from typing import Any

import pytest
from app.auth.errors import IdentityProviderUnavailable, TokenInvalid, TokenRejection
from app.auth.settings import AuthSettings
from app.auth.tokens import JwksCache, TokenValidator
from tests.auth.fake_idp import DROP, ISSUER, NOW, Clock, FakeIdp


def settings(**extra: Any) -> AuthSettings:
    return AuthSettings.model_validate({"AUTH_OIDC_ISSUER": ISSUER, **extra})


class Rig:
    def __init__(self, **extra: Any) -> None:
        self.idp = FakeIdp()
        self.clock = Clock()
        self.mono = Clock(1000.0)
        self.settings = settings(**extra)
        self.cache = JwksCache(
            self.idp.fetch,
            ttl_seconds=self.settings.jwks_cache_seconds,
            min_refresh_seconds=self.settings.jwks_min_refresh_seconds,
            monotonic=self.mono,
        )
        self.validator = TokenValidator(self.settings, self.cache, clock=self.clock)


@pytest.fixture
def rig() -> Rig:
    return Rig()


def reject(rig: Rig, token: object) -> TokenRejection:
    with pytest.raises(TokenInvalid) as caught:
        rig.validator.validate(token)
    assert caught.value.status == 401 and caught.value.code == "AUTH_TOKEN_INVALID"
    return caught.value.reason


# AC-TOK-01
@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_valid_token_is_accepted_and_exposes_only_identity_fields(rig: Rig, algorithm: str) -> None:
    kid = "rsa-1" if algorithm == "RS256" else "ec-1"
    verified = rig.validator.validate(rig.idp.token(kid=kid, algorithm=algorithm))
    assert verified.subject.startswith("7b2f0c1e")
    assert (verified.session_id, verified.client_id) == (
        "5d1c5b7e-0f0c-4f5a-8f0a-9b0c1d2e3f40",
        "at-mobile",
    )
    assert verified.acr == "loa1" and verified.email_verified is True
    assert not hasattr(verified, "roles") and not hasattr(verified, "tenant_id")


def test_authorization_claims_in_the_token_are_never_surfaced(rig: Rig) -> None:
    verified = rig.validator.validate(
        rig.idp.token(tenant_id="t", roles=["OWNER"], realm_access={"roles": ["admin"]})
    )
    assert "OWNER" not in repr(verified) and "admin" not in repr(verified)


# AC-TOK-02
def test_alg_none_is_rejected(rig: Rig) -> None:
    assert reject(rig, rig.idp.unsigned()) is TokenRejection.ALGORITHM


def test_hmac_signed_with_the_public_key_is_rejected_before_key_use(rig: Rig) -> None:
    assert reject(rig, rig.idp.hmac_with_public_key()) is TokenRejection.ALGORITHM


@pytest.mark.parametrize("algorithm", ["HS256", "HS512", "RS512", "PS256", "ES512", "EdDSA"])
def test_algorithms_outside_the_allowlist_are_rejected(rig: Rig, algorithm: str) -> None:
    import base64
    import json

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": algorithm, "kid": "rsa-1"}).encode())
    body = b64(json.dumps(rig.idp.claims()).encode())
    assert reject(rig, f"{header}.{body}.{b64(b'x' * 32)}") is TokenRejection.ALGORITHM


def test_tampered_payload_and_foreign_signature_are_rejected(rig: Rig) -> None:
    good = rig.idp.token().split(".")
    forged = rig.idp.token(sub="someone-else").split(".")
    assert reject(rig, ".".join([good[0], forged[1], good[2]])) is TokenRejection.SIGNATURE
    other = FakeIdp()
    assert reject(rig, other.token()) is TokenRejection.SIGNATURE  # same kid, different key


def test_algorithm_and_key_type_must_match(rig: Rig) -> None:
    # ES256 header pointing at an RSA key id: the key cannot verify an ES256 signature
    token = rig.idp.token(kid="ec-1", algorithm="ES256")
    header_swapped = rig.idp.token(kid="ec-1", algorithm="ES256", headers={"kid": "rsa-1"})
    assert rig.validator.validate(token)
    assert reject(rig, header_swapped) is TokenRejection.SIGNATURE


# AC-TOK-03: each token is valid except one property
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://auth.test.invalid/realms/autotramita-prod"}, TokenRejection.ISSUER),
        ({"iss": DROP}, TokenRejection.ISSUER),
        ({"aud": ["account"]}, TokenRejection.AUDIENCE),
        ({"aud": "at-web"}, TokenRejection.AUDIENCE),
        ({"aud": DROP}, TokenRejection.AUDIENCE),
        ({"azp": "at-web"}, TokenRejection.AUTHORIZED_PARTY),
        ({"azp": DROP}, TokenRejection.AUTHORIZED_PARTY),
        ({"typ": "ID"}, TokenRejection.TOKEN_TYPE),
        ({"typ": "Refresh"}, TokenRejection.TOKEN_TYPE),
        ({"typ": DROP}, TokenRejection.TOKEN_TYPE),
        ({"sub": DROP}, TokenRejection.MISSING_CLAIM),
        ({"sub": ""}, TokenRejection.MISSING_CLAIM),
        ({"sid": DROP}, TokenRejection.MISSING_CLAIM),
        ({"exp": DROP}, TokenRejection.MISSING_CLAIM),
        ({"iat": DROP}, TokenRejection.MISSING_CLAIM),
        ({"exp": "soon"}, TokenRejection.MISSING_CLAIM),
    ],
)
def test_each_claim_check_rejects_exactly_its_own_violation(
    rig: Rig, overrides: dict[str, Any], reason: TokenRejection
) -> None:
    assert reject(rig, rig.idp.token(**overrides)) is reason


def test_an_id_token_shaped_token_is_not_an_access_token(rig: Rig) -> None:
    id_token = rig.idp.token(typ="ID", aud="at-web", azp="at-web")
    assert reject(rig, id_token) is TokenRejection.AUDIENCE  # wrong audience and type


# AC-TOK-04: boundaries with the 30 s tolerance, both directions
def test_expiry_boundary_with_leeway(rig: Rig) -> None:
    token = rig.idp.token()  # exp = NOW + 290
    rig.clock.now = NOW + 290 + 29
    assert rig.validator.validate(token)
    rig.clock.now = NOW + 290 + 30
    assert reject(rig, token) is TokenRejection.EXPIRED


def test_not_before_and_future_issue_time_boundaries(rig: Rig) -> None:
    ahead = rig.idp.token(nbf=int(NOW) + 30)
    assert rig.validator.validate(ahead)  # exactly at the tolerance
    assert reject(rig, rig.idp.token(nbf=int(NOW) + 31)) is TokenRejection.NOT_YET_VALID
    assert rig.validator.validate(rig.idp.token(iat=int(NOW) + 30, exp=int(NOW) + 300))
    future = rig.idp.token(iat=int(NOW) + 31, exp=int(NOW) + 300)
    assert reject(rig, future) is TokenRejection.NOT_YET_VALID


def test_implausibly_long_lifetime_is_rejected(rig: Rig) -> None:
    long_lived = rig.idp.token(iat=int(NOW) - 10, exp=int(NOW) + 3600)
    assert reject(rig, long_lived) is TokenRejection.LIFETIME


# AC-TOK-05: key handling
def test_unknown_kid_triggers_one_refetch_per_interval_then_is_rejected(rig: Rig) -> None:
    rig.validator.validate(rig.idp.token())  # warms the cache: 1 fetch
    assert rig.idp.fetches == 1
    rig.idp.add_rsa("rsa-2")
    token = rig.idp.token(kid="rsa-2")
    rig.idp.remove("rsa-2")  # the provider no longer publishes it
    assert reject(rig, token) is TokenRejection.UNKNOWN_KEY  # refused to refetch: too soon
    assert rig.idp.fetches == 1
    rig.mono.now += 61
    assert reject(rig, token) is TokenRejection.UNKNOWN_KEY  # allowed one refetch, still unknown
    assert rig.idp.fetches == 2
    for _ in range(5):  # a flood of unknown kids cannot hammer the provider
        reject(rig, token)
    assert rig.idp.fetches == 2


def test_rotation_new_key_is_picked_up_and_old_tokens_still_validate(rig: Rig) -> None:
    old = rig.idp.token()
    rig.validator.validate(old)
    rig.idp.add_rsa("rsa-2")
    rig.mono.now += 61
    assert rig.validator.validate(rig.idp.token(kid="rsa-2"))
    assert rig.validator.validate(old)


def test_missing_kid_is_rejected(rig: Rig) -> None:
    import jwt

    token = jwt.encode(rig.idp.claims(), rig.idp.rsa["rsa-1"], algorithm="RS256")
    assert reject(rig, token) is TokenRejection.UNKNOWN_KEY


def test_provider_down_without_cache_fails_closed_with_503(rig: Rig) -> None:
    rig.idp.down = True
    with pytest.raises(IdentityProviderUnavailable) as caught:
        rig.validator.validate(rig.idp.token())
    assert caught.value.status == 503 and caught.value.code == "IDENTITY_PROVIDER_UNAVAILABLE"
    assert caught.value.headers.get("Retry-After") == "5"


def test_provider_down_with_cached_key_keeps_working_but_unknown_key_fails_closed(
    rig: Rig,
) -> None:
    token = rig.idp.token()
    rig.validator.validate(token)
    rig.idp.down = True
    rig.mono.now += 700  # cache expired, refresh fails
    assert rig.validator.validate(token)
    rig.idp.add_rsa("rsa-2")
    other = rig.idp.token(kid="rsa-2")
    rig.mono.now += 61
    with pytest.raises(IdentityProviderUnavailable):
        rig.validator.validate(other)


def test_only_signing_rsa_and_ec_keys_are_loaded() -> None:
    idp = FakeIdp()
    document = idp.jwks()
    document["keys"].append({"kty": "oct", "kid": "sym", "k": "AAAA", "use": "sig"})
    document["keys"].append({**document["keys"][0], "kid": "enc", "use": "enc"})
    cache = JwksCache(lambda: document, ttl_seconds=600, min_refresh_seconds=60)
    cache.key("rsa-1")
    for forbidden in ("sym", "enc"):
        with pytest.raises(TokenInvalid):
            cache.key(forbidden)


# AC-TOK-06: nothing sensitive in logs or exceptions
def test_tokens_never_reach_logs_or_exception_text(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bad = rig.idp.token(aud=["account"])
    signature = bad.split(".")[2]
    with pytest.raises(TokenInvalid) as caught:
        rig.validator.validate(bad)
    text = caplog.text + repr(caught.value) + str(caught.value) + str(caught.value.detail)
    assert bad not in text and signature not in text and "person@example.test" not in text
    reasons = [getattr(r, "fields", {}).get("reason") for r in caplog.records]
    assert reasons == ["audience"]  # the reason is logged, nothing else
    assert caught.value.__cause__ is None


# AC-TOK-08
@pytest.mark.parametrize(
    "garbage",
    ["", "   ", "abc", "a.b", "a.b.c", "....", "%%%.%%%.%%%", "é.é.é", None, 123, b"a.b.c", [], {}],
)
def test_malformed_input_is_a_401_never_a_server_error(rig: Rig, garbage: object) -> None:
    assert reject(rig, garbage) in {TokenRejection.MALFORMED, TokenRejection.ALGORITHM}


def test_oversized_token_is_rejected_before_parsing(rig: Rig) -> None:
    assert reject(rig, "a" * 20000) is TokenRejection.TOO_LARGE
    big_claim = rig.idp.token(blob="x" * 9000)
    assert reject(rig, big_claim) is TokenRejection.TOO_LARGE


def test_invalid_token_response_headers_and_shape(rig: Rig) -> None:
    with pytest.raises(TokenInvalid) as caught:
        rig.validator.validate("x")
    assert caught.value.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


# settings
def test_settings_defaults_match_accepted_decisions() -> None:
    s = settings()
    assert (s.web_idle_minutes, s.web_absolute_hours) == (30, 12)
    assert (s.admin_idle_minutes, s.admin_absolute_hours) == (15, 8)
    assert (s.mobile_idle_days, s.mobile_absolute_days) == (7, 30)
    assert (s.step_up_window_minutes, s.max_sessions_per_user, s.leeway_seconds) == (10, 10, 30)
    assert (s.login_per_min_ip, s.callback_per_min_ip, s.recovery_per_hour_ip) == (20, 30, 10)
    assert s.audience == "at-api" and s.authorized_parties == {"at-mobile"}
    assert s.jwks_endpoint == f"{ISSUER}/protocol/openid-connect/certs"


@pytest.mark.parametrize(
    "bad",
    [
        {"AUTH_OIDC_ISSUER": "http://auth.example.test/realms/x"},
        {"AUTH_OIDC_ISSUER": "ftp://auth.example.test/realms/x"},
        {"AUTH_OIDC_ISSUER": ""},
        {"AUTH_OIDC_JWKS_URL": "http://auth.example.test/certs"},
        {"AUTH_OIDC_ALLOWED_AZP": " , "},
        {"AUTH_TOKEN_LEEWAY_SECONDS": 600},
        {"AUTH_ADMIN_IDLE_MINUTES": 45},
        {"AUTH_ADMIN_ABSOLUTE_HOURS": 24},
        {"AUTH_MAX_SESSIONS_PER_USER": 0},
    ],
)
def test_insecure_or_inconsistent_settings_are_rejected(bad: dict[str, Any]) -> None:
    values = {"AUTH_OIDC_ISSUER": ISSUER, **bad}
    with pytest.raises(ValueError):
        AuthSettings.model_validate(values)


def test_loopback_http_issuer_is_allowed_for_the_test_keycloak_only() -> None:
    assert settings(AUTH_OIDC_ISSUER="http://127.0.0.1:18081/realms/x").issuer.startswith("http://")


def test_missing_issuer_fails_without_echoing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.auth.settings import get_auth_settings

    monkeypatch.delenv("AUTH_OIDC_ISSUER", raising=False)
    get_auth_settings.cache_clear()
    with pytest.raises(ValueError, match=r"validation error"):
        get_auth_settings()
    get_auth_settings.cache_clear()
