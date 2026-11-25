"""F2-T09 / AC-POL-03..06, 10..12, 14: recovery, verification resend, password change, second
factors and notices on real PostgreSQL 16 and Redis 7, with a fake identity provider, a fake
admin API and a recording notifier. The real Keycloak is exercised in tests/identity."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.auth.idp import IdpCredential
from app.auth.security import recovery as recovery_module
from app.auth.security.markers import RecoveryMarkers
from app.auth.security.notify import NoticeKind
from app.auth.web.csrf import csrf_token
from app.core.ratelimit import create_redis
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.auth.fake_admin import FakeAdmin, RecordingNotifier
from tests.auth.fake_idp import NOW
from tests.auth.web_harness import ORIGIN_WEB, SESSION_COOKIE, Web, build_web
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

API = "/api/v1"
SUB = "sub-p"
EMAIL = "p@example.test"


class Rig:
    def __init__(self, web: Web, admin: FakeAdmin, notifier: RecordingNotifier) -> None:
        self.web, self.admin, self.notifier = web, admin, notifier

    def login(
        self, sub: str = SUB, email: str = EMAIL, sid: str | None = None, **kw: Any
    ) -> TestClient:
        client = self.web.client()
        response = self.web.sign_in(
            client, sub=sub, email=email, sid=sid or f"sid-{time.time_ns()}", **kw
        )
        assert response.status_code == 302, response.text
        return client

    def audit(self, action: str) -> list[tuple[Any, ...]]:
        return self.web.rows(
            "SELECT outcome, actor_type, subject_user_id IS NOT NULL FROM audit_events "
            "WHERE action = :a ORDER BY occurred_at",
            a=action,
        )

    def live_sessions(self) -> int:
        return int(
            self.web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL")[0][0]
        )


def secure(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(client.cookies[SESSION_COOKIE]), "Origin": ORIGIN_WEB}


def problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


@pytest.fixture
def rig(role_env: RoleEnv, redis_url: str) -> Iterator[Rig]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    web = build_web(role_env, redis_url, AUTH_SECURITY_HMAC_KEY="k" * 32)
    admin, notifier = FakeAdmin(), RecordingNotifier()
    web.runtime.admin, web.runtime.notifier = admin, notifier
    web.runtime.markers = RecoveryMarkers(create_redis(redis_url), namespace=f"m{id(web)}")
    admin.add(EMAIL, SUB)
    yield Rig(web, admin, notifier)
    web.close()


def anonymous(rig: Rig) -> TestClient:
    return rig.web.client()


# --- AC-POL-03/04 recovery: same answer for every account, per-account and per-IP limits -------
def test_recovery_answers_every_account_the_same_way(rig: Rig) -> None:
    rig.login()  # the known, active person
    rig.admin.add("gone@example.test", "sub-gone", enabled=False)
    rig.login("sub-d", "dead@example.test")  # known to the application, then deactivated
    rig.admin.add("dead@example.test", "sub-d")
    with rig.web.env.admin_engine().begin() as c:
        c.execute(
            text(
                "UPDATE users SET status='DEACTIVATED', version = version + 1 WHERE auth_subject='sub-d'"
            )
        )
    answers = {}
    for key, address in {
        "active": EMAIL,
        "unknown": "nobody@example.test",
        "disabled": "gone@example.test",
        "deactivated": "dead@example.test",
        "spaced": "  P@Example.TEST ",
    }.items():
        r = anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": address})
        answers[key] = (
            r.status_code,
            r.json(),
            r.headers["content-type"],
            r.headers.get("cache-control"),
            sorted(h for h in r.headers if not h.startswith(("x-request-id", "ratelimit", "date"))),
        )
    assert len({repr(v) for v in answers.values()}) == 1, answers
    assert answers["active"][:2] == (202, {"status": "accepted"})
    # only the active account got a message (the second request for it was the normalised twin)
    assert [s[0] for s in rig.admin.sent] == [SUB, SUB]
    assert all(s[1] == ("UPDATE_PASSWORD",) and s[2] == 1800 for s in rig.admin.sent)


def test_recovery_does_no_account_dependent_work_before_answering(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    deferred: list[str] = []
    monkeypatch.setattr(
        recovery_module, "process_recovery", lambda rt, email, **kw: deferred.append(email)
    )
    for address in (EMAIL, "nobody@example.test"):
        assert (
            anonymous(rig)
            .post(f"{API}/auth/password-recovery", json={"email": address})
            .status_code
            == 202
        )
    assert rig.admin.calls == [] and len(deferred) == 2  # look-ups and mail happen afterwards


def test_a_fourth_recovery_request_in_an_hour_sends_nothing_and_looks_the_same(rig: Rig) -> None:
    rig.login()
    answers = [
        anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
        for _ in range(4)
    ]
    assert [a.status_code for a in answers] == [202] * 4
    assert len({a.text for a in answers}) == 1
    assert len(rig.admin.sent) == 3
    assert [r[0] for r in rig.audit("security.password.recovery.limited")] == ["DENIED"]
    other = anonymous(rig).post(
        f"{API}/auth/password-recovery", json={"email": "other@example.test"}
    )
    assert other.status_code == 202  # another account has its own counter


def test_recovery_is_limited_per_address_of_the_caller_too(rig: Rig) -> None:
    codes = [
        anonymous(rig)
        .post(f"{API}/auth/password-recovery", json={"email": f"u{i}@example.test"})
        .status_code
        for i in range(11)
    ]
    assert codes == [202] * 10 + [429]


def test_recovery_refuses_malformed_input_and_fails_closed_without_redis_or_key(
    rig: Rig, role_env: RoleEnv, redis_url: str
) -> None:
    assert (
        anonymous(rig)
        .post(f"{API}/auth/password-recovery", json={"email": "not-an-address"})
        .status_code
        == 422
    )
    assert anonymous(rig).post(f"{API}/auth/password-recovery", json={}).status_code == 422
    broken = build_web(
        role_env,
        redis_url,
        redis_for_limiter="redis://127.0.0.1:1/0",
        AUTH_SECURITY_HMAC_KEY="k" * 32,
    )
    try:
        r = broken.client().post(f"{API}/auth/password-recovery", json={"email": EMAIL})
        assert r.status_code == 503 and r.json()["code"] == "RATE_LIMIT_UNAVAILABLE"
    finally:
        broken.close()
    keyless = build_web(role_env, redis_url)
    try:
        r = keyless.client().post(f"{API}/auth/password-recovery", json={"email": EMAIL})
        assert r.status_code == 503 and r.json()["code"] == "AUTH_NOT_CONFIGURED"
    finally:
        keyless.close()


def test_an_identity_provider_outage_is_invisible_to_the_caller_and_leaves_no_marker(
    rig: Rig,
) -> None:
    rig.admin.down = True
    r = anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    assert r.status_code == 202 and r.json() == {"status": "accepted"}
    assert rig.admin.sent == []


def test_the_limiter_key_is_an_hmac_and_no_address_reaches_redis_or_the_audit_log(
    rig: Rig, redis_url: str
) -> None:
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    client = create_redis(redis_url)
    keys = [k for k in client.keys("*") if "auth_recovery_account" in k]
    assert keys and not any("example" in k or "p@" in k for k in keys)
    dump = str(rig.web.rows("SELECT details::text, ip_prefix FROM audit_events"))
    assert "example.test" not in dump


# --- AC-POL-05 a reset ends every other session, once the password really changed ---------------
def test_a_completed_reset_ends_other_sessions_at_the_next_sign_in_and_says_so(rig: Rig) -> None:
    first, second = rig.login(sid="s1"), rig.login(sid="s2")
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 60) * 1000))]
    third = rig.login(sid="s3", auth_time=int(NOW + 61))  # authenticated with the new password
    assert first.get(f"{API}/auth/session").status_code == 401
    assert second.get(f"{API}/auth/session").status_code == 401
    assert third.get(f"{API}/auth/session").status_code == 200
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.PASSWORD_RESET_COMPLETED]
    assert rig.notifier.notices[0].to == EMAIL
    assert rig.audit("security.password.changed")[0][0] == "SUCCESS"
    revoked = rig.web.rows(
        "SELECT revoked_reason, count(*) FROM user_sessions WHERE revoked_at IS NOT NULL GROUP BY 1"
    )
    assert ("PASSWORD_CHANGED", 2) in revoked
    assert rig.web.rows(
        "SELECT details->>'revoked_reason' FROM audit_events WHERE action = 'session.revoked'"
    ) == [("CREDENTIAL_CHANGED",)]
    rig.login(sid="s4", auth_time=int(NOW + 62))  # handled: a later sign-in revokes nothing more
    assert third.get(f"{API}/auth/session").status_code == 200
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.PASSWORD_RESET_COMPLETED]


@pytest.mark.parametrize("first_after_reset", ["old_sso", "fresh"])
def test_a_sign_on_session_older_than_the_new_password_cannot_open_the_application(
    rig: Rig, first_after_reset: str
) -> None:
    """A single sign-on session that survived the reset must be asked for the password again,
    whether it is the first to come back or comes after the owner already signed in."""
    before = rig.login(sid="s1")
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 60) * 1000))]
    owner = None
    if first_after_reset == "fresh":
        owner = rig.login(sid="s2", auth_time=int(NOW + 61))
    attacker = rig.web.client()
    refused = rig.web.sign_in(attacker, sub=SUB, email=EMAIL, sid="s1")  # auth_time is old
    assert refused.status_code == 302
    location = urlparse(refused.headers["location"])
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert query["prompt"] == "login" and query["max_age"] == "0"
    assert SESSION_COOKIE not in attacker.cookies
    assert before.get(f"{API}/auth/session").status_code == 401
    assert rig.live_sessions() == (1 if owner else 0)
    if owner:
        assert owner.get(f"{API}/auth/session").status_code == 200
    # a second stale answer to the forced sign-in is refused, never looped
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid="s1")
    again = attacker.get(f"{API}/auth/callback", params={"code": code, "state": query["state"]})
    problem(again, 400, "AUTH_CALLBACK_REJECTED")
    assert rig.live_sessions() == (1 if owner else 0)


def test_the_forced_sign_in_with_the_new_password_succeeds(rig: Rig) -> None:
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 60) * 1000))]
    client = rig.web.client()
    refused = rig.web.sign_in(client, sub=SUB, email=EMAIL, sid="s1")
    query = {k: v[0] for k, v in parse_qs(urlparse(refused.headers["location"]).query).items()}
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid="s1", auth_time=int(NOW + 65))
    done = client.get(f"{API}/auth/callback", params={"code": code, "state": query["state"]})
    assert done.status_code == 302 and done.headers["location"] == "/"
    assert client.get(f"{API}/auth/session").status_code == 200


def test_asking_for_recovery_again_does_not_hide_a_change_that_already_happened(rig: Rig) -> None:
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 60) * 1000))]
    rig.web.clock.now = NOW + 120
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    refused = rig.web.sign_in(rig.web.client(), sub=SUB, email=EMAIL, sid="s1")
    assert "prompt=login" in refused.headers["location"]
    assert rig.live_sessions() == 0


def test_requesting_recovery_alone_does_not_end_anybodys_session(rig: Rig) -> None:
    first = rig.login(sid="s1")
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.credentials[SUB] = [
        IdpCredential("c-pw", "password", int((NOW - 3600) * 1000))
    ]  # old
    rig.login(sid="s2")
    assert first.get(f"{API}/auth/session").status_code == 200 and rig.notifier.notices == []


def test_an_identity_provider_outage_at_sign_in_postpones_the_check_but_never_blocks_login(
    rig: Rig,
) -> None:
    first = rig.login(sid="s1")
    anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    rig.admin.down = True
    assert rig.login(sid="s2").get(f"{API}/auth/session").status_code == 200
    assert first.get(f"{API}/auth/session").status_code == 200
    rig.admin.down = False
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 60) * 1000))]
    rig.login(sid="s3")  # the marker survived the outage
    assert first.get(f"{API}/auth/session").status_code == 401


# --- verification resend ---------------------------------------------------------------------
def test_verification_resend_is_always_202_limited_and_only_sends_to_the_unverified(
    rig: Rig,
) -> None:
    pending = rig.login("sub-n", "n@example.test", verified=False)
    verified = rig.login()
    answers = [
        pending.post(f"{API}/me/email-verification", headers=secure(pending)) for _ in range(4)
    ]
    assert [a.status_code for a in answers] == [202] * 4 and len({a.text for a in answers}) == 1
    assert [s[1] for s in rig.admin.sent] == [("VERIFY_EMAIL",)] * 3
    same = verified.post(f"{API}/me/email-verification", headers=secure(verified))
    assert same.status_code == 202 and same.text == answers[0].text and len(rig.admin.sent) == 3
    assert anonymous(rig).post(f"{API}/me/email-verification").status_code == 401


# --- AC-POL-06/10 password change and second factors need a fresh authentication ---------------
def start(client: TestClient, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
    response: httpx.Response = client.post(
        f"{API}/me/security/{path}", json=body or {"return_to": "/me"}, headers=secure(client)
    )
    return response


def come_back(
    rig: Rig, client: TestClient, started: httpx.Response, **claims: Any
) -> httpx.Response:
    """What Keycloak does after the action: redirect to the callback with a code (and the status)."""
    query = {k: v[0] for k, v in parse_qs(urlparse(started.json()["redirect_url"]).query).items()}
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid="s-action")
    params = {"code": code, "state": query["state"], **claims}
    done: httpx.Response = client.get(f"{API}/auth/callback", params=params)
    return done


def test_password_change_asks_keycloak_and_ends_other_sessions_only_when_a_new_password_exists(
    rig: Rig,
) -> None:
    other = rig.login(sid="other")
    client = rig.login(sid="s-action")
    started = start(client, "password-change-requests")
    assert started.status_code == 200, started.text
    url = urlparse(started.json()["redirect_url"])
    assert parse_qs(url.query)["kc_action"] == ["UPDATE_PASSWORD"]
    assert started.headers["cache-control"] == "no-store"
    # a forged "success" without a new password in Keycloak changes nothing
    forged = come_back(rig, client, started, kc_action_status="success")
    assert forged.headers["location"] == "/me?security_action=cancelled"
    assert other.get(f"{API}/auth/session").status_code == 200 and rig.notifier.notices == []
    # the real thing: Keycloak now holds a password created after the flow started
    started = start(client, "password-change-requests")
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", int((NOW + 5) * 1000))]
    old_cookie = client.cookies[SESSION_COOKIE]
    done = come_back(rig, client, started, kc_action_status="success")
    assert done.headers["location"] == "/me?security_action=success"
    assert other.get(f"{API}/auth/session").status_code == 401
    assert client.cookies[SESSION_COOKIE] != old_cookie  # rotated
    assert client.get(f"{API}/auth/session").status_code == 200
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.PASSWORD_CHANGED]
    assert rig.audit("security.password.changed")[0][0] == "SUCCESS"


def test_a_cancelled_action_changes_nothing(rig: Rig) -> None:
    client = rig.login(sid="s-action")
    started = start(client, "mfa-enrollment-requests", {"factor": "TOTP", "return_to": "/me"})
    assert parse_qs(urlparse(started.json()["redirect_url"]).query)["kc_action"] == [
        "CONFIGURE_TOTP"
    ]
    done = come_back(rig, client, started, kc_action_status="cancelled")
    assert done.headers["location"] == "/me?security_action=cancelled"
    assert rig.notifier.notices == [] and rig.audit("security.mfa.enrolled") == []


def test_second_factor_enrolment_is_proven_by_the_provider_and_noticed(rig: Rig) -> None:
    client = rig.login(sid="s-action")
    started = start(
        client, "mfa-enrollment-requests", {"factor": "RECOVERY_CODES", "return_to": "/me"}
    )
    assert parse_qs(urlparse(started.json()["redirect_url"]).query)["kc_action"] == [
        "CONFIGURE_RECOVERY_AUTHN_CODES"
    ]
    rig.admin.credentials[SUB] = [
        IdpCredential("c-rc", "recovery-authn-codes", int((NOW + 5) * 1000))
    ]
    done = come_back(rig, client, started, kc_action_status="success")
    assert done.headers["location"] == "/me?security_action=success"
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.MFA_ENROLLED]
    assert rig.audit("security.mfa.enrolled")[0][0] == "SUCCESS"
    assert rig.web.rows(
        "SELECT details->>'factor' FROM audit_events WHERE action='security.mfa.enrolled'"
    ) == [("RECOVERY_CODES",)]


def test_a_one_time_code_set_up_on_the_way_to_recovery_codes_is_audited_too(rig: Rig) -> None:
    """The provider first has a person without a factor set one up (no codes-only accounts)."""
    client = rig.login(sid="s-action")
    started = start(
        client, "mfa-enrollment-requests", {"factor": "RECOVERY_CODES", "return_to": "/me"}
    )
    rig.admin.credentials[SUB] = [
        IdpCredential("c-otp", "otp", int((NOW + 4) * 1000)),
        IdpCredential("c-rc", "recovery-authn-codes", int((NOW + 5) * 1000)),
    ]
    done = come_back(rig, client, started, kc_action_status="success")
    assert done.headers["location"] == "/me?security_action=success"
    assert sorted(
        rig.web.rows(
            "SELECT details->>'factor' FROM audit_events WHERE action='security.mfa.enrolled'"
        )
    ) == [("RECOVERY_CODES",), ("TOTP",)]


def test_a_callback_for_somebody_elses_session_or_subject_is_refused(rig: Rig) -> None:
    victim = rig.login(sid="s-action")
    started = start(victim, "password-change-requests")
    query = {k: v[0] for k, v in parse_qs(urlparse(started.json()["redirect_url"]).query).items()}
    code = rig.web.code_for(query, sub="sub-attacker", email="a@example.test", sid="s-x")
    done = victim.get(
        f"{API}/auth/callback",
        params={"code": code, "state": query["state"], "kc_action_status": "success"},
    )
    assert done.status_code == 400 and done.json()["code"] == "AUTH_CALLBACK_REJECTED"


def test_sensitive_actions_need_a_fresh_authentication_and_second_factor_removal_needs_loa2(
    rig: Rig,
) -> None:
    stale = rig.web.client()
    rig.web.sign_in(stale, sub=SUB, email=EMAIL, sid="s-old", auth_time=int(time.time()) - 3600)
    refused = start(stale, "password-change-requests")
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa1"' in refused.headers["www-authenticate"]
    problem(start(stale, "mfa-enrollment-requests"), 401, "STEP_UP_REQUIRED")
    password_only = rig.login(sid="s-lo")
    rig.admin.credentials[SUB] = [IdpCredential("c-otp", "otp", 1)]
    gone = password_only.delete(
        f"{API}/me/security/second-factors/c-otp", headers=secure(password_only)
    )
    problem(gone, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa2"' in gone.headers["www-authenticate"]
    assert rig.admin.deleted == []


def test_removing_a_second_factor_deletes_it_audits_and_notices_and_never_touches_other_credentials(
    rig: Rig,
) -> None:
    client = rig.web.client()
    rig.web.sign_in(client, sub=SUB, email=EMAIL, sid="s-mfa", acr="loa2")
    rig.admin.credentials[SUB] = [
        IdpCredential("c-pw", "password", 1),
        IdpCredential("c-otp", "otp", 2),
    ]
    refused = client.delete(f"{API}/me/security/second-factors/c-pw", headers=secure(client))
    problem(refused, 404, "NOT_FOUND")  # a password is not a second factor
    problem(
        client.delete(f"{API}/me/security/second-factors/unknown", headers=secure(client)),
        404,
        "NOT_FOUND",
    )
    assert rig.admin.deleted == []
    done = client.delete(f"{API}/me/security/second-factors/c-otp", headers=secure(client))
    assert done.status_code == 204 and rig.admin.deleted == [(SUB, "c-otp")]
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.MFA_REMOVED]
    assert rig.web.rows(
        "SELECT details->>'factor' FROM audit_events WHERE action='security.mfa.removed'"
    ) == [("TOTP",)]
    assert (
        client.delete(f"{API}/me/security/second-factors/c-otp", headers=secure(client)).status_code
        == 404
    )


def test_the_security_overview_lists_factors_without_any_secret(rig: Rig) -> None:
    client = rig.login()
    rig.admin.credentials[SUB] = [
        IdpCredential("c-pw", "password", 1_700_000_000_000),
        IdpCredential("c-otp", "otp", 1_700_000_100_000),
    ]
    body = client.get(f"{API}/me/security").json()
    assert body["email_verified"] is True and body["password_changed_at"].startswith("2023-11-14")
    assert body["second_factors"] == [
        {"id": "c-otp", "type": "otp", "created_at": "2023-11-14T22:15:00Z"}
    ]
    rig.admin.down = True
    problem(client.get(f"{API}/me/security"), 503, "IDENTITY_PROVIDER_UNAVAILABLE")


def test_security_requests_are_limited_per_person(rig: Rig) -> None:
    client = rig.login(sid="s-action")
    codes = [start(client, "password-change-requests").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_unconfigured_admin_client_answers_503_not_a_guess(rig: Rig) -> None:
    client = rig.login()
    rig.web.runtime.admin = None
    problem(client.get(f"{API}/me/security"), 503, "AUTH_NOT_CONFIGURED")
    assert re.fullmatch(r"[a-z-]+", "ok")


def test_revoking_other_sessions_sends_one_notice_after_commit(rig: Rig) -> None:
    first = rig.login(sid="notice-first", auth_time=int(time.time()) - 5)
    second = rig.login(sid="notice-second", auth_time=int(time.time()) - 5)
    result = first.post(f"{API}/sessions/revoke-others", headers=secure(first))
    assert result.status_code == 200 and result.json() == {"revoked": 1}
    assert second.get(f"{API}/auth/session").status_code == 401
    assert [notice.kind for notice in rig.notifier.notices] == [NoticeKind.SESSIONS_REVOKED]
    assert first.post(f"{API}/sessions/revoke-others", headers=secure(first)).json() == {
        "revoked": 0
    }
    assert len(rig.notifier.notices) == 1
    result = first.post(f"{API}/sessions/revoke-all", headers=secure(first))
    assert result.status_code == 200 and result.json() == {"revoked": 1}
    assert [notice.kind for notice in rig.notifier.notices] == [
        NoticeKind.SESSIONS_REVOKED,
        NoticeKind.SESSIONS_REVOKED,
    ]
