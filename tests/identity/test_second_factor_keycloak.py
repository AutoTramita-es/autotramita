"""F2-T09-REC F-1R, F-2 and F-3 against real Keycloak 26.4.7, with the application on real
PostgreSQL and Redis where it takes part. Runs only in the ``keycloak`` CI job.

Two tests at the end record behaviour that is **not** protected (open findings, owner decision
needed); they exist so that the finding is evidence and cannot change unnoticed."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from app.auth.security import recovery
from app.auth.security.notify import NoticeKind
from app.auth.security.recovery_worker import EmailChangeRecoveryWorker
from app.core.db import create_session_factory
from tests.identity.accounts import (
    CODES,
    OTP,
    PASSKEY,
    PASSWORDLESS,
    Account,
    account,
    set_up_codes,
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
    "recovery_codes_only": (CODES,),
    "passkey": (PASSKEY,),
    "passwordless_passkey": (PASSWORDLESS,),
    "totp_and_codes": (OTP, CODES),
    "totp_and_passkey": (OTP, PASSKEY),
    "passkey_and_codes": (PASSKEY, CODES),
}


def password_only(env: Env, who: Account) -> Browser:
    """What somebody who knows nothing but the password gets."""
    browser = Browser(env)
    browser.login(who.user, acr_values="loa1").require_code()
    return browser


# --- F-1R: the password alone is never enough ----------
@pytest.mark.parametrize("name", sorted(ACCOUNTS))
def test_with_a_second_factor_the_password_alone_never_reaches_level_two(
    env: Env, admin: Admin, name: str
) -> None:
    who = account(admin, *ACCOUNTS[name])
    before = who.credentials()
    for browser, page in (
        (fresh := Browser(env), fresh.login(who.user, acr_values="loa2")),
        (sso := password_only(env, who), sso.authorize("at-web", WEB_REDIRECT, acr_values="loa2")),
    ):
        # asked for an existing factor: never a code to take, never the setup of a new one
        assert page.code is None and shown(page) in ASKED, page.summary
        expected = {PASSKEY if k == PASSWORDLESS else k for k in ACCOUNTS[name]}
        assert who.offered(browser, page) == expected
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


@pytest.mark.parametrize("name", sorted(ACCOUNTS))
@pytest.mark.parametrize("action", ["CONFIGURE_TOTP", "CONFIGURE_RECOVERY_AUTHN_CODES"])
def test_the_password_alone_cannot_add_a_factor(
    env: Env, admin: Admin, name: str, action: str
) -> None:
    who = account(admin, *ACCOUNTS[name])
    before = who.credentials()
    sso = password_only(env, who)
    fresh = Browser(env)
    asked_directly = fresh.authorize("at-web", WEB_REDIRECT, kc_action=action)
    signed = fresh.submit(
        asked_directly,
        {"username": who.user.email, "password": who.user.password, "credentialId": ""},
    )
    pages = [
        signed,
        sso.authorize("at-web", WEB_REDIRECT, kc_action=action),
        sso.authorize("at-web", WEB_REDIRECT, kc_action=action, acr_values="loa1"),
    ]
    for page in pages:
        assert page.code is None and shown(page) in ASKED, page.summary
    assert who.credentials() == before


def account_api(env: Env, who: Account) -> tuple[Browser, dict[str, str], str]:
    base = f"{env.base_url}/realms/{REALM}/account/"
    browser = Browser(env)
    signed = browser.login(who.user, client_id="account-console", redirect_uri=base)
    tokens = browser.token("account-console", signed.require_code(), base)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    return browser, headers, base


@pytest.mark.parametrize("name", sorted(ACCOUNTS))
def test_the_password_alone_cannot_remove_a_factor(env: Env, admin: Admin, name: str) -> None:
    who = account(admin, *ACCOUNTS[name])
    before = who.credentials()
    console, headers, base = account_api(env, who)
    sso = password_only(env, who)
    for kind in ACCOUNTS[name]:
        credential = who.credential_id(kind)
        refused = console.http.delete(f"{base}credentials/{credential}", headers=headers)
        assert refused.status_code == 403, (kind, refused.status_code)
        page = sso.authorize("at-web", WEB_REDIRECT, kc_action=f"delete_credential:{credential}")
        assert page.code is None and shown(page) in ASKED, page.summary
    assert who.credentials() == before


@pytest.mark.parametrize("name", ["none", "totp", "recovery_codes_only", "passkey"])
@pytest.mark.parametrize("client_id", ["admin-cli", "at-web", "account-console"])
def test_no_client_may_exchange_a_password_for_a_token(
    env: Env, admin: Admin, name: str, client_id: str
) -> None:
    """The built-in ``admin-cli`` client allows password grants; the realm refuses the flow."""
    who = account(admin, *ACCOUNTS.get(name, ()))
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
    who = account(admin, CODES)
    first = Browser(env)
    page = first.login(who.user, acr_values="loa2")
    used = who.next_code(page)
    who.answer_code(first, page, used).require_code()
    second = Browser(env)
    page = second.login(who.user, acr_values="loa2")
    again = who.answer_code(second, page, used)
    assert again.code is None and shown(again) == CODES, again.summary
    who.answer_code(second, again, who.next_code(again)).require_code()


def test_wrong_proofs_are_refused(env: Env, admin: Admin) -> None:
    passkey = account(admin, PASSKEY)
    browser = Browser(env)
    page = browser.login(passkey.user, acr_values="loa2")
    forged = authenticate(browser, page, env.base_url, passkey.keys[PASSKEY], forged=True)
    assert forged.code is None, "a signature of another key was accepted"
    codes = account(admin, CODES)
    browser = Browser(env)
    page = browser.login(codes.user, acr_values="loa2")
    wrong = codes.answer_code(browser, page, "AAAAAAAAAAAA")
    assert wrong.code is None and shown(wrong) == CODES


def test_the_last_factor_can_be_removed_only_after_proving_it(env: Env, admin: Admin) -> None:
    who = account(admin, OTP)
    credential = who.credential_id(OTP)
    sso = password_only(env, who)
    page = sso.authorize("at-web", WEB_REDIRECT, kc_action=f"delete_credential:{credential}")
    confirm = who.prove(sso, page)
    assert confirm.code is None and who.kinds() == [OTP]  # proof, then Keycloak's confirmation


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
    who = account(admin)
    assert rig.sign_in(who.user).status_code == 302
    phone = Browser(env)
    code = phone.login(who.user, client_id="at-mobile", redirect_uri=MOBILE_REDIRECT).require_code()
    tokens = phone.token("at-mobile", code, MOBILE_REDIRECT)
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
    renewed = decode_jwt(browser.token("at-web", entered.require_code(), WEB_REDIRECT)["id_token"])
    # the password sign-in is new (auth_time moves), the second factor is as old as before
    assert times(renewed) == ("loa1", proven, renewed["auth_time"])
    assert renewed["auth_time"] > signed_in


# --- F-2 and F-3 through the application ----------
def follow(rig: Rig, url: str) -> Page:
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    return rig.browser._settle(rig.browser.http.get(url), rig.browser._last)


def password_then_factor(rig: Rig, who: Account, page: Page) -> Page:
    if shown(page) == "password":
        fields = {"password": who.user.password, "credentialId": ""}
        if 'name="username"' in page.text:
            fields["username"] = who.user.email
        page = rig.browser.submit(page, fields)
    assert shown(page) in ASKED, page.summary
    return who.prove(rig.browser, page)


def step_up(rig: Rig, who: Account) -> None:
    asked = rig.api.post(
        f"{AUTH_API}/step-up", json={"purpose": "MFA", "return_to": "/me"}, headers=secure(rig)
    )
    page = follow(rig, asked.json()["redirect_url"])
    assert shown(page) == "password", "an MFA step-up must ask again, not reuse single sign-on"
    done = password_then_factor(rig, who, page)
    assert done.location, done.summary
    assert rig.api.get(done.location).status_code == 302


@pytest.mark.parametrize("kind", [OTP, CODES, PASSKEY])
def test_the_application_asks_for_the_factor_before_every_account_action(
    rig: Rig, env: Env, admin: Admin, kind: str
) -> None:
    who = account(admin, kind)
    assert rig.sign_in(who.user).status_code == 302  # level one: the password
    for path, body in (
        ("password-change-requests", {}),
        ("mfa-enrollment-requests", {"factor": "TOTP"}),
    ):
        refused = rig.api.post(f"{API}/me/security/{path}", json=body, headers=secure(rig))
        assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED"
        assert 'acr_values="loa2"' in refused.headers["www-authenticate"]
    step_up(rig, who)
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


def test_a_password_change_of_a_person_with_a_factor_runs_through_it(
    rig: Rig, env: Env, admin: Admin
) -> None:
    who = account(admin, OTP)
    assert rig.sign_in(who.user).status_code == 302
    step_up(rig, who)
    started = rig.api.post(
        f"{API}/me/security/password-change-requests", json={}, headers=secure(rig)
    )
    url = started.json()["redirect_url"]
    assert parse_qs(urlparse(url).query)["acr_values"] == ["loa2"]
    page = follow(rig, url)
    if shown(page) != "new-password":  # Keycloak asks again when the sign-in is not recent
        page = password_then_factor(rig, who, page)
    assert shown(page) == "new-password", page.summary
    done = rig.browser.submit(
        page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location, done.summary
    finished = rig.api.get(done.location)
    assert finished.headers["location"] == "/?security_action=success"
    assert rig.api.get(f"{AUTH_API}/session").status_code == 200


# --- open findings (recorded, not protected) ----------
def test_open_finding_keycloak_changes_a_password_without_the_second_factor(
    rig: Rig, env: Env, admin: Admin
) -> None:
    """OPEN (F-3, owner decision). Keycloak 26.4.7 does not treat its password form as a
    credential action: with the password alone it can be opened for a person who has a second
    factor. The application detects it only when the change returns through its own callback
    and then ends every session; a change made on Keycloak's pages alone is seen with T11."""
    who = account(admin, OTP)
    browser = password_only(env, who)
    page = browser.authorize("at-web", WEB_REDIRECT, kc_action="UPDATE_PASSWORD")
    assert shown(page) == "new-password", "the finding changed: update F-3 and this test"
    # the same through the application with the level request removed from the address
    assert rig.sign_in(who.user).status_code == 302
    step_up(rig, who)
    started = rig.api.post(
        f"{API}/me/security/password-change-requests", json={}, headers=secure(rig)
    )
    url = urlparse(started.json()["redirect_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items() if k != "acr_values"}
    rig.browser = Browser(env)  # no single sign-on session that proved the factor
    form = follow(rig, url._replace(query=urlencode(query)).geturl())
    entered = rig.browser.submit(
        form, {"username": who.user.email, "password": who.user.password, "credentialId": ""}
    )
    assert shown(entered) == "new-password", entered.summary
    done = rig.browser.submit(
        entered, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location, done.summary
    finished = rig.api.get(done.location)
    assert finished.headers["location"] == "/?security_action=reauthentication_required"
    assert rig.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(0,)]
    assert NoticeKind.PASSWORD_CHANGED in [n.kind for n in rig.notices.notices]


def test_open_finding_unfinished_new_recovery_codes_can_be_taken_with_the_password(
    env: Env, admin: Admin
) -> None:
    """OPEN, P1 (F-1R, owner decision). After the last recovery code Keycloak requires new
    ones. If the person leaves that page, the requirement stays on the account and is served
    after the next **password** sign-in, without the one-time code the account also has: the
    person who knows the password creates codes of their own and reaches level two."""
    who = account(admin, OTP, CODES)
    for position in range(len(who.codes)):
        browser = Browser(env)
        page = who.select(browser, browser.login(who.user, acr_values="loa2"), CODES)
        done = who.answer_code(browser, page, who.next_code(page))
        last = position == len(who.codes) - 1
        assert (shown(done) == "codes-setup") if last else done.code, done.summary
    assert who.kinds() == [OTP]  # left there: the codes are gone, the requirement stays
    assert who.required_actions() == ["CONFIGURE_RECOVERY_AUTHN_CODES"]
    stranger = Browser(env)
    offered = stranger.login(who.user)  # the password alone
    assert shown(offered) == "codes-setup", "the finding changed: update F-1R and this test"
    who.codes, done = set_up_codes(stranger, offered)
    done.require_code()
    taken = Browser(env)
    page = who.select(taken, taken.login(who.user, acr_values="loa2"), CODES)
    assert who.answer_code(taken, page, who.next_code(page)).code
