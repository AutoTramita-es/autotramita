"""F2-T09-REC F-1R, F-2 and F-3 against real Keycloak 26.8.2, with the application on real
PostgreSQL and Redis where it takes part. Runs only in the ``keycloak`` CI job.

The final MFA decision (2026-11-25): whoever has a second factor proves it with the password,
credentials cannot be removed at the provider, and the password-only sign-in stays only for
people who never set up a factor. Recovery codes and older accounts are in
``test_recovery_codes_keycloak.py``.

The two tests at the end were open findings (F-1R-C, the rest of F-3K) until the Keycloak
security provider; they now assert the protection."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from app.auth.security import recovery
from app.auth.security.recovery_worker import EmailChangeRecoveryWorker
from app.core.db import create_session_factory
from tests.identity.accounts import (
    CODES,
    OTP,
    PASSKEY,
    PASSWORDLESS,
    Account,
    account,
    codes_only_account,
    set_up_otp,
    shown,
)
from tests.identity.kc import (
    MOBILE_REDIRECT,
    REALM,
    WEB_REDIRECT,
    Admin,
    Browser,
    Env,
    Page,
    SmtpSink,
    TestUser,
    decode_jwt,
    form_action,
    hidden_inputs,
    totp,
)
from tests.identity.rig import API as AUTH_API
from tests.identity.rig import ORIGIN, Rig
from tests.identity.test_reconciliation_keycloak import reset_password, wait_for
from tests.identity.test_security_keycloak import NEW_PASSWORD, mail_link, secure, settings_admin
from tests.identity.webauthn import authenticate

pytestmark = pytest.mark.keycloak

API = "/api/v1"
ASKED = (OTP, CODES, PASSKEY)
ACCOUNTS = {
    "totp": (OTP,),
    "passkey": (PASSKEY,),
    "passwordless_passkey": (PASSWORDLESS,),
    "totp_and_codes": (OTP, CODES),
    "totp_and_passkey": (OTP, PASSKEY),
    "passkey_and_codes": (PASSKEY, CODES),
}
OLDER = "recovery_codes_only"  # cannot be created any more; refused, waits for recovery
EVERY = sorted([*ACCOUNTS, OLDER])
CLIENTS = {"at-web": WEB_REDIRECT, "at-mobile": MOBILE_REDIRECT}


def make(admin: Admin, name: str) -> Account:
    if name == OLDER:
        return codes_only_account(admin, marked=True)
    return account(admin, *ACCOUNTS[name])


def refused_or_asked(name: str, page: Page) -> None:
    """The password alone is answered with the question for an existing permanent factor, or,
    for an account holding recovery codes only, with a refusal (controlled recovery, T10/T11;
    after several refusals Keycloak's brute-force protection shows its sign-in form)."""
    assert page.code is None, page.summary
    expected = ("denied", "password") if name == OLDER else ASKED
    assert shown(page) in expected, page.summary


def asked_kinds(who: Account) -> set[str]:
    return {PASSKEY if k == PASSWORDLESS else k for k in who.kinds()}


def password_only(env: Env, who: Account) -> Browser:
    """What somebody who knows nothing but the password gets, for a person without a factor."""
    browser = Browser(env)
    browser.login(who.user, acr_values="loa1").require_code()
    return browser


def signed_in(env: Env, who: Account, **kw: str) -> Browser:
    browser = Browser(env)
    who.sign_in(browser, **kw).require_code()
    return browser


# --- option A: the password alone signs nobody in who has a second factor -----------------------
@pytest.mark.parametrize("client_id", sorted(CLIENTS))
@pytest.mark.parametrize("name", EVERY)
def test_with_a_second_factor_the_password_alone_never_reaches_level_two(
    env: Env, admin: Admin, name: str, client_id: str
) -> None:
    """Not even level one: whatever is requested, on the web and on the phone, the password is
    answered with the question for an existing factor and no authorization code."""
    who = make(admin, name)
    before = who.credentials()
    for level in ({}, {"acr_values": "loa1"}, {"acr_values": "loa2"}):
        browser = Browser(env)
        page = browser.login(
            who.user, client_id=client_id, redirect_uri=CLIENTS[client_id], **level
        )
        # asked for an existing factor: never a code to take, never the setup of a new one
        refused_or_asked(name, page)
        if name != OLDER:
            assert who.offered(browser, page) == asked_kinds(who)
        again = browser.authorize(client_id, CLIENTS[client_id])
        assert again.code is None, "the unfinished sign-in left a session behind"
    assert who.credentials() == before


@pytest.mark.parametrize("name", sorted(ACCOUNTS))
def test_every_registered_factor_reaches_level_two_and_records_when(
    env: Env, admin: Admin, name: str
) -> None:
    who = account(admin, *ACCOUNTS[name])
    for kind in ACCOUNTS[name]:
        started = int(time.time())
        browser = Browser(env)
        page = browser.login(who.user, acr_values="loa2")
        done = who.prove(browser, page, kind)
        tokens = browser.token("at-web", done.require_code(), WEB_REDIRECT)
        for claims in (decode_jwt(tokens["id_token"]), decode_jwt(tokens["access_token"])):
            assert claims["acr"] == "loa2"
            assert started - 2 <= json.loads(claims["loa_map"])["2"] <= time.time() + 2


ACTIONS = ("CONFIGURE_TOTP", "CONFIGURE_RECOVERY_AUTHN_CODES", "UPDATE_PASSWORD")


@pytest.mark.parametrize("client_id", [*sorted(CLIENTS), "account-console"])
@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("name", EVERY)
def test_the_password_alone_cannot_add_a_factor(
    env: Env, admin: Admin, name: str, action: str, client_id: str
) -> None:
    """Nor change the password (F-3K): every credential action starts with the sign-in, and the
    sign-in asks for the factor."""
    redirect = CLIENTS.get(client_id, f"{env.base_url}/realms/{REALM}/account/")
    who = make(admin, name)
    before = who.credentials()
    for level in ({}, {"acr_values": "loa1"}):
        browser = Browser(env)
        page = browser.login(
            who.user, client_id=client_id, redirect_uri=redirect, kc_action=action, **level
        )
        refused_or_asked(name, page)
    assert who.credentials() == before


def test_a_session_older_than_the_second_factor_cannot_change_a_credential(
    env: Env, admin: Admin
) -> None:
    """F-3K: whoever signed in with the password before the person set up a factor keeps that
    single sign-on session; every credential action from it asks for the factor."""
    who = account(admin)
    old = password_only(env, who)
    who.enrol(OTP)
    time.sleep(1.5)
    before = who.credentials()
    form = old.authorize("at-web", WEB_REDIRECT, kc_action="UPDATE_PASSWORD")
    assert shown(form) == "password", form.summary  # signed in again first,
    asked = old.submit(
        form, {"username": who.user.email, "password": who.user.password, "credentialId": ""}
    )
    assert shown(asked) == OTP, asked.summary  # which asks for the factor
    for action in ("CONFIGURE_TOTP", "CONFIGURE_RECOVERY_AUTHN_CODES"):
        browser = Browser(env)
        browser.cookies.update(old.cookies)
        page = browser.authorize("at-web", WEB_REDIRECT, kc_action=action)
        assert page.code is None and shown(page) in (OTP, "password"), page.summary
    assert who.credentials() == before


def account_api(env: Env, who: Account) -> tuple[Browser, dict[str, str], str]:
    """The account console of a person who proved a factor."""
    base = f"{env.base_url}/realms/{REALM}/account/"
    browser = Browser(env)
    signed = who.sign_in(browser, client_id="account-console", redirect_uri=base, acr_values="loa2")
    tokens = browser.token("account-console", signed.require_code(), base)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    return browser, headers, base


@pytest.mark.parametrize("name", EVERY)
def test_the_password_alone_cannot_remove_a_factor(env: Env, admin: Admin, name: str) -> None:
    """The password gets no token for the account console and no removal page."""
    who = make(admin, name)
    before = who.credentials()
    base = f"{env.base_url}/realms/{REALM}/account/"
    for kind in who.kinds():
        action = f"delete_credential:{who.credential_id(kind)}"
        for client_id, redirect in (("account-console", base), ("at-web", WEB_REDIRECT)):
            browser = Browser(env)
            page = browser.login(
                who.user, client_id=client_id, redirect_uri=redirect, kc_action=action
            )
            refused_or_asked(name, page)
    assert who.credentials() == before


@pytest.mark.parametrize("name", sorted(ACCOUNTS))
def test_nobody_removes_a_credential_at_the_provider(env: Env, admin: Admin, name: str) -> None:
    """Not even after proving a factor: neither the account console nor a crafted request
    removes anything, so the last permanent factor cannot go while recovery codes stay. People
    remove factors through the application, which keeps that rule."""
    who = account(admin, *ACCOUNTS[name])
    before = who.credentials()
    console, headers, base = account_api(env, who)
    listed = console.http.get(f"{base}credentials", headers=headers).json()
    assert not any(entry.get("removeable") for entry in listed), listed
    for kind in who.kinds():
        credential = who.credential_id(kind)
        refused = console.http.delete(f"{base}credentials/{credential}", headers=headers)
        assert refused.status_code == 400, (kind, refused.status_code, refused.text)
        page = console.authorize(
            "account-console", base, kc_action=f"delete_credential:{credential}"
        )
        assert 'id="kc-delete-text"' not in page.text and "delete-credential" not in page.text
    assert who.credentials() == before


@pytest.mark.parametrize("name", ["none", *EVERY])
@pytest.mark.parametrize("client_id", ["admin-cli", "at-web", "account-console"])
def test_no_client_may_exchange_a_password_for_a_token(
    env: Env, admin: Admin, name: str, client_id: str
) -> None:
    """The built-in ``admin-cli`` client allows password grants; the realm refuses the flow."""
    who = account(admin) if name == "none" else make(admin, name)
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": who.user.email,
        "password": who.user.password,
        "scope": "openid",
    }
    if client_id == "at-web":
        data["client_secret"] = env.web_secret
    answer = httpx.post(f"{env.base_url}/realms/{REALM}/protocol/openid-connect/token", data=data)
    assert answer.status_code in (400, 401), answer.status_code
    assert "access_token" not in answer.text
    assert admin.service_token()  # the application's own client credentials still work


def test_a_recovery_code_works_once(env: Env, admin: Admin) -> None:
    who = account(admin, OTP, CODES)
    first = Browser(env)
    page = who.select(first, first.login(who.user, acr_values="loa2"), CODES)
    used = who.next_code(page)
    who.answer_code(first, page, used).require_code()
    second = Browser(env)
    page = who.select(second, second.login(who.user, acr_values="loa2"), CODES)
    again = who.answer_code(second, page, used)
    assert again.code is None and shown(again) == CODES, again.summary
    who.answer_code(second, again, who.next_code(again)).require_code()


def test_wrong_proofs_are_refused(env: Env, admin: Admin) -> None:
    passkey = account(admin, PASSKEY)
    browser = Browser(env)
    page = browser.login(passkey.user, acr_values="loa2")
    forged = authenticate(browser, page, env.base_url, passkey.keys[PASSKEY], forged=True)
    assert forged.code is None, "a signature of another key was accepted"
    codes = account(admin, OTP, CODES)
    browser = Browser(env)
    page = codes.select(browser, browser.login(codes.user, acr_values="loa2"), CODES)
    wrong = codes.answer_code(browser, page, "AAAAAAAAAAAA")
    assert wrong.code is None and shown(wrong) == CODES


@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_people_who_never_set_up_a_second_factor_see_no_change(
    env: Env, admin: Admin, client_id: str
) -> None:
    who = account(admin)
    browser = Browser(env)
    page = browser.login(who.user, client_id=client_id, redirect_uri=CLIENTS[client_id])
    tokens = browser.token(client_id, page.require_code(), CLIENTS[client_id])
    assert decode_jwt(tokens["id_token"])["acr"] == "loa1"
    assert browser.refresh(client_id, tokens["refresh_token"])["_status"] == 200
    browser.authorize(client_id, CLIENTS[client_id]).require_code()  # single sign-on
    changing = browser.authorize(client_id, CLIENTS[client_id], kc_action="UPDATE_PASSWORD")
    if shown(changing) == "password":  # the password again, and nothing more
        changing = browser.submit(
            changing,
            {"username": who.user.email, "password": who.user.password, "credentialId": ""},
        )
    assert shown(changing) == "new-password", changing.summary
    assert who.required_actions() == [] and who.credentials() == ["password"]


def test_without_a_second_factor_level_two_means_setting_one_up(env: Env, admin: Admin) -> None:
    """Voluntary enrolment stays (I07, D23): with a password only there is nothing to protect
    yet. T10 must require an enrolled factor before a platform grant takes effect."""
    who = account(admin)
    browser = password_only(env, who)
    page = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
    assert shown(page) == "otp-setup", page.summary
    assert who.credentials() == ["password"]  # nothing until the code is confirmed
    who.otp, done = set_up_otp(browser, page)
    done.require_code()
    assert who.kinds() == [OTP]


def test_a_forgotten_password_is_recovered_and_the_factor_stays(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    who = account(admin, OTP, CODES)
    asked = rig.api.post(f"{API}/auth/password-recovery", json={"email": who.user.email})
    assert asked.status_code == 202
    reset_password(env, mail_link(smtp, who.user.email), sign_out_other_devices=False)
    who.user = TestUser(id=who.user.id, email=who.user.email, password=NEW_PASSWORD)
    assert who.kinds() == sorted([OTP, CODES])
    page = Browser(env).login(who.user, acr_values="loa2")
    assert page.code is None and shown(page) in ASKED, page.summary
    who.level_two(OTP)


def test_a_reset_ends_web_and_mobile_sessions_and_the_phone_cannot_come_back(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    """F-0 (a) for both kinds of client: the periodic check ends them, and neither the old
    token nor a refreshed one opens a new mobile session."""
    who = account(admin, OTP)
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    phone = Browser(env)
    page = who.sign_in(phone, client_id="at-mobile", redirect_uri=MOBILE_REDIRECT)
    tokens = phone.token("at-mobile", page.require_code(), MOBILE_REDIRECT)
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    opened = rig.another_client().post(f"{API}/auth/mobile/session", json={}, headers=bearer)
    assert opened.status_code == 201, opened.text
    time.sleep(3.2)  # beyond the whole-second tolerance of auth_time

    def check(should_stop: Callable[[], bool]) -> None:
        recovery.check_pending_password_changes(
            rig.runtime,
            create_session_factory(rig.role_env.engine("worker")),
            rig.notices,
            should_stop=should_stop,
        )

    rig.another_client().post(f"{API}/auth/password-recovery", json={"email": who.user.email})
    reset_password(env, mail_link(smtp, who.user.email), sign_out_other_devices=False)
    worker = EmailChangeRecoveryWorker(
        create_session_factory(rig.role_env.engine("worker")),
        settings_admin(rig),
        None,
        on_cycle=lambda ok: None,
        password_check=check,
        interval_seconds=0.3,
    )
    worker.start()
    try:
        wait_for(
            lambda: (
                rig.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(0,)]
            )
        )
    finally:
        assert worker.stop()
    assert rig.rows(
        "SELECT DISTINCT client_type, revoked_reason FROM user_sessions ORDER BY 1"
    ) == [
        ("MOBILE", "PASSWORD_CHANGED"),
        ("WEB", "PASSWORD_CHANGED"),
    ]
    refreshed = phone.refresh("at-mobile", tokens["refresh_token"])
    assert refreshed["_status"] == 200  # Keycloak keeps its session unless asked to end it
    for access in (tokens["access_token"], refreshed["access_token"]):
        headers = {"Authorization": f"Bearer {access}"}
        client = rig.another_client()
        assert client.get(f"{API}/auth/session", headers=headers).status_code == 401
        reopened = client.post(f"{API}/auth/mobile/session", json={}, headers=headers)
        assert reopened.status_code == 401 and reopened.json()["code"] == "SESSION_REVOKED"


# --- F-2: when the factor was proven ----------
def times(claims: dict[str, Any]) -> tuple[str, int, int]:
    return claims["acr"], json.loads(claims["loa_map"])["2"], claims["auth_time"]


def test_neither_single_sign_on_nor_a_refresh_nor_the_password_moves_the_factor_time(
    env: Env, admin: Admin
) -> None:
    who = account(admin, OTP)
    browser = Browser(env)
    page = browser.login(who.user, acr_values="loa2")
    first = browser.token("at-web", who.prove(browser, page).require_code(), WEB_REDIRECT)
    _, proven, signed_in = times(decode_jwt(first["id_token"]))
    time.sleep(2)
    silent = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
    again = browser.token("at-web", silent.require_code(), WEB_REDIRECT)
    assert times(decode_jwt(again["id_token"])) == ("loa2", proven, signed_in)
    refreshed = browser.http.post(
        f"{env.base_url}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "at-web",
            "client_secret": env.web_secret,
            "refresh_token": again["refresh_token"],
        },
    ).json()
    assert times(decode_jwt(refreshed["access_token"])) == ("loa2", proven, signed_in)
    form = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa1", prompt="login", max_age="0")
    entered = browser.submit(
        form, {"username": who.user.email, "password": who.user.password, "credentialId": ""}
    )
    assert entered.code is None and shown(entered) == OTP, entered.summary  # the password is
    # not enough, and the abandoned attempt moves nothing:
    silent = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
    after = browser.token("at-web", silent.require_code(), WEB_REDIRECT)
    assert times(decode_jwt(after["id_token"])) == ("loa2", proven, signed_in)


# --- F-2 and F-3 through the application ----------
def follow(rig: Rig, url: str) -> Page:
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    return rig.browser._settle(rig.browser.http.get(url), rig.browser._last)


def password_then_factor(rig: Rig, who: Account, page: Page, kind: str | None = None) -> Page:
    if shown(page) == "password":
        fields = {"password": who.user.password, "credentialId": ""}
        if 'name="username"' in page.text:
            fields["username"] = who.user.email
        page = rig.browser.submit(page, fields)
    assert shown(page) in ASKED, page.summary
    return who.answer(rig.browser, page, kind)


def step_up(rig: Rig, who: Account, kind: str | None = None) -> None:
    asked = rig.api.post(
        f"{AUTH_API}/step-up", json={"purpose": "MFA", "return_to": "/me"}, headers=secure(rig)
    )
    page = follow(rig, asked.json()["redirect_url"])
    assert shown(page) == "password", "an MFA step-up must ask again, not reuse single sign-on"
    done = password_then_factor(rig, who, page, kind)
    assert done.location, done.summary
    assert rig.api.get(done.location).status_code == 302


@pytest.mark.parametrize("kind", [OTP, CODES, PASSKEY])
def test_the_application_asks_for_the_factor_before_every_account_action(
    rig: Rig, env: Env, admin: Admin, kind: str
) -> None:
    who = account(admin, OTP, CODES) if kind == CODES else account(admin, kind)

    def with_factor(browser: Browser, page: Page) -> Page:
        return who.answer(browser, page, kind)

    assert rig.sign_in(who.user, prove=with_factor).status_code == 302
    for path, body in (
        ("password-change-requests", {}),
        ("mfa-enrollment-requests", {"factor": "TOTP"}),
    ):
        refused = rig.api.post(f"{API}/me/security/{path}", json=body, headers=secure(rig))
        assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED"
        assert 'acr_values="loa2"' in refused.headers["www-authenticate"]
    step_up(rig, who, kind)
    info = rig.api.get(f"{AUTH_API}/session").json()
    assert info["auth_level"] == "LOA2"
    proven = datetime.fromisoformat(info["step_up_expires_at"]).timestamp() - 600
    assert time.time() - 30 <= proven <= time.time() + 2
    # a second sign-in through single sign-on carries the old factor time, not a new window
    time.sleep(2.5)
    second = rig.another_client()
    start = second.get(
        f"{AUTH_API}/login",
        params={
            "return_to": "/app",
        },
    )
    url = urlparse(start.headers["location"])
    query = {**{k: v[0] for k, v in parse_qs(url.query).items()}, "acr_values": "loa2"}
    silent = rig.at_keycloak(url._replace(query=urlencode(query)).geturl(), None)
    assert second.get(silent).status_code == 302
    other = second.get(f"{AUTH_API}/session").json()
    assert other["auth_level"] == "LOA2"
    assert other["step_up_expires_at"] == info["step_up_expires_at"]


def change_password(rig: Rig, who: Account, url: str) -> httpx.Response:
    """Walk the provider's pages of an application-started password change."""
    page = follow(rig, url)
    if shown(page) != "new-password":  # the provider always asks again before this form (F-3K)
        page = password_then_factor(rig, who, page)
    assert shown(page) == "new-password", page.summary
    done = rig.browser.submit(
        page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location, done.summary
    finished: httpx.Response = rig.api.get(done.location)
    return finished


@pytest.mark.parametrize("asked_for_level_two", [True, False], ids=["as_sent", "parameter_dropped"])
def test_a_password_change_of_a_person_with_a_factor_runs_through_it(
    rig: Rig, env: Env, admin: Admin, asked_for_level_two: bool
) -> None:
    """F-3K: the provider asks for the factor before its password form even when the browser
    drops the level request, and a browser without a session gets no further either."""
    who = account(admin, OTP)
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    step_up(rig, who)
    time.sleep(1.5)  # the sign-in is no longer of this very second
    started = rig.api.post(
        f"{API}/me/security/password-change-requests", json={}, headers=secure(rig)
    )
    url = urlparse(started.json()["redirect_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert query["acr_values"] == "loa2"
    if not asked_for_level_two:
        del query["acr_values"]
        rig.browser = Browser(env)  # no single sign-on session that proved the factor
    address = url._replace(query=urlencode(query)).geturl()
    page = follow(rig, address)
    assert shown(page) == "password", page.summary
    entered = rig.browser.submit(
        page,
        {"password": who.user.password, "credentialId": ""}
        | ({"username": who.user.email} if 'name="username"' in page.text else {}),
    )
    assert shown(entered) == OTP, entered.summary  # never the form after the password alone
    done = who.prove(rig.browser, entered)
    assert shown(done) == "new-password", done.summary
    done = rig.browser.submit(
        done, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location, done.summary
    finished = rig.api.get(done.location)
    expected = "success" if asked_for_level_two else "reauthentication_required"
    assert finished.headers["location"] == f"/?security_action={expected}"


# --- the application keeps what the provider cannot ----------------------------------------------
def test_the_application_keeps_the_last_permanent_factor_at_the_real_provider(
    rig: Rig, env: Env, admin: Admin
) -> None:
    """With codes and, since the provider marks every first factor, without them too: the last
    permanent factor goes only through the controlled switch-off."""
    who = account(admin, OTP, CODES)
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    step_up(rig, who)
    path = f"{API}/me/security/second-factors"
    refused = rig.api.delete(f"{path}/{who.credential_id(OTP)}", headers=secure(rig))
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "LAST_PERMANENT_FACTOR"
    assert who.kinds() == sorted([OTP, CODES])
    gone = rig.api.delete(f"{path}/{who.credential_id(CODES)}", headers=secure(rig))
    assert gone.status_code == 204, gone.text  # the backup may go
    refused = rig.api.delete(f"{path}/{who.credential_id(OTP)}", headers=secure(rig))
    assert refused.status_code == 409 and who.kinds() == [OTP]


def test_the_application_reads_the_factor_obligation_from_the_real_provider(
    rig: Rig, env: Env, admin: Admin
) -> None:
    who = account(admin, OTP)
    who.mark()
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    step_up(rig, who)
    refused = rig.api.delete(
        f"{API}/me/security/second-factors/{who.credential_id(OTP)}", headers=secure(rig)
    )
    assert refused.status_code == 409 and who.kinds() == [OTP], refused.text


def test_the_admin_client_withdraws_credential_setups_and_nothing_else(
    rig: Rig, admin: Admin
) -> None:
    who = account(admin, OTP)
    who.mark()
    path = f"/users/{who.user.id}"
    before = admin.master("GET", path).json()
    before["requiredActions"] = [
        "VERIFY_EMAIL",
        "CONFIGURE_TOTP",
        "CONFIGURE_RECOVERY_AUTHN_CODES",
    ]
    admin.master("PUT", path, json=before).raise_for_status()
    client = settings_admin(rig)
    client.clear_pending_credential_setups(who.user.id)
    after = admin.master("GET", path).json()
    assert after["requiredActions"] == ["VERIFY_EMAIL"]
    for field in ("email", "username", "enabled", "emailVerified", "attributes"):
        assert after[field] == before[field], field
    assert who.kinds() == [OTP] and client.has_factor_obligation(who.user.id)
    client.set_verified_email(who.user.id, f"new-{who.user.email}")  # D37 keeps the marker
    assert client.has_factor_obligation(who.user.id)


# --- held forms (F-1R-C and the rest of F-3K, closed by the Keycloak security provider) ----------
def test_a_set_up_page_opened_before_the_first_factor_is_refused_after_it(
    env: Env, admin: Admin
) -> None:
    """F-1R-C (P1), closed. Somebody who knows the password opens the one-time code set-up while
    the account has no factor and keeps the page open. The person then turns a factor on. The old
    page is refused when it is submitted: the provider decides under the person's lock, on the
    account as it is then, and this sign-in proved no permanent factor."""
    who = account(admin)
    intruder = Browser(env)
    held = intruder.login(who.user, kc_action="CONFIGURE_TOTP")
    manual = re.search(r'href="([^"]*mode=manual[^"]*)"', held.text)
    if manual:  # the page with the secret, as the intruder keeps it
        held = intruder.get(manual.group(1).replace("&amp;", "&"))
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', held.text)
    assert secret, held.summary
    who.enrol(OTP)  # the person turns on the second factor
    admin.master("POST", f"/users/{who.user.id}/logout").raise_for_status()
    fields = {**hidden_inputs(held.text), "totp": totp(secret.group(1).strip()), "userLabel": "x"}
    done = intruder.submit(held, fields, action=form_action(held.text))
    assert done.code is None and done.location and "error=access_denied" in done.location
    assert who.credentials() == [OTP, "password"]
    page = Browser(env).login(who.user, acr_values="loa2")
    assert shown(page) == OTP and "toggleOTP(1," not in page.text  # one device: the person's
    who.prove(Browser(env), Browser(env).login(who.user), OTP)


def test_a_password_form_opened_before_the_first_factor_is_refused_after_it(
    env: Env, admin: Admin
) -> None:
    """F-3K (the remaining case), closed. The same with the new-password form."""
    who = account(admin)
    intruder = Browser(env)
    held = intruder.login(who.user, kc_action="UPDATE_PASSWORD")
    assert shown(held) == "new-password", held.summary
    who.enrol(OTP)
    done = intruder.submit(held, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD})
    assert done.code is None and done.location and "error=access_denied" in done.location
    page = Browser(env).login(who.user)  # the old password is still the password
    assert page.code is None and shown(page) == OTP, page.summary
