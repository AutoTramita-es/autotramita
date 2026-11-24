"""F2-T06 unit tests (no infrastructure): ID token and logout token validation, return_to
handling, CSRF tokens, cookies and the step-up freshness check."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.auth.errors import CsrfInvalid, StepUpRequired, TokenInvalid, TokenRejection
from app.auth.sessions.models import AuthLevel, ClientType, UserSession
from app.auth.settings import AuthSettings
from app.auth.tokens import IdTokenValidator, JwksCache, LogoutTokenValidator
from app.auth.web import cookies
from app.auth.web.csrf import csrf_token, verify_csrf
from app.auth.web.redirects import safe_return_to
from app.auth.web.stepup import (
    StepUpPurpose,
    authorization_params,
    level_from_acr,
    require_step_up,
)
from starlette.requests import Request
from starlette.responses import Response
from tests.auth.fake_idp import DROP, ISSUER, NOW, Clock, FakeIdp

NONCE = "n" * 32
SETTINGS = AuthSettings.model_validate(
    {
        "AUTH_OIDC_ISSUER": ISSUER,
        "AUTH_WEB_ORIGIN": "https://autotramita.example",
        "AUTH_WEB_CLIENT_SECRET": "x",
    }
)


class Rig:
    def __init__(self) -> None:
        self.idp = FakeIdp()
        self.clock = Clock()
        cache = JwksCache(
            self.idp.fetch, ttl_seconds=600, min_refresh_seconds=60, monotonic=Clock(1000.0)
        )
        self.ids = IdTokenValidator(SETTINGS, cache, clock=self.clock)
        self.logout = LogoutTokenValidator(SETTINGS, cache, clock=self.clock)

    def id(self, **overrides: Any) -> str:
        nonce = overrides.pop("nonce", NONCE)
        return self.idp.sign(self.idp.id_claims(nonce, **overrides))

    def lo(self, **overrides: Any) -> str:
        return self.idp.sign(self.idp.logout_claims(**overrides))


@pytest.fixture
def rig() -> Rig:
    return Rig()


# --- ID token -----------------------------------------------------------------------------------
def test_valid_id_token_yields_identity_facts_only(rig: Rig) -> None:
    got = rig.ids.validate(rig.id(), client_id="at-web", nonce=NONCE)
    assert got.subject.startswith("7b2f0c1e") and got.session_id and got.acr == "loa1"
    assert got.email == "person@example.test" and got.email_verified is True


def reason_of(validator: Any, token: str, **kw: Any) -> TokenRejection:
    with pytest.raises(TokenInvalid) as caught:
        validator.validate(token, **kw)
    return caught.value.reason


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"nonce": "other-nonce-value"}, TokenRejection.NONCE),
        ({"nonce": DROP}, TokenRejection.NONCE),
        ({"aud": "at-mobile", "azp": "at-mobile"}, TokenRejection.AUDIENCE),
        ({"aud": ["at-web", "account"], "azp": "at-mobile"}, TokenRejection.AUTHORIZED_PARTY),
        ({"aud": ["at-web", "account"], "azp": DROP}, TokenRejection.AUTHORIZED_PARTY),
        ({"typ": "Bearer"}, TokenRejection.TOKEN_TYPE),
        ({"typ": DROP}, TokenRejection.TOKEN_TYPE),
        ({"iss": "https://other.example/realms/x"}, TokenRejection.ISSUER),
        ({"sid": DROP}, TokenRejection.MISSING_CLAIM),
        ({"sub": ""}, TokenRejection.MISSING_CLAIM),
        ({"exp": DROP}, TokenRejection.MISSING_CLAIM),
        ({"exp": int(NOW) - 100, "iat": int(NOW) - 400}, TokenRejection.EXPIRED),
        ({"iat": int(NOW) + 100, "exp": int(NOW) + 300}, TokenRejection.NOT_YET_VALID),
        ({"iat": int(NOW) - 5, "exp": int(NOW) + 5000}, TokenRejection.LIFETIME),
    ],
)
def test_each_id_token_check_rejects_exactly_its_violation(
    rig: Rig, overrides: dict[str, Any], reason: TokenRejection
) -> None:
    assert reason_of(rig.ids, rig.id(**overrides), client_id="at-web", nonce=NONCE) is reason


def test_id_token_signature_and_algorithm_are_enforced(rig: Rig) -> None:
    assert reason_of(rig.ids, rig.idp.unsigned(), client_id="at-web", nonce=NONCE) is (
        TokenRejection.ALGORITHM)  # fmt: skip
    other = FakeIdp()
    forged = other.sign(other.id_claims(NONCE))
    assert reason_of(rig.ids, forged, client_id="at-web", nonce=NONCE) is TokenRejection.SIGNATURE
    assert reason_of(rig.ids, "", client_id="at-web", nonce=NONCE) is TokenRejection.MALFORMED


def test_an_access_token_is_not_an_id_token(rig: Rig) -> None:
    access = rig.idp.token(aud=["at-web"], azp="at-web", nonce=NONCE)
    assert reason_of(rig.ids, access, client_id="at-web", nonce=NONCE) is TokenRejection.TOKEN_TYPE


# --- logout token -------------------------------------------------------------------------------
def test_valid_logout_token(rig: Rig) -> None:
    got = rig.logout.validate(rig.lo(), client_id="at-web")
    assert got.subject.startswith("7b2f0c1e") and got.session_id and got.jti
    assert rig.logout.validate(rig.lo(sid=DROP), client_id="at-web").session_id is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://other.example/realms/x"}, TokenRejection.ISSUER),
        ({"aud": "at-mobile"}, TokenRejection.AUDIENCE),
        ({"events": DROP}, TokenRejection.EVENTS),
        ({"events": {"other-event": {}}}, TokenRejection.EVENTS),
        ({"nonce": "present"}, TokenRejection.NONCE),
        ({"jti": DROP}, TokenRejection.MISSING_CLAIM),
        ({"sub": DROP}, TokenRejection.MISSING_CLAIM),
        ({"sid": ""}, TokenRejection.MISSING_CLAIM),
        ({"iat": DROP}, TokenRejection.MISSING_CLAIM),
        ({"typ": "Bearer"}, TokenRejection.TOKEN_TYPE),
        ({"iat": int(NOW) - 4000, "exp": int(NOW) + 100}, TokenRejection.EXPIRED),
        ({"iat": int(NOW) + 300}, TokenRejection.NOT_YET_VALID),
        ({"exp": int(NOW) - 100}, TokenRejection.EXPIRED),
    ],
)
def test_each_logout_token_check_rejects_exactly_its_violation(
    rig: Rig, overrides: dict[str, Any], reason: TokenRejection
) -> None:
    assert reason_of(rig.logout, rig.lo(**overrides), client_id="at-web") is reason


# --- return_to ----------------------------------------------------------------------------------
@pytest.mark.parametrize("good", ["/", "/app", "/app/cases?x=1&y=2", "/a/b-c_d.e~f", "/%C3%B1"])
def test_same_site_paths_are_kept(good: str) -> None:
    assert safe_return_to(good) == good


@pytest.mark.parametrize(
    "bad",
    ["//evil.example", "///evil.example", "https://evil.example", "http://evil.example/",
     "evil.example", "javascript:alert(1)", "/\\evil.example", "/%5Cevil.example",
     "/%2F/evil.example", "/%252F/evil.example", "/%252F%252Fevil.example", "/a\r\nSet-Cookie: x",
     "/a%0d%0aSet-Cookie:%20x", "/a\x00b", "", None, 5, "/" + "a" * 600, "\\\\evil.example",
     "/x?next=https://evil.example/..//", " //evil.example"],
)  # fmt: skip
def test_everything_else_falls_back_to_the_root(bad: object) -> None:
    expected = (
        "/" if bad != "/x?next=https://evil.example/..//" else "/x?next=https://evil.example/..//"
    )
    assert safe_return_to(bad) == expected


def test_query_strings_that_merely_mention_urls_are_still_relative() -> None:
    assert safe_return_to("/x?next=https://evil.example/") == "/x?next=https://evil.example/"


# --- CSRF ---------------------------------------------------------------------------------------
def request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


SECRET = "A" * 43
ORIGINS = {"https://autotramita.example", "https://admin.autotramita.example"}


def test_csrf_token_is_derived_from_the_credential_and_changes_with_it() -> None:
    token = csrf_token(SECRET)
    assert token == csrf_token(SECRET) and len(token) == 43
    assert token != csrf_token("B" * 43) and SECRET not in token


@pytest.mark.parametrize(
    "headers",
    [
        {},  # nothing
        {"origin": "https://autotramita.example"},  # origin but no token
        {"x-csrf-token": "wrong", "origin": "https://autotramita.example"},
        {"x-csrf-token": "", "origin": "https://autotramita.example"},
        {"x-csrf-token": "{t}", "origin": "https://evil.example"},
        {"x-csrf-token": "{t}", "origin": "null"},
        {"x-csrf-token": "{t}"},  # token only: no proof of origin
        {"x-csrf-token": "{t}", "sec-fetch-site": "cross-site"},
        {"x-csrf-token": "{t}", "sec-fetch-site": "same-site"},
        {"x-csrf-token": "{t}", "sec-fetch-site": "none"},
        {"x-csrf-token": csrf_token("B" * 43), "origin": "https://autotramita.example"},
    ],
)
def test_csrf_rejects_missing_wrong_or_foreign_requests(headers: dict[str, str]) -> None:
    prepared = {k: v.replace("{t}", csrf_token(SECRET)) for k, v in headers.items()}
    with pytest.raises(CsrfInvalid) as caught:
        verify_csrf(request(prepared), SECRET, ORIGINS)
    assert (caught.value.status, caught.value.code) == (403, "CSRF_INVALID")


@pytest.mark.parametrize(
    "extra",
    [{"origin": "https://autotramita.example"}, {"origin": "https://admin.autotramita.example"},
     {"sec-fetch-site": "same-origin"}],
)  # fmt: skip
def test_csrf_accepts_token_with_own_origin_proof(extra: dict[str, str]) -> None:
    verify_csrf(request({"x-csrf-token": csrf_token(SECRET), **extra}), SECRET, ORIGINS)


# --- cookies ------------------------------------------------------------------------------------
def test_session_cookie_attributes() -> None:
    response = Response()
    cookies.set_session_cookie(response, SETTINGS, SECRET, max_age_seconds=3600)
    header = response.headers["set-cookie"]
    assert header.startswith(f"__Host-at_session={SECRET};")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=3600"):
        assert attribute in header, attribute
    assert "Domain" not in header


def test_clearing_a_cookie_keeps_the_host_prefix_requirements() -> None:
    response = Response()
    cookies.clear_session_cookie(response, SETTINGS)
    header = response.headers["set-cookie"]
    assert header.startswith("__Host-at_session=") and "Max-Age=0" in header
    assert "Secure" in header and "Path=/" in header and "Domain" not in header


def test_insecure_cookies_are_only_possible_on_a_loopback_origin() -> None:
    loopback = AuthSettings.model_validate(
        {"AUTH_OIDC_ISSUER": ISSUER, "AUTH_WEB_ORIGIN": "http://127.0.0.1:18080",
         "AUTH_COOKIE_SECURE": "false"}
    )  # fmt: skip
    assert loopback.cookie_name == "at_session" and SETTINGS.cookie_name == "__Host-at_session"
    for bad in (
        {"AUTH_WEB_ORIGIN": "https://autotramita.example", "AUTH_COOKIE_SECURE": "false"},
        {"AUTH_WEB_ORIGIN": "http://127.0.0.1:18080", "AUTH_COOKIE_SECURE": "true"},
        {"AUTH_WEB_ORIGIN": "https://autotramita.example/path"},
        {"AUTH_WEB_ORIGIN": "https://user@autotramita.example"},
        {"AUTH_WEB_CLIENT_SECRET": ""},
    ):
        with pytest.raises(ValueError):
            AuthSettings.model_validate({"AUTH_OIDC_ISSUER": ISSUER, **bad})


# --- step-up ------------------------------------------------------------------------------------
def session(**kw: Any) -> UserSession:
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    base: dict[str, Any] = {
        "id": uuid.uuid4(), "user_id": uuid.uuid4(), "client_type": ClientType.WEB,
        "kc_session_id": "kc", "active_tenant_id": None, "active_branch_id": None,
        "active_membership_id": None, "context_version": 1, "auth_time": now,
        "auth_level": AuthLevel.LOA1, "step_up_at": None, "device_label": None, "platform": None,
        "app_version": None, "ua_family": None, "country_code": None, "created_at": now,
        "last_activity_at": now, "idle_expires_at": now + timedelta(minutes=30),
        "absolute_expires_at": now + timedelta(hours=12), "revoked_at": None,
        "revoked_reason": None, "version": 1,
    }  # fmt: skip
    return UserSession(**{**base, **kw})


T = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_authorization_parameters_per_purpose() -> None:
    mfa = authorization_params(StepUpPurpose.MFA)
    assert (mfa.acr_values, mfa.prompt, mfa.max_age) == ("loa2", None, None)
    reauth = authorization_params(StepUpPurpose.REAUTHENTICATE)
    assert (reauth.acr_values, reauth.prompt, reauth.max_age) == ("loa1", "login", 0)
    assert level_from_acr("loa2") is AuthLevel.LOA2
    for other in ("loa1", None, "", "LOA2", "2"):
        assert level_from_acr(other) is AuthLevel.LOA1


def test_loa1_freshness_counts_from_sign_in_or_the_last_step_up() -> None:
    fresh = session()
    require_step_up(
        fresh, level=AuthLevel.LOA1, max_age_seconds=600, now=T + timedelta(seconds=600)
    )
    with pytest.raises(StepUpRequired) as stale:
        require_step_up(
            fresh, level=AuthLevel.LOA1, max_age_seconds=600, now=T + timedelta(seconds=601)
        )
    assert (stale.value.status, stale.value.code) == (401, "STEP_UP_REQUIRED")
    challenge = stale.value.headers["WWW-Authenticate"]
    assert 'error="insufficient_user_authentication"' in challenge and 'max_age="600"' in challenge
    renewed = session(step_up_at=T + timedelta(minutes=20))
    require_step_up(
        renewed, level=AuthLevel.LOA1, max_age_seconds=600, now=T + timedelta(minutes=25)
    )


def test_loa2_needs_a_recorded_second_factor_step_up_within_the_window() -> None:
    plain = session()
    with pytest.raises(StepUpRequired) as missing:
        require_step_up(plain, level=AuthLevel.LOA2, max_age_seconds=600, now=T)
    assert 'acr_values="loa2"' in missing.value.headers["WWW-Authenticate"]
    only_loa1_step_up = session(step_up_at=T)  # level still LOA1
    with pytest.raises(StepUpRequired):
        require_step_up(only_loa1_step_up, level=AuthLevel.LOA2, max_age_seconds=600, now=T)
    mfa = session(auth_level=AuthLevel.LOA2, step_up_at=T)
    require_step_up(mfa, level=AuthLevel.LOA2, max_age_seconds=600, now=T + timedelta(seconds=599))
    with pytest.raises(StepUpRequired):
        require_step_up(
            mfa, level=AuthLevel.LOA2, max_age_seconds=600, now=T + timedelta(seconds=601)
        )
