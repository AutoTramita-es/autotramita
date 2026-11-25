"""F2-T09-REC F-3 and F-2 through the application, on real PostgreSQL 16 and Redis 7 with a fake
identity provider.

F-3: what an account action needs follows from the account. Without a second factor a fresh
password is enough; with any second factor the fresh authentication must have proven it.
F-2: a step-up counts from the authentication that really happened, for at most ten minutes."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.auth.idp import SECOND_FACTOR_TYPES, IdpCredential
from app.auth.security.notify import NoticeKind
from fastapi.testclient import TestClient
from tests.auth.fake_idp import DROP
from tests.auth.security.test_email_change_api import enable
from tests.auth.security.test_security_policies import API, EMAIL, SUB, Rig, problem, secure
from tests.auth.web_harness import SESSION_COOKIE

pytest_plugins = ["tests.auth.security.test_security_policies"]

FACTORS = sorted(SECOND_FACTOR_TYPES)


def now() -> int:
    return int(time.time())


@pytest.fixture(autouse=True)
def real_clock(rig: Rig) -> None:
    """Token times in these tests are ages relative to the real clock."""
    rig.web.clock.now = time.time()


def enrolled(rig: Rig, kind: str = "otp") -> None:
    rig.admin.credentials[SUB] = [
        IdpCredential("c-pw", "password", 1),
        IdpCredential("c-factor", kind, 2),
    ]


def evidence(factor_age: int | None, auth_age: int = 5) -> dict[str, Any]:
    """Claims of an authentication ``auth_age`` seconds ago; ``factor_age`` seconds since a
    second factor was proven (``None``: a password only)."""
    claims: dict[str, Any] = {"auth_time": now() - auth_age, "iat": now() - 1, "exp": now() + 290}
    if factor_age is None:
        return {**claims, "acr": "loa1"}
    times = {"1": now() - auth_age, "2": now() - factor_age}
    return {**claims, "acr": "loa2", "loa_map": json.dumps(times)}


def signed_in(rig: Rig, factor_age: int | None = None, auth_age: int = 5, **kw: Any) -> TestClient:
    return rig.login(**evidence(factor_age, auth_age), **kw)


def post(client: TestClient, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
    response: httpx.Response = client.post(
        f"{API}{path}", headers=secure(client), json=body if body is not None else {}
    )
    return response


ACTIONS: dict[str, Callable[[TestClient], httpx.Response]] = {
    "password_change": lambda c: post(c, "/me/security/password-change-requests"),
    "enrol_totp": lambda c: post(c, "/me/security/mfa-enrollment-requests", {"factor": "TOTP"}),
    "enrol_codes": lambda c: post(
        c, "/me/security/mfa-enrollment-requests", {"factor": "RECOVERY_CODES"}
    ),
    "email_request": lambda c: post(
        c, "/me/security/email-change-requests", {"new_email": "new@example.test"}
    ),
    "email_confirm": lambda c: post(
        c,
        "/me/security/email-change-confirmations",
        {"operation_id": "00000000-0000-4000-8000-000000000000", "token": "t" * 43},
    ),
    "revoke_all": lambda c: post(c, "/sessions/revoke-all"),
}


def untouched(rig: Rig, sink: Any) -> None:
    assert rig.web.rows("SELECT count(*) FROM email_change_operations") == [(0,)]
    assert sink.links == [] and rig.admin.deleted == [] and rig.admin.sent == []
    assert rig.web.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NOT NULL") == [(0,)]


# --- F-3: the level follows from the account ---------------------------------------------------
@pytest.mark.parametrize("action", sorted(ACTIONS))
@pytest.mark.parametrize("kind", FACTORS)
def test_with_a_second_factor_a_password_alone_is_refused(rig: Rig, kind: str, action: str) -> None:
    sink = enable(rig)
    client = signed_in(rig)
    enrolled(rig, kind)
    refused = ACTIONS[action](client)
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa2"' in refused.headers["www-authenticate"]
    untouched(rig, sink)


@pytest.mark.parametrize("action", sorted(ACTIONS))
@pytest.mark.parametrize("kind", FACTORS)
def test_with_a_second_factor_proven_the_action_is_open(rig: Rig, kind: str, action: str) -> None:
    enable(rig)
    client = signed_in(rig, factor_age=30)
    enrolled(rig, kind)
    answer = ACTIONS[action](client)
    assert answer.status_code in (200, 202), answer.text
    if "redirect_url" in answer.json():
        query = parse_qs(urlparse(answer.json()["redirect_url"]).query)
        assert query["acr_values"] == ["loa2"]


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_without_a_second_factor_a_fresh_password_is_enough(rig: Rig, action: str) -> None:
    enable(rig)
    client = signed_in(rig)
    answer = ACTIONS[action](client)
    assert answer.status_code in (200, 202), answer.text
    if "redirect_url" in answer.json():
        assert "acr_values" not in parse_qs(urlparse(answer.json()["redirect_url"]).query)


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_without_a_second_factor_a_stale_password_is_refused(rig: Rig, action: str) -> None:
    sink = enable(rig)
    client = signed_in(rig, auth_age=605)
    refused = ACTIONS[action](client)
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa1"' in refused.headers["www-authenticate"]
    untouched(rig, sink)


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_when_the_provider_cannot_say_nothing_happens(rig: Rig, action: str) -> None:
    sink = enable(rig)
    client = signed_in(rig, factor_age=5)
    rig.admin.down = True
    problem(ACTIONS[action](client), 503, "IDENTITY_PROVIDER_UNAVAILABLE")
    untouched(rig, sink)
    rig.admin.down = False
    rig.web.runtime.admin = None
    refused = ACTIONS[action](client)
    problem(refused, 503, "AUTH_NOT_CONFIGURED")
    untouched(rig, sink)


def test_confirming_an_address_needs_the_factor_enrolled_since_the_request(rig: Rig) -> None:
    sink = enable(rig)
    client = signed_in(rig)
    assert ACTIONS["email_request"](client).status_code == 202
    _, _, operation, token = sink.links[0]
    enrolled(rig)  # the person set up a second factor before opening the link
    body = {"operation_id": str(operation), "token": token}
    path = "/me/security/email-change-confirmations"
    problem(post(client, path, body), 401, "STEP_UP_REQUIRED")
    assert rig.web.rows("SELECT status FROM email_change_operations") == [("PENDING",)]
    proven = signed_in(rig, factor_age=5)
    assert post(proven, path, body).status_code == 202
    assert rig.web.rows("SELECT status FROM email_change_operations") == [("CONFIRMED",)]


def test_recovering_a_forgotten_password_needs_no_second_factor(rig: Rig) -> None:
    signed_in(rig)
    enrolled(rig)
    answer = rig.web.client().post(f"{API}/auth/password-recovery", json={"email": EMAIL})
    assert answer.status_code == 202
    assert [(s[0], s[1]) for s in rig.admin.sent] == [(SUB, ("UPDATE_PASSWORD",))]


# --- F-3: what comes back from the provider ----------------------------------------------------
def returned(
    rig: Rig, client: TestClient, action: str, created: str, **claims: Any
) -> httpx.Response:
    started = ACTIONS[action](client)
    assert started.status_code == 200, started.text
    query = {k: v[0] for k, v in parse_qs(urlparse(started.json()["redirect_url"]).query).items()}
    rig.admin.credentials[SUB].append(IdpCredential("c-new", created, (now() + 1) * 1000))
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid="s-action", **claims)
    done: httpx.Response = client.get(
        f"{API}/auth/callback",
        params={"code": code, "state": query["state"], "kc_action_status": "success"},
    )
    return done


@pytest.mark.parametrize(
    ("action", "created", "audit_action", "notice"),
    [
        ("password_change", "password", "security.password.changed", NoticeKind.PASSWORD_CHANGED),
        ("enrol_codes", "recovery-authn-codes", "security.mfa.enrolled", NoticeKind.MFA_ENROLLED),
    ],
)
@pytest.mark.parametrize(
    "factor_age", [None, 700], ids=["password_only", "factor_proven_too_long_ago"]
)
def test_a_change_made_without_the_existing_factor_ends_every_session(
    rig: Rig, action: str, created: str, audit_action: str, notice: NoticeKind, factor_age: Any
) -> None:
    """The provider does not guard its password form and the browser can drop ``acr_values``:
    the application notices on the way back and trusts nothing from before."""
    other = signed_in(rig, factor_age=20, sid="other")
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    done = returned(rig, client, action, created, **evidence(factor_age))
    assert done.status_code == 302
    assert done.headers["location"] == "/?security_action=reauthentication_required"
    assert f"{SESSION_COOKIE}=" in done.headers["set-cookie"]
    assert "Max-Age=0" in done.headers["set-cookie"]
    assert rig.live_sessions() == 0
    for browser in (client, other):
        assert browser.get(f"{API}/auth/session").status_code == 401
    assert [n.kind for n in rig.notifier.notices] == [notice]
    assert rig.audit(audit_action)[0][0] == "SUCCESS"  # it did happen at the provider
    assert rig.audit("security.step_up.failed")[0][0] == "FAILURE"


def test_a_change_made_with_the_factor_keeps_this_session(rig: Rig) -> None:
    other = signed_in(rig, factor_age=20, sid="other")
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    done = returned(rig, client, "password_change", "password", **evidence(10))
    assert done.headers["location"] == "/?security_action=success"
    assert client.get(f"{API}/auth/session").status_code == 200
    assert other.get(f"{API}/auth/session").status_code == 401
    assert rig.audit("security.step_up.failed") == []


# --- F-2: ten minutes from the real authentication ---------------------------------------------
def remove_factor(client: TestClient) -> httpx.Response:
    response: httpx.Response = client.delete(
        f"{API}/me/security/second-factors/c-factor", headers=secure(client)
    )
    return response


@pytest.mark.parametrize(("age", "allowed"), [(590, True), (605, False)])
def test_the_factor_counts_for_ten_minutes_whatever_the_password_age(
    rig: Rig, age: int, allowed: bool
) -> None:
    # the password was typed seconds ago in both cases: it does not renew the factor
    client = signed_in(rig, factor_age=age, auth_age=2)
    enrolled(rig)
    removed = remove_factor(client)
    assert (removed.status_code == 204) is allowed, removed.text
    changed = ACTIONS["password_change"](client)
    assert (changed.status_code == 200) is allowed, changed.text


def test_single_sign_on_does_not_extend_the_window(rig: Rig) -> None:
    """The session opens now, but the factor was proven nine minutes ago."""
    proven = now() - 540
    client = signed_in(rig, factor_age=540)
    info = client.get(f"{API}/auth/session").json()
    assert info["auth_level"] == "LOA2"
    until = datetime.fromisoformat(info["step_up_expires_at"]).timestamp()
    assert abs(until - (proven + 600)) <= 2


def test_level_two_without_the_factor_time_is_level_one(rig: Rig) -> None:
    client = rig.login(**{**evidence(5), "loa_map": DROP})
    enrolled(rig)
    assert client.get(f"{API}/auth/session").json()["auth_level"] == "LOA1"
    problem(remove_factor(client), 401, "STEP_UP_REQUIRED")
    assert rig.admin.deleted == []


def step_up(rig: Rig, client: TestClient, purpose: str, **claims: Any) -> httpx.Response:
    asked = post(client, "/auth/step-up", {"purpose": purpose, "return_to": "/me"})
    query = {k: v[0] for k, v in parse_qs(urlparse(asked.json()["redirect_url"]).query).items()}
    assert query["prompt"] == "login"
    sid = rig.web.rows("SELECT kc_session_id FROM user_sessions")[0][0]
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid=sid, **claims)
    done: httpx.Response = client.get(
        f"{API}/auth/callback", params={"code": code, "state": query["state"]}
    )
    return done


@pytest.mark.parametrize("age", [120, 599], ids=["two_minutes", "almost_ten"])
def test_a_step_up_answered_from_single_sign_on_is_refused(rig: Rig, age: int) -> None:
    client = signed_in(rig)
    enrolled(rig)
    refused = step_up(rig, client, "MFA", **evidence(age))
    problem(refused, 400, "AUTH_CALLBACK_REJECTED")
    info = client.get(f"{API}/auth/session").json()
    assert info["auth_level"] == "LOA1" and info["step_up_expires_at"] is None
    problem(remove_factor(client), 401, "STEP_UP_REQUIRED")


def test_a_real_step_up_opens_the_window_from_the_factor_time(rig: Rig) -> None:
    client = signed_in(rig, auth_age=3600)
    enrolled(rig)
    problem(remove_factor(client), 401, "STEP_UP_REQUIRED")
    proven = now()
    assert step_up(rig, client, "MFA", **evidence(0, 0)).status_code == 302
    info = client.get(f"{API}/auth/session").json()
    until = datetime.fromisoformat(info["step_up_expires_at"]).timestamp()
    assert info["auth_level"] == "LOA2" and abs(until - (proven + 600)) <= 2
    assert remove_factor(client).status_code == 204


def test_a_password_re_entry_does_not_bring_back_level_two(rig: Rig) -> None:
    client = signed_in(rig, factor_age=700, auth_age=700)
    enrolled(rig)
    claims = evidence(700, 0)  # new password sign-in, the factor time stays old
    assert step_up(rig, client, "REAUTHENTICATE", **{**claims, "acr": "loa1"}).status_code == 302
    assert client.get(f"{API}/auth/session").json()["auth_level"] == "LOA1"
    problem(remove_factor(client), 401, "STEP_UP_REQUIRED")


def test_a_refreshed_bearer_token_does_not_renew_the_step_up(rig: Rig) -> None:
    enrolled(rig)

    def app(**claims: Any) -> TestClient:
        token = rig.web.access(sub=SUB, email=EMAIL, sid="phone", **claims)
        return rig.web.bearer(token)

    first = app(**evidence(595))
    assert first.post(f"{API}/auth/mobile/session", json={}).status_code == 201
    assert first.post(f"{API}/me/security/password-change-requests", json={}).status_code == 200
    # six seconds later the app refreshed: new iat and exp, same authentication times
    claims = evidence(606)
    refreshed = app(**{**claims, "iat": now(), "exp": now() + 300})
    for answer in (
        refreshed.post(f"{API}/me/security/password-change-requests", json={}),
        refreshed.delete(f"{API}/me/security/second-factors/c-factor"),
        refreshed.post(f"{API}/sessions/revoke-all"),
    ):
        problem(answer, 401, "STEP_UP_REQUIRED")
    assert rig.admin.deleted == [] and rig.live_sessions() == 1
