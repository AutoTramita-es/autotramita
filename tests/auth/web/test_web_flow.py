"""F2-T06 / AC-WEB-01..12: the web sign-in end to end on real PostgreSQL 16 and Redis 7, with a
fake identity provider. Every negative case sits next to the positive one it protects."""

import json
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import pytest
from app.auth.settings import AuthLimitSettings
from app.auth.web.csrf import csrf_token
from fastapi.testclient import TestClient
from tests.auth.fake_idp import ISSUER, Clock, FakeIdp
from tests.auth.web_harness import (
    ADMIN_HOST,
    CHROME,
    FIREFOX,
    FLOW_COOKIE,
    SESSION_COOKIE,
    SUBJECT,
    WEB_HOST,
    Web,
    build_web,
)
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

ORIGIN = f"https://{WEB_HOST}"
API = "/api/v1/auth"


@pytest.fixture
def web(role_env: RoleEnv, redis_url: str) -> Iterator[Web]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(role_env, redis_url)
    yield harness
    harness.close()


def secure(client: TestClient) -> dict[str, str]:
    """Headers a browser page of ours sends with an unsafe request."""
    value = client.cookies.get(SESSION_COOKIE)
    assert value, "no session cookie"
    return {"X-CSRF-Token": csrf_token(value), "Origin": ORIGIN}


def problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code and response.headers["content-type"].startswith(
        "application/problem+json"
    )


def audit(web: Web, action: str) -> list[tuple[Any, ...]]:
    return web.rows(
        "SELECT outcome, details->>'reason', actor_type FROM audit_events WHERE action = :a "
        "ORDER BY occurred_at",
        a=action,
    )


# --- AC-WEB-01 the whole journey -------------------------------------------------------------------
def test_login_session_logout_and_the_old_cookie_is_dead(web: Web) -> None:
    client = web.client()
    start = client.get(f"{API}/login", params={"return_to": "/app/cases?x=1"})
    assert start.status_code == 302
    location = start.headers["location"]
    assert location.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    query = web.start(web.client(), "/")  # a second flow only to inspect the parameters
    assert {"client_id", "redirect_uri", "state", "nonce", "code_challenge"} <= set(query)
    assert query["client_id"] == "at-web" and query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256" and query["scope"] == "openid"
    assert query["redirect_uri"] == f"{ORIGIN}/api/v1/auth/callback"
    assert len({query["state"], query["nonce"]}) == 2 and "verifier" not in location

    callback = web.sign_in(client, return_to="/app/cases?x=1")
    assert callback.status_code == 302 and callback.headers["location"] == "/app/cases?x=1"
    cookie = client.cookies.get(SESSION_COOKIE)
    assert cookie and len(cookie) == 43

    info = client.get(f"{API}/session")
    assert info.status_code == 200
    body = info.json()
    assert body["user"]["email"] == "person@example.test" and body["user"]["status"] == "ACTIVE"
    assert body["user"]["email_verified"] is True and body["auth_level"] == "LOA1"
    assert body["client_type"] == "WEB" and body["workspace"] is None
    assert body["csrf_token"] == csrf_token(cookie)
    assert "token" not in json.dumps({k: v for k, v in body.items() if k != "csrf_token"})

    out = client.post(f"{API}/logout", headers=secure(client))
    assert out.status_code == 200
    end = out.json()["end_session_url"]
    assert end.startswith(f"{ISSUER}/protocol/openid-connect/logout?")
    assert "client_id=at-web" in end and quote(f"{ORIGIN}/", safe="") in end
    assert 'at_session=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]
    stale = client.get(f"{API}/session", headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})
    problem(stale, 401, "SESSION_REVOKED")
    assert web.rows("SELECT revoked_reason FROM user_sessions") == [("LOGOUT",)]
    actions = {r[0] for r in web.rows("SELECT action FROM audit_events")}
    assert {"auth.login.succeeded", "session.created", "auth.logout", "session.revoked"} <= actions
    assert web.rows("SELECT last_login_at IS NOT NULL FROM users") == [(True,)]


# --- AC-WEB-02 cookie attributes -------------------------------------------------------------------
def test_cookie_attributes_and_the_flow_cookie_is_cleared(web: Web) -> None:
    client = web.client()
    start = client.get(f"{API}/login")
    flow_cookies = start.headers.get_list("set-cookie")
    flow = next(h for h in flow_cookies if h.startswith(f"{FLOW_COOKIE}="))
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert attribute in flow, attribute
    from urllib.parse import parse_qs, urlparse

    query = {k: v[0] for k, v in parse_qs(urlparse(start.headers["location"]).query).items()}
    response = client.get(
        f"{API}/callback", params={"code": web.code_for(query), "state": query["state"]}
    )
    headers = response.headers.get_list("set-cookie")
    session = next(h for h in headers if h.startswith(f"{SESSION_COOKIE}="))
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in session, attribute
    assert "Domain" not in session
    max_age = int(session.split("Max-Age=")[1].split(";")[0])
    assert 12 * 3600 - 120 <= max_age <= 12 * 3600
    cleared = next(h for h in headers if h.startswith(f"{FLOW_COOKIE}="))
    assert "Max-Age=0" in cleared


# --- AC-WEB-03 state, nonce, PKCE, replay ----------------------------------------------------------
def test_a_replayed_callback_is_refused(web: Web) -> None:
    client = web.client()
    query = web.start(client)
    params = {"code": web.code_for(query), "state": query["state"]}
    assert client.get(f"{API}/callback", params=params).status_code == 302
    again = client.get(f"{API}/callback", params=params)
    problem(again, 400, "AUTH_CALLBACK_REJECTED")
    assert [r[1] for r in audit(web, "auth.callback.rejected")] == ["STATE"]
    assert len(web.rows("SELECT 1 FROM user_sessions")) == 1


def test_a_token_for_another_nonce_is_refused(web: Web) -> None:
    client = web.client()
    query = web.start(client)
    code = web.code_for(query, nonce="x" * 32)
    problem(
        client.get(f"{API}/callback", params={"code": code, "state": query["state"]}),
        400,
        "AUTH_CALLBACK_REJECTED",
    )
    assert [r[1] for r in audit(web, "auth.callback.rejected")] == ["TOKEN_NONCE"]
    assert web.rows("SELECT 1 FROM user_sessions") == [] and web.rows("SELECT 1 FROM users") == []


@pytest.mark.parametrize(
    "params",
    [{}, {"code": "c"}, {"state": "s"}, {"code": "c", "state": "short"}, {"code": "c", "state": "z" * 32},
     {"error": "access_denied", "state": "z" * 32}, {"code": "x" * 3000, "state": "z" * 32}],
)  # fmt: skip
def test_malformed_or_unknown_callbacks_are_refused(web: Web, params: dict[str, str]) -> None:
    problem(web.client().get(f"{API}/callback", params=params), 400, "AUTH_CALLBACK_REJECTED")
    assert web.rows("SELECT 1 FROM user_sessions") == []


def test_a_callback_without_the_browsers_flow_cookie_is_refused(web: Web) -> None:
    victim, attacker_view = web.client(), web.client()
    query = web.start(victim)  # the victim starts a sign-in ...
    code = web.code_for(query)
    # ... but the callback arrives from a browser that never started this flow (login CSRF)
    problem(
        attacker_view.get(f"{API}/callback", params={"code": code, "state": query["state"]}),
        400,
        "AUTH_CALLBACK_REJECTED",
    )
    assert [r[1] for r in audit(web, "auth.callback.rejected")] == ["BINDER"]
    assert web.rows("SELECT 1 FROM user_sessions") == []


def test_pkce_is_enforced_by_the_code_exchange(web: Web) -> None:
    client = web.client()
    query = web.start(client)
    query["code_challenge"] = "A" * 43  # not the challenge of this flow's verifier
    code = web.code_for(query)
    problem(
        client.get(f"{API}/callback", params={"code": code, "state": query["state"]}),
        400,
        "AUTH_CALLBACK_REJECTED",
    )
    assert [r[1] for r in audit(web, "auth.callback.rejected")] == ["EXCHANGE"]


def test_a_flow_started_on_one_site_cannot_finish_on_another(web: Web) -> None:
    web_client, admin_client = web.client(), web.client(ADMIN_HOST)
    query = web.start(web_client)
    admin_client.cookies.set(FLOW_COOKIE, web_client.cookies[FLOW_COOKIE], domain=ADMIN_HOST)
    code = web.code_for(query)
    problem(
        admin_client.get(f"{API}/callback", params={"code": code, "state": query["state"]}),
        400,
        "AUTH_CALLBACK_REJECTED",
    )
    assert [r[1] for r in audit(web, "auth.callback.rejected")] == ["ORIGIN"]


def test_parallel_callbacks_with_one_state_succeed_once(web: Web) -> None:
    first = web.client()
    query = web.start(first)
    code = web.code_for(query)
    binder = first.cookies[FLOW_COOKIE]
    statuses: list[int] = []

    def attempt() -> None:
        c = web.client()
        c.cookies.set(FLOW_COOKIE, binder, domain=WEB_HOST)
        statuses.append(
            c.get(f"{API}/callback", params={"code": code, "state": query["state"]}).status_code
        )

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(statuses) == [302] + [400] * 5
    assert len(web.rows("SELECT 1 FROM user_sessions")) == 1


# --- AC-WEB-04 tokens never reach the browser ------------------------------------------------------
def test_no_token_is_ever_returned_to_the_browser(web: Web) -> None:
    client = web.client()
    query = web.start(client)
    token = web.idp.sign(web.idp.id_claims(query["nonce"]))
    code = web.exchanger.issue(
        token, challenge=query["code_challenge"], redirect_uri=query["redirect_uri"]
    )
    response = client.get(f"{API}/callback", params={"code": code, "state": query["state"]})
    everything = response.text + str(dict(response.headers)) + str(dict(client.cookies))
    assert token not in everything and token.split(".")[1] not in everything
    assert set(client.cookies.keys()) == {SESSION_COOKIE}
    page = client.get(f"{API}/session")
    assert (
        token not in page.text and "id_token" not in page.text and "access_token" not in page.text
    )
    assert web.rows("SELECT count(*) FROM user_sessions WHERE credential_hash IS NULL") == [(0,)]


# --- AC-WEB-05 no session fixation -----------------------------------------------------------------
def test_signing_in_replaces_a_planted_cookie_and_two_sign_ins_never_share_a_credential(
    web: Web,
) -> None:
    planted = "A" * 43
    client = web.client()
    client.cookies.set(SESSION_COOKIE, planted, domain=WEB_HOST)
    web.sign_in(client)
    fresh = client.cookies[SESSION_COOKIE]
    assert fresh != planted
    problem(
        client.get(f"{API}/session", headers={"Cookie": f"{SESSION_COOKIE}={planted}"}),
        401,
        "SESSION_REQUIRED",
    )
    assert client.get(f"{API}/session").status_code == 200
    other = web.client()
    web.sign_in(other, sid="another-keycloak-session")
    assert other.cookies[SESSION_COOKIE] != fresh


def test_a_second_sign_in_in_the_same_keycloak_session_supersedes_the_first(web: Web) -> None:
    first, second = web.client(), web.client()
    web.sign_in(first)
    old = first.cookies[SESSION_COOKIE]
    web.sign_in(second)  # same Keycloak sid, e.g. after a logout with the SSO session still alive
    assert second.get(f"{API}/session").status_code == 200
    problem(
        first.get(f"{API}/session", headers={"Cookie": f"{SESSION_COOKIE}={old}"}),
        401,
        "SESSION_REVOKED",
    )
    live = web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL")
    assert live == [(1,)]


# --- AC-WEB-06 return_to ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (None, "/"), ("/app/cases?x=1&y=2", "/app/cases?x=1&y=2"), ("//evil.example", "/"),
        ("https://evil.example/", "/"), ("/\\evil.example", "/"), ("/%2F/evil.example", "/"),
        ("/%252F%252Fevil.example", "/"), ("javascript:alert(1)", "/"), ("evil.example", "/"),
        ("/a\r\nSet-Cookie: x=y", "/"), ("/" + "a" * 600, "/"),
    ],
)  # fmt: skip
def test_return_to_only_ever_leads_to_a_path_on_our_own_site(
    web: Web, asked: str | None, expected: str
) -> None:
    response = web.sign_in(web.client(), return_to=asked)
    assert response.status_code == 302 and response.headers["location"] == expected


# --- AC-WEB-07 CSRF --------------------------------------------------------------------------------
def test_unsafe_requests_need_the_csrf_token_and_a_proof_of_origin(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    good = secure(client)
    cookie = client.cookies[SESSION_COOKIE]
    for headers in (
        {}, {"Origin": ORIGIN}, {"X-CSRF-Token": good["X-CSRF-Token"]},
        {**good, "Origin": "https://evil.example"}, {**good, "Origin": "null"},
        {"X-CSRF-Token": "wrong", "Origin": ORIGIN},
        {"X-CSRF-Token": good["X-CSRF-Token"], "Sec-Fetch-Site": "cross-site"},
    ):  # fmt: skip
        problem(client.post(f"{API}/logout", headers=headers), 403, "CSRF_INVALID")
    assert client.get(f"{API}/session").status_code == 200  # nothing was logged out
    assert len(audit(web, "authz.denied")) == 7
    assert {r[1] for r in audit(web, "authz.denied")} == {"CSRF"}
    ok = client.post(
        f"{API}/logout",
        headers={"X-CSRF-Token": csrf_token(cookie), "Sec-Fetch-Site": "same-origin"},
    )
    assert ok.status_code == 200


def test_safe_methods_need_no_csrf_token(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    assert client.get(f"{API}/session").status_code == 200


# --- AC-WEB-08 one kind of credential --------------------------------------------------------------
def test_cookie_and_bearer_together_are_refused_and_no_credential_is_a_401(web: Web) -> None:
    client = web.client()
    problem(client.get(f"{API}/session"), 401, "AUTH_REQUIRED")
    problem(  # bearer sessions exist since F2-T07: a bad token is an invalid token
        client.get(f"{API}/session", headers={"Authorization": "Bearer abc"}),
        401,
        "AUTH_TOKEN_INVALID",
    )
    web.sign_in(client)
    problem(
        client.get(f"{API}/session", headers={"Authorization": "Bearer abc"}),
        400,
        "AMBIGUOUS_CREDENTIALS",
    )


# --- AC-WEB-09 back-channel logout -----------------------------------------------------------------
def post_logout(web: Web, token: str | None = None, **kw: Any) -> httpx.Response:
    client = kw.pop("client", None) or web.client()
    body = kw.pop("content", None)
    if body is None:
        body = urlencode(
            {"logout_token": token if token is not None else web.idp.sign(web.idp.logout_claims())}
        )
    headers = kw.pop("headers", {"content-type": "application/x-www-form-urlencoded"})
    result: httpx.Response = client.post(
        f"{API}/oidc/backchannel-logout", content=body, headers=headers
    )
    return result


def test_backchannel_logout_revokes_the_named_keycloak_session_only(web: Web) -> None:
    one, two = web.client(), web.client()
    web.sign_in(one, sid="sid-one")
    web.sign_in(two, sid="sid-two")
    assert post_logout(web, web.idp.sign(web.idp.logout_claims(sid="sid-one"))).status_code == 204
    problem(one.get(f"{API}/session"), 401, "SESSION_REVOKED")
    assert two.get(f"{API}/session").status_code == 200
    assert (
        post_logout(
            web, web.idp.sign(web.idp.logout_claims(sid=None if False else "sid-two"))
        ).status_code
        == 204
    )
    problem(two.get(f"{API}/session"), 401, "SESSION_REVOKED")
    assert {r[0] for r in web.rows("SELECT revoked_reason FROM user_sessions")} == {"IDP_LOGOUT"}
    assert audit(web, "session.revoked")[0][2] == "IDP"


def test_mobile_backchannel_token_revokes_native_session(web: Web) -> None:
    token = web.access(sid="mobile-logout-sid")
    client = web.bearer(token)
    opened = client.post(f"{API}/mobile/session", json={"device": {"platform": "android"}})
    assert opened.status_code == 201, opened.text
    logout = web.idp.sign(web.idp.logout_claims(client_id="at-mobile", sid="mobile-logout-sid"))
    assert post_logout(web, logout).status_code == 204
    problem(client.get(f"{API}/session"), 401, "SESSION_REVOKED")
    problem(post_logout(web, logout), 400, "LOGOUT_TOKEN_INVALID")


def test_a_logout_token_without_sid_ends_every_session_of_the_user(web: Web) -> None:
    one, two = web.client(), web.client()
    web.sign_in(one, sid="sid-one")
    web.sign_in(two, sid="sid-two")
    token = web.idp.sign({k: v for k, v in web.idp.logout_claims().items() if k != "sid"})
    assert post_logout(web, token).status_code == 204
    problem(one.get(f"{API}/session"), 401, "SESSION_REVOKED")
    problem(two.get(f"{API}/session"), 401, "SESSION_REVOKED")


def test_a_logout_token_is_accepted_once(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    token = web.idp.sign(web.idp.logout_claims())
    assert post_logout(web, token).status_code == 204
    problem(post_logout(web, token), 400, "LOGOUT_TOKEN_INVALID")
    assert audit(web, "auth.token.invalid")[0][1] == "LOGOUT_REPLAY"


def test_logout_tokens_for_unknown_people_change_nothing_and_reveal_nothing(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    token = web.idp.sign(web.idp.logout_claims(sub="nobody-here"))
    assert post_logout(web, token).status_code == 204
    assert client.get(f"{API}/session").status_code == 200


def test_invalid_logout_requests_are_refused(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    other = FakeIdp()
    claims = web.idp.logout_claims
    bad_tokens = [
        web.idp.sign(claims(iss="https://other.example/realms/x")), web.idp.sign(claims(aud="other-client")),
        web.idp.sign({k: v for k, v in claims().items() if k != "events"}),
        web.idp.sign(claims(nonce="n")), web.idp.sign({k: v for k, v in claims().items() if k != "jti"}),
        other.sign(other.logout_claims()), web.idp.unsigned(), "", "garbage", "a.b.c",
    ]  # fmt: skip
    for token in bad_tokens:
        problem(post_logout(web, token), 400, "LOGOUT_TOKEN_INVALID")
    problem(post_logout(web, content=b"not=a-token"), 400, "LOGOUT_TOKEN_INVALID")
    problem(post_logout(web, content=b"x" * 20000), 400, "LOGOUT_TOKEN_INVALID")
    problem(
        post_logout(web, headers={"content-type": "application/json"}), 400, "LOGOUT_TOKEN_INVALID"
    )
    assert client.get(f"{API}/session").status_code == 200  # nothing was revoked


# --- AC-WEB-10 step-up -----------------------------------------------------------------------------
def start_step_up(
    web: Web, client: TestClient, purpose: str, return_to: str = "/ops"
) -> dict[str, str]:
    response = client.post(
        f"{API}/step-up", json={"purpose": purpose, "return_to": return_to}, headers=secure(client)
    )
    assert response.status_code == 200, response.text
    from urllib.parse import parse_qs, urlparse

    query = {k: v[0] for k, v in parse_qs(urlparse(response.json()["redirect_url"]).query).items()}
    assert query["client_id"] == "at-web" and query["code_challenge_method"] == "S256"
    return query


def finish_step_up(
    web: Web, client: TestClient, query: dict[str, str], **identity: Any
) -> httpx.Response:
    code = web.code_for(query, **identity)
    result: httpx.Response = client.get(
        f"{API}/callback", params={"code": code, "state": query["state"]}
    )
    return result


def test_reauthentication_rotates_the_credential_and_records_the_step_up(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    old = client.cookies[SESSION_COOKIE]
    query = start_step_up(web, client, "REAUTHENTICATE")
    assert (query["prompt"], query["max_age"], query["acr_values"]) == ("login", "0", "loa1")
    done = finish_step_up(web, client, query)
    assert done.status_code == 302 and done.headers["location"] == "/ops"
    assert client.cookies[SESSION_COOKIE] != old
    problem(
        client.get(f"{API}/session", headers={"Cookie": f"{SESSION_COOKIE}={old}"}),
        401,
        "SESSION_REQUIRED",
    )
    info = client.get(f"{API}/session").json()
    assert info["auth_level"] == "LOA1" and info["step_up_expires_at"] is not None
    assert [r[0] for r in audit(web, "security.step_up.succeeded")] == ["SUCCESS"]


def test_mfa_step_up_reaches_loa2_only_with_a_second_factor(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    query = start_step_up(web, client, "MFA")
    assert query["acr_values"] == "loa2" and "prompt" not in query
    old = client.cookies[SESSION_COOKIE]
    refused = finish_step_up(web, client, query, acr="loa1")  # password only: not enough
    problem(refused, 400, "AUTH_CALLBACK_REJECTED")
    assert (
        client.cookies[SESSION_COOKIE] == old
        and client.get(f"{API}/session").json()["auth_level"] == "LOA1"
    )
    assert [r[0] for r in audit(web, "security.step_up.failed")] == ["FAILURE"]
    second = start_step_up(web, client, "MFA")
    assert finish_step_up(web, client, second, acr="loa2").status_code == 302
    assert client.get(f"{API}/session").json()["auth_level"] == "LOA2"


@pytest.mark.parametrize(
    "identity",
    [{"auth_time": 1_000}, {"sub": "someone-else"}],
    ids=["stale authentication", "other person"],
)
def test_step_up_with_a_stale_or_foreign_authentication_is_refused(
    web: Web, identity: dict[str, Any]
) -> None:
    client = web.client()
    web.sign_in(client)
    query = start_step_up(web, client, "REAUTHENTICATE")
    problem(finish_step_up(web, client, query, **identity), 400, "AUTH_CALLBACK_REJECTED")
    assert client.get(f"{API}/session").json()["step_up_expires_at"] is None


def test_a_step_up_flow_cannot_be_completed_in_another_session(web: Web) -> None:
    mine, theirs = web.client(), web.client()
    web.sign_in(mine)
    web.sign_in(theirs, sub="another-person", sid="other-sid", email="other@example.test")
    query = start_step_up(web, mine, "REAUTHENTICATE")
    theirs.cookies.set(FLOW_COOKIE, mine.cookies[FLOW_COOKIE], domain=WEB_HOST)
    problem(
        finish_step_up(
            web, theirs, query, sub="another-person", sid="other-sid", email="other@example.test"
        ),
        400,
        "AUTH_CALLBACK_REJECTED",
    )


def test_step_up_needs_a_session_and_the_csrf_token(web: Web) -> None:
    client = web.client()
    problem(client.post(f"{API}/step-up", json={"purpose": "MFA"}), 401, "AUTH_REQUIRED")
    web.sign_in(client)
    problem(client.post(f"{API}/step-up", json={"purpose": "MFA"}), 403, "CSRF_INVALID")
    bad = client.post(f"{API}/step-up", json={"purpose": "BOGUS"}, headers=secure(client))
    assert bad.status_code == 422


# --- AC-WEB-11 no-store ----------------------------------------------------------------------------
def test_every_answer_of_the_sign_in_routes_is_no_store_errors_included(web: Web) -> None:
    client = web.client()
    answers = [
        client.get(f"{API}/login"), client.get(f"{API}/callback"),  # 400
        client.get(f"{API}/session"),  # 401
        post_logout(web, "garbage"),  # 400
    ]  # fmt: skip
    web.sign_in(client)
    answers += [client.get(f"{API}/session"), client.post(f"{API}/step-up", json={"purpose": "MFA"}, headers=secure(client)),
                client.post(f"{API}/logout", headers=secure(client)), post_logout(web)]  # fmt: skip
    for response in answers:
        assert response.headers["cache-control"] == "no-store", response.url
        assert response.headers["pragma"] == "no-cache"
    assert "x-request-id" in answers[0].headers


# --- AC-WEB-12 limits and failure of the limiter ---------------------------------------------------
def test_sign_in_routes_have_their_own_ip_limit(role_env: RoleEnv, redis_url: str) -> None:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(
        role_env, redis_url, limits=AuthLimitSettings.model_validate({"AUTH_LOGIN_PER_MIN_IP": 2})
    )
    try:
        client = harness.client()
        assert [client.get(f"{API}/login").status_code for _ in range(2)] == [302, 302]
        limited = client.get(f"{API}/login")
        problem(limited, 429, "RATE_LIMIT_EXCEEDED")
        assert int(limited.headers["retry-after"]) >= 1
        assert client.get(f"{API}/session").status_code == 401  # other routes are not affected
    finally:
        harness.close()


def test_when_the_limiter_is_down_sign_in_fails_closed(role_env: RoleEnv, redis_url: str) -> None:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(role_env, redis_url, redis_for_limiter="redis://127.0.0.1:1/0")
    try:
        problem(harness.client().get(f"{API}/login"), 503, "RATE_LIMIT_UNAVAILABLE")
    finally:
        harness.close()


def test_step_up_requests_are_limited_per_session(role_env: RoleEnv, redis_url: str) -> None:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(
        role_env,
        redis_url,
        limits=AuthLimitSettings.model_validate({"AUTH_STEP_UP_PER_HOUR_SESSION": 2}),
    )
    try:
        client = harness.client()
        harness.sign_in(client)
        codes = [
            client.post(
                f"{API}/step-up", json={"purpose": "MFA"}, headers=secure(client)
            ).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]
    finally:
        harness.close()


# --- accounts, sites and configuration -------------------------------------------------------------
def test_a_deactivated_person_authenticates_but_gets_no_session(web: Web) -> None:
    with web.env.admin_engine().connect() as c:
        from sqlalchemy import text

        c.execute(
            text(
                "INSERT INTO users (auth_subject, email, email_normalized, status, email_verified_at) "
                "VALUES (:s, 'person@example.test', 'person@example.test', 'DEACTIVATED', now())"
            ),
            {"s": SUBJECT},
        )
    client = web.client()
    response = web.sign_in(client)
    problem(response, 403, "ACCOUNT_DISABLED")
    assert SESSION_COOKIE not in client.cookies and web.rows("SELECT 1 FROM user_sessions") == []
    failed = web.rows(
        "SELECT outcome, details->>'error' FROM audit_events WHERE action = 'auth.login.failed'"
    )
    assert failed == [("DENIED", "ACCOUNT_DISABLED")]


def test_an_unverified_person_gets_a_session_with_limited_status(web: Web) -> None:
    client = web.client()
    assert web.sign_in(client, verified=False).status_code == 302
    assert client.get(f"{API}/session").json()["user"]["status"] == "PENDING_VERIFICATION"


def test_an_email_that_belongs_to_another_identity_is_a_conflict(web: Web) -> None:
    web.sign_in(web.client())
    problem(web.sign_in(web.client(), sub="a-different-sub", sid="s2"), 409, "ACCOUNT_CONFLICT")
    assert len(web.rows("SELECT 1 FROM users")) == 1
    assert [
        r[0]
        for r in web.rows("SELECT action FROM audit_events WHERE action = 'identity.link.conflict'")
    ] == ["identity.link.conflict"]


def test_the_admin_site_gets_admin_sessions_with_shorter_lifetimes(web: Web) -> None:
    client = web.client(ADMIN_HOST)
    assert web.sign_in(client).status_code == 302
    info = client.get(f"{API}/session").json()
    assert info["client_type"] == "ADMIN_WEB"
    rows = web.rows(
        "SELECT idle_expires_at - created_at, absolute_expires_at - created_at FROM user_sessions"
    )
    assert [str(v) for v in rows[0]] == ["0:15:00", "8:00:00"]


def test_unknown_hosts_and_a_missing_configuration_do_not_serve_sign_in(web: Web) -> None:
    problem(web.client("evil.example").get(f"{API}/login"), 503, "UNKNOWN_ORIGIN")
    web.app.state.auth = None  # the runtime is not configured
    problem(web.client().get(f"{API}/login"), 503, "AUTH_NOT_CONFIGURED")
    problem(web.client().get(f"{API}/session"), 503, "AUTH_NOT_CONFIGURED")


# --- sessions: expiry and theft signals ------------------------------------------------------------
def test_an_idle_session_expires_without_any_cleanup_job(web: Web) -> None:
    client = web.client()
    web.sign_in(client)
    with web.env.admin_engine().connect() as c:
        from sqlalchemy import text

        c.execute(text("UPDATE user_sessions SET idle_expires_at = now() - interval '1 minute'"))
    problem(client.get(f"{API}/session"), 401, "SESSION_EXPIRED")


def test_a_different_browser_revokes_the_session_and_leaves_a_trace(web: Web) -> None:
    client = web.client(user_agent=CHROME)
    web.sign_in(client)
    cookie = client.cookies[SESSION_COOKIE]
    stranger = web.client(user_agent=FIREFOX)
    problem(
        stranger.get(f"{API}/session", headers={"Cookie": f"{SESSION_COOKIE}={cookie}"}),
        401,
        "SESSION_REVOKED",
    )
    assert web.rows("SELECT revoked_reason FROM user_sessions") == [("SECURITY_POLICY",)]
    problem(client.get(f"{API}/session"), 401, "SESSION_REVOKED")
    signals = web.rows(
        "SELECT details->>'signal' FROM audit_events WHERE action = 'session.theft_suspected'"
    )
    assert signals == [("UA_CHANGE",)]


def test_a_reused_clock_helper_is_available() -> None:
    assert Clock(5.0)() == 5.0
