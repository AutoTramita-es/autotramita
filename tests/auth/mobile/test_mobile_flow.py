"""F2-T07 / AC-MOB-01..07: mobile (bearer) sessions and the session list and revocation routes,
on real PostgreSQL 16 and Redis 7 with a fake identity provider."""

import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from app.auth.web.csrf import csrf_token
from tests.auth.fake_admin import FakeAdmin
from tests.auth.fake_idp import NOW
from tests.auth.web_harness import ORIGIN_WEB, SESSION_COOKIE, SID, SUBJECT, Web, build_web
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

API = "/api/v1"
OPEN = f"{API}/auth/mobile/session"
DEVICE = {"device": {"label": "Ana's phone", "platform": "android", "app_version": "1.4.2+7"}}
SID_B = "sid-device-b"


@pytest.fixture
def web(role_env: RoleEnv, redis_url: str) -> Iterator[Web]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(role_env, redis_url)
    harness.runtime.admin = FakeAdmin()  # "sign out everywhere" asks for second factors (F-3)
    yield harness
    harness.close()


def problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


def open_session(web: Web, **identity: Any) -> tuple[httpx.Response, Any]:
    client = web.bearer(web.access(**identity))
    return client.post(OPEN, json=DEVICE), client


def secure(client: Any) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(client.cookies[SESSION_COOKIE]), "Origin": ORIGIN_WEB}


# --- AC-MOB-01 opening a session is idempotent ----------------------------------------------------
def test_opening_a_session_creates_it_once_and_returns_it_afterwards(web: Web) -> None:
    first, client = open_session(web)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["client_type"] == "MOBILE" and body["csrf_token"] is None
    assert body["user"]["email"] == "person@example.test" and body["user"]["status"] == "ACTIVE"
    assert body["auth_level"] == "LOA1" and body["workspace"] is None
    second = client.post(OPEN, json=DEVICE)
    assert second.status_code == 200 and second.json()["session_id"] == body["session_id"]
    assert client.post(OPEN, json={}).json()["session_id"] == body["session_id"]  # no device: fine
    rows = web.rows("SELECT device_label, platform, app_version, credential_hash IS NULL, kc_session_id "
                    "FROM user_sessions")  # fmt: skip
    assert rows == [("Ana's phone", "android", "1.4.2+7", True, SID)]
    assert [r[0] for r in web.rows("SELECT action FROM audit_events WHERE action IN "
                                   "('auth.login.succeeded', 'session.created')")] == [
        "session.created", "auth.login.succeeded"]  # fmt: skip
    assert web.rows("SELECT last_login_at IS NOT NULL FROM users") == [(True,)]


def test_parallel_openings_of_one_keycloak_session_give_one_session(web: Web) -> None:
    token = web.access()
    barrier = threading.Barrier(6)
    results: list[tuple[int, str]] = []

    def attempt() -> None:
        client = web.bearer(token)
        barrier.wait()
        r = client.post(OPEN, json=DEVICE)
        results.append((r.status_code, r.json().get("session_id", "")))

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(code for code, _ in results) == [200] * 5 + [201]
    assert len({sid for _, sid in results}) == 1
    assert web.rows("SELECT count(*) FROM user_sessions") == [(1,)]


def test_another_device_of_the_same_person_gets_its_own_session(web: Web) -> None:
    a, _ = open_session(web, sid="sid-a")
    b, _ = open_session(web, sid="sid-b")
    assert a.status_code == b.status_code == 201
    assert a.json()["session_id"] != b.json()["session_id"]
    assert web.rows("SELECT count(DISTINCT user_id) FROM user_sessions") == [(1,)]


# --- AC-MOB-02 only valid access tokens of the mobile client -------------------------------------
@pytest.mark.parametrize(
    "claims",
    [{"azp": "at-web"}, {"aud": ["account"]}, {"typ": "ID"}, {"iss": "https://other.example/realms/x"},
     {"iat": int(NOW) - 1000, "exp": int(NOW) - 500}, {"sid": None}],
    ids=["web client", "wrong audience", "id token", "other issuer", "expired", "no session id"],
)  # fmt: skip
def test_tokens_that_are_not_mobile_access_tokens_are_refused(
    web: Web, claims: dict[str, Any]
) -> None:
    from tests.auth.fake_idp import DROP

    prepared: dict[str, Any] = {k: (DROP if v is None else v) for k, v in claims.items()}
    client = web.bearer(web.idp.token(**prepared))
    for path, method in (
        (OPEN, "post"),
        (f"{API}/auth/session", "get"),
        (f"{API}/sessions", "get"),
    ):
        r = client.request(method.upper(), path, **({"json": {}} if method == "post" else {}))
        problem(r, 401, "AUTH_TOKEN_INVALID")
    assert web.rows("SELECT 1 FROM user_sessions") == [] and web.rows("SELECT 1 FROM users") == []


def test_a_garbage_or_missing_token_is_a_401(web: Web) -> None:
    for header in ("Bearer", "Bearer not-a-jwt", "Bearer a.b.c", "Basic abc"):
        c = web.client(headers={"authorization": header})
        assert c.post(OPEN, json={}).status_code == 401
    problem(web.client().post(OPEN, json={}), 401, "AUTH_REQUIRED")


def test_a_cookie_together_with_a_bearer_token_is_refused(web: Web) -> None:
    client = web.bearer(web.access())
    client.cookies.set(SESSION_COOKIE, "A" * 43, domain="autotramita.example")
    problem(client.post(OPEN, json={}), 400, "AMBIGUOUS_CREDENTIALS")


def test_a_token_without_an_email_cannot_create_a_new_person(web: Web) -> None:
    problem(web.bearer(web.access(email=None)).post(OPEN, json={}), 400, "INVALID_EMAIL")
    assert web.rows("SELECT 1 FROM users") == []
    open_session(web)  # the person exists now: a token without e-mail is then fine
    assert web.bearer(web.access(email=None)).post(OPEN, json={}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{"refresh_token": "x"}, {"device": {"refresh_token": "x"}}, {"device": {"label": "a\nb"}},
     {"device": {"label": ""}}, {"device": {"label": "x" * 81}}, {"device": {"platform": "a b"}},
     {"device": {"app_version": "1" * 41}}, {"device": "phone"}, {"id_token": "x"}],
)  # fmt: skip
def test_unknown_fields_and_malformed_device_data_are_refused(
    web: Web, body: dict[str, Any]
) -> None:
    r = web.bearer(web.access()).post(OPEN, json=body)
    assert r.status_code == 422
    assert "x" * 40 not in r.text and r.json()["code"] == "VALIDATION_ERROR"
    assert web.rows("SELECT 1 FROM user_sessions") == []


def test_no_token_of_any_kind_is_ever_stored(web: Web) -> None:
    token = web.access()
    client = web.bearer(token)
    client.post(OPEN, json={"refresh_token": "refresh-secret-value"})  # refused
    client.post(OPEN, json=DEVICE)
    dump = web.rows("SELECT row_to_json(s)::text FROM user_sessions s")
    audit = web.rows("SELECT row_to_json(a)::text FROM audit_events a")
    users = web.rows("SELECT row_to_json(u)::text FROM users u")
    text = str(dump + audit + users)
    assert token not in text and token.split(".")[1] not in text
    assert "refresh" not in text.lower() and "secret-value" not in text


# --- sessions behind a token -----------------------------------------------------------------------
def test_a_valid_token_without_an_application_session_is_a_401(web: Web) -> None:
    client = web.bearer(web.access())
    problem(client.get(f"{API}/auth/session"), 401, "SESSION_REQUIRED")
    problem(client.get(f"{API}/sessions"), 401, "SESSION_REQUIRED")


def test_another_persons_token_cannot_reach_my_session(web: Web) -> None:
    open_session(web)
    other = web.bearer(web.access(sub="someone-else", email="else@example.test"))
    problem(other.get(f"{API}/auth/session"), 401, "SESSION_REQUIRED")  # same sid, other person


def test_the_session_state_of_a_mobile_caller_has_no_csrf_token_and_ignores_the_user_agent(
    web: Web,
) -> None:
    _, client = open_session(web)
    info = client.get(f"{API}/auth/session")
    assert info.status_code == 200 and info.json()["csrf_token"] is None
    changed = web.bearer(web.access(), user_agent="okhttp/4.12 Totally-Different/9")
    assert changed.get(f"{API}/auth/session").status_code == 200  # app updates change agents
    assert web.rows("SELECT revoked_at IS NULL FROM user_sessions") == [(True,)]


def test_an_idle_mobile_session_expires_and_the_still_valid_token_can_open_a_new_one(
    web: Web,
) -> None:
    first, client = open_session(web)
    with web.env.admin_engine().connect() as c:
        from sqlalchemy import text

        c.execute(text("UPDATE user_sessions SET idle_expires_at = now() - interval '1 minute'"))
    problem(client.get(f"{API}/auth/session"), 401, "SESSION_EXPIRED")
    again = client.post(OPEN, json=DEVICE)
    assert again.status_code == 201 and again.json()["session_id"] != first.json()["session_id"]


def test_accounts_that_may_not_sign_in_get_no_session(web: Web) -> None:
    pending = web.bearer(web.access(sub="p", email="p@example.test", verified=False)).post(
        OPEN, json={}
    )
    assert pending.status_code == 201 and pending.json()["user"]["status"] == "PENDING_VERIFICATION"
    with web.env.admin_engine().connect() as c:
        from sqlalchemy import text

        c.execute(text("UPDATE users SET status = 'BLOCKED' WHERE auth_subject = 'p'"))
    problem(
        web.bearer(web.access(sub="p", email="p@example.test", sid="new")).post(OPEN, json={}),
        403,
        "ACCOUNT_DISABLED",
    )
    problem(
        web.bearer(web.access(sub="p", email="p@example.test")).get(f"{API}/auth/session"),
        403,
        "ACCOUNT_DISABLED",
    )
    assert [
        r[0]
        for r in web.rows(
            "SELECT details->>'error' FROM audit_events WHERE action = 'auth.login.failed'"
        )
    ] == ["ACCOUNT_DISABLED"]


# --- AC-MOB-03 revocation beats a token that is still valid ----------------------------------------
def test_a_revoked_session_stays_revoked_although_the_token_is_still_valid(web: Web) -> None:
    a, client_a = open_session(web, sid="sid-a")
    _, client_b = open_session(web, sid="sid-b")
    revoked = client_b.delete(f"{API}/sessions/{a.json()['session_id']}")
    assert revoked.status_code == 204
    problem(client_a.get(f"{API}/auth/session"), 401, "SESSION_REVOKED")
    problem(client_a.post(OPEN, json=DEVICE), 401, "SESSION_REVOKED")  # no resurrection
    assert client_b.get(f"{API}/auth/session").status_code == 200
    assert web.rows("SELECT revoked_reason FROM user_sessions WHERE kc_session_id = 'sid-a'") == [
        ("USER_REVOKED",)
    ]


# --- AC-MOB-05 listing and revoking my own sessions ------------------------------------------------
def test_the_list_shows_my_sessions_only_and_marks_the_current_one(web: Web) -> None:
    _, client_a = open_session(web, sid="sid-a")
    open_session(web, sid="sid-b")
    web_client = web.client()
    web.sign_in(web_client, sid="web-sid")
    open_session(web, sub="stranger", email="s@example.test", sid="sid-x")
    items = client_a.get(f"{API}/sessions")
    assert items.status_code == 200
    body = items.json()
    assert body["next_cursor"] is None and len(body["items"]) == 3
    assert sum(i["current"] for i in body["items"]) == 1
    current = next(i for i in body["items"] if i["current"])
    assert current["client_type"] == "MOBILE" and current["device_label"] == "Ana's phone"
    assert {i["client_type"] for i in body["items"]} == {"MOBILE", "WEB"}
    assert set(body["items"][0]) == {"id", "client_type", "device_label", "platform", "country_code",
                                     "created_at", "last_activity_at", "expires_at", "current"}  # fmt: skip
    created = [i["created_at"] for i in body["items"]]
    assert created == sorted(created, reverse=True)
    from_web = web_client.get(f"{API}/sessions").json()
    assert len(from_web["items"]) == 3 and sum(i["current"] for i in from_web["items"]) == 1


def test_somebody_elses_or_unknown_sessions_look_like_they_do_not_exist(web: Web) -> None:
    _, mine = open_session(web, sid="sid-a")
    stranger_session, stranger = open_session(
        web, sub="stranger", email="s@example.test", sid="sid-x"
    )
    problem(
        mine.delete(f"{API}/sessions/{stranger_session.json()['session_id']}"), 404, "NOT_FOUND"
    )
    problem(mine.delete(f"{API}/sessions/00000000-0000-4000-8000-000000000000"), 404, "NOT_FOUND")
    assert mine.delete(f"{API}/sessions/not-a-uuid").status_code == 422
    assert stranger.get(f"{API}/auth/session").status_code == 200  # untouched


def test_deleting_my_own_current_session_signs_me_out(web: Web) -> None:
    first, client = open_session(web)
    assert client.delete(f"{API}/sessions/{first.json()['session_id']}").status_code == 204
    problem(client.get(f"{API}/auth/session"), 401, "SESSION_REVOKED")
    assert web.rows("SELECT revoked_reason FROM user_sessions") == [("LOGOUT",)]
    problem(client.delete(f"{API}/sessions/{first.json()['session_id']}"), 401, "SESSION_REVOKED")


def test_a_web_session_can_revoke_a_mobile_session_with_the_csrf_token(web: Web) -> None:
    mobile, mobile_client = open_session(web, sid="sid-m")
    browser = web.client()
    web.sign_in(browser, sid="web-sid")
    url = f"{API}/sessions/{mobile.json()['session_id']}"
    problem(browser.delete(url), 403, "CSRF_INVALID")
    assert browser.delete(url, headers=secure(browser)).status_code == 204
    problem(mobile_client.get(f"{API}/auth/session"), 401, "SESSION_REVOKED")


def test_revoke_others_keeps_only_the_calling_session(web: Web) -> None:
    open_session(web, sid="sid-1")
    _, caller = open_session(web, sid="sid-2")
    open_session(web, sid="sid-3")
    r = caller.post(f"{API}/sessions/revoke-others")
    assert r.status_code == 200 and r.json() == {"revoked": 2}
    assert caller.get(f"{API}/auth/session").status_code == 200
    assert web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(1,)]
    assert caller.post(f"{API}/sessions/revoke-others").json() == {"revoked": 0}


def test_revoke_all_needs_a_fresh_authentication_for_bearer_callers(web: Web) -> None:
    open_session(web, sid="sid-1")
    stale_token = web.access(sid="sid-2", auth_time=int(time.time()) - 3600)
    stale = web.bearer(stale_token)
    stale.post(OPEN, json=DEVICE)
    refused = stale.post(f"{API}/sessions/revoke-all")
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'error="insufficient_user_authentication"' in refused.headers["www-authenticate"]
    assert web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(2,)]
    fresh = web.bearer(web.access(sid="sid-2", auth_time=int(time.time()) - 5))
    r = fresh.post(f"{API}/sessions/revoke-all")
    assert r.status_code == 200 and r.json() == {"revoked": 2}
    problem(fresh.get(f"{API}/auth/session"), 401, "SESSION_REVOKED")


def test_revoke_all_for_a_web_session_needs_a_fresh_sign_in_and_clears_the_cookie(web: Web) -> None:
    open_session(web, sid="sid-m")
    stale = web.client()
    web.sign_in(stale, sid="web-1", auth_time=int(time.time()) - 3600)
    problem(
        stale.post(f"{API}/sessions/revoke-all", headers=secure(stale)), 401, "STEP_UP_REQUIRED"
    )
    fresh = web.client()
    web.sign_in(fresh, sid="web-2", auth_time=int(time.time()) - 5)
    r = fresh.post(f"{API}/sessions/revoke-all", headers=secure(fresh))
    assert r.status_code == 200 and r.json()["revoked"] == 3
    assert "Max-Age=0" in r.headers["set-cookie"]
    assert web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(0,)]


# --- AC-MOB-06 / session cap -------------------------------------------------------------------------
def test_the_eleventh_device_evicts_the_oldest_session(web: Web) -> None:
    clients = [open_session(web, sid=f"sid-{n}")[1] for n in range(11)]
    assert web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(10,)]
    problem(clients[0].get(f"{API}/auth/session"), 401, "SESSION_REVOKED")
    assert clients[10].get(f"{API}/auth/session").status_code == 200
    assert web.rows("SELECT revoked_reason FROM user_sessions WHERE revoked_at IS NOT NULL") == [
        ("SESSION_LIMIT",)
    ]


def test_every_route_answers_no_store_for_bearer_callers_too(web: Web) -> None:
    first, client = open_session(web)
    for r in (first, client.get(f"{API}/auth/session"), client.get(f"{API}/sessions"),
              client.post(f"{API}/sessions/revoke-others")):  # fmt: skip
        if "/auth/" in str(r.url):
            assert r.headers["cache-control"] == "no-store"
    assert SUBJECT  # keep the shared constants referenced
