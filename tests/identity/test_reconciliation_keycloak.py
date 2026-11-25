"""F2-T09-REC against real Keycloak 26.4.7, PostgreSQL 16, Redis 7 and an SMTP sink.

D37 end to end through the periodic worker, the absence of a way around it inside Keycloak, and
the remaining checks of S3 (level-of-authentication age, WebAuthn) plus what Keycloak does and
does not tell the application about resets and refresh-token reuse."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from app.auth.security import recovery
from app.auth.security.email_change import confirm_request, create_request
from app.auth.security.email_change_worker import run_once
from app.auth.security.notify import NoticeKind, SmtpNotifier
from app.auth.security.recovery_worker import EmailChangeRecoveryWorker
from app.core.db import RequestContext, create_session_factory, session_scope
from tests.identity.accounts import OTP, account, codes_only_account
from tests.identity.kc import (
    GOOD_PASSWORD,
    MOBILE_REDIRECT,
    REALM,
    SMTP_PORT,
    WEB_REDIRECT,
    Admin,
    BackchannelSink,
    Browser,
    Env,
    SmtpSink,
    TestUser,
    decode_jwt,
    form_action,
    hidden_inputs,
    totp,
)
from tests.identity.rig import API as AUTH_API
from tests.identity.rig import ORIGIN, SESSION, Rig
from tests.identity.test_security_keycloak import (
    NEW_PASSWORD,
    mail_link,
    password_form,
    secure,
    settings_admin,
)
from tests.identity.webauthn import SoftwareKey, authenticate, register

pytestmark = pytest.mark.keycloak

API = "/api/v1"


def wait_for(condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.2)


def keycloak_user(admin: Admin, user: TestUser) -> tuple[str, str, bool]:
    found = admin.master("GET", f"/users/{user.id}").json()
    return found["email"], found["username"], found["emailVerified"]


def can_sign_in(env: Env, address: str, password: str = GOOD_PASSWORD) -> bool:
    browser = Browser(env)
    try:
        return bool(browser.login(address, password).code)
    finally:
        browser.close()


def strict_clock(rig: Rig) -> None:
    """Application and Keycloak share one host clock here, so the margin can shrink to the one
    second that covers ``auth_time`` being truncated to whole seconds."""
    rig.runtime.settings = rig.runtime.settings.model_copy(update={"leeway_seconds": 1})


def smtp_notifier(rig: Rig) -> SmtpNotifier:
    return SmtpNotifier(
        rig.runtime.settings.model_copy(
            update={
                "notify_mode": "smtp",
                "smtp_host": "127.0.0.1",
                "smtp_port": SMTP_PORT,
                "smtp_from": "security@example.test",
            }
        )
    )


@contextmanager
def periodic_worker(rig: Rig, notifier: SmtpNotifier) -> Iterator[None]:
    def finished(ok: bool) -> None:
        rig.runtime.email_change_ready = ok

    worker = EmailChangeRecoveryWorker(
        create_session_factory(rig.role_env.engine("worker")),
        settings_admin(rig),
        notifier,
        on_cycle=finished,
        interval_seconds=0.3,
    )
    worker.start()
    try:
        wait_for(lambda: rig.runtime.email_change_ready)
        yield
    finally:
        assert worker.stop()


# --- D37 ---------------------------------------------------------------------------------------
def test_d37_end_to_end_with_real_mail_and_the_periodic_worker(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    user = admin.create_user()
    new_email = f"new-{user.email}"
    notifier = smtp_notifier(rig)
    rig.runtime.notifier = notifier
    strict_clock(rig)
    assert rig.sign_in(user).status_code == 302
    second, elsewhere = rig.another_client(), Browser(env)
    assert rig.sign_in(user, client=second, browser=elsewhere).status_code == 302
    time.sleep(2.5)  # the other device authenticated clearly before the change

    with periodic_worker(rig, notifier):
        asked = rig.api.post(
            f"{API}/me/security/email-change-requests",
            headers=secure(rig),
            json={"new_email": new_email},
        )
        assert asked.status_code == 202
        mail = smtp.for_recipient(new_email)
        assert len(mail) == 1
        found = re.search(rf"{re.escape(ORIGIN)}(/api/v1/auth/\S+)#(\S+)", mail[0]["body"])
        assert found and found.group(1) == f"{API}/auth/email-change-verification"
        link = {k: v[0] for k, v in parse_qs(found.group(2)).items()}
        # nothing changes before the confirmation: the old address is still the login
        assert keycloak_user(admin, user) == (user.email, user.email, True)
        assert can_sign_in(env, user.email) and not can_sign_in(env, new_email)
        assert rig.api.get(found.group(1)).status_code == 200
        body = {"operation_id": link["id"], "token": link["token"]}
        confirm = f"{API}/me/security/email-change-confirmations"
        assert rig.api.post(confirm, headers=secure(rig), json=body).status_code == 202
        wait_for(
            lambda: (
                rig.rows("SELECT status FROM email_change_notifications ORDER BY status")
                == [("SENT",), ("SENT",)]
            )
        )
        assert rig.api.post(confirm, headers=secure(rig), json=body).status_code == 202  # replay

    assert keycloak_user(admin, user) == (new_email, new_email, True)
    assert can_sign_in(env, new_email) and not can_sign_in(env, user.email)
    assert rig.rows("SELECT auth_subject, email FROM users") == [(user.id, new_email)]
    assert rig.rows(
        "SELECT status, old_email, new_email, token_hash FROM email_change_operations"
    ) == [("COMPLETED", None, None, None)]
    assert rig.rows("SELECT recipient FROM email_change_notifications") == [(None,), (None,)]
    assert rig.api.get(f"{AUTH_API}/session").status_code == 200
    assert second.get(f"{AUTH_API}/session").status_code == 401
    for address in (user.email, new_email):
        notices = [m for m in smtp.for_recipient(address) if "correo ha cambiado" in m["subject"]]
        assert len(notices) == 1, address
        assert link["token"] not in notices[0]["body"]
    assert rig.rows("SELECT count(*) FROM audit_events WHERE action='identity.email.changed'") == [
        (1,)
    ]

    # the other device still holds its Keycloak session: it is asked for the password again
    start = second.get(f"{AUTH_API}/login", params={"return_to": "/app"})
    silent = rig.at_keycloak(start.headers["location"], None, elsewhere)
    forced = second.get(silent)
    assert forced.status_code == 302
    assert parse_qs(urlparse(forced.headers["location"]).query)["prompt"] == ["login"]
    assert second.get(f"{AUTH_API}/session").status_code == 401
    elsewhere._last = f"{ORIGIN}{AUTH_API}/callback"
    form = elsewhere.get(forced.headers["location"])
    assert form.location is None and 'name="password"' in form.text, form.summary
    renamed = TestUser(id=user.id, email=new_email, password=user.password)
    fields = {"username": renamed.email, "password": renamed.password, "credentialId": ""}
    if 'name="username"' not in form.text:
        del fields["username"]
    done = elsewhere.submit(form, fields)
    assert done.location, done.summary
    assert second.get(done.location).status_code == 302
    assert second.get(f"{AUTH_API}/session").status_code == 200


def test_d37_cannot_be_bypassed_inside_keycloak(env: Env, admin: Admin) -> None:
    """The login name must not change before verification, so Keycloak must not let the person
    edit it: neither on its profile page nor through its account API."""
    user = admin.create_user()
    wanted = f"bypass-{user.email}"
    browser = Browser(env)
    browser.login(user).require_code()
    page = browser.authorize("at-web", WEB_REDIRECT, kc_action="UPDATE_PROFILE")
    assert page.location is None and 'name="firstName"' in page.text, page.summary
    assert not re.search(r'<input[^>]*name="email"(?![^>]*(readonly|disabled))', page.text)
    fields = hidden_inputs(page.text)
    fields.update({"email": wanted, "username": wanted, "firstName": "A", "lastName": "B"})
    browser.submit(page, fields)
    assert keycloak_user(admin, user) == (user.email, user.email, True)

    account = f"{env.base_url}/realms/{REALM}/account/"
    other = Browser(env)
    signed = other.login(user, client_id="account-console", redirect_uri=account)
    tokens = other.token("account-console", signed.require_code(), account)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    shown = other.http.get(f"{account}?userProfileMetadata=true", headers=headers)
    assert shown.status_code == 200
    editable = {
        a["name"]: not a["readOnly"] for a in shown.json()["userProfileMetadata"]["attributes"]
    }
    assert editable["email"] is False and editable["username"] is False
    other.http.post(
        account,
        headers=headers,
        json={"username": wanted, "email": wanted, "firstName": "A", "lastName": "B"},
    )
    assert keycloak_user(admin, user) == (user.email, user.email, True)


def test_d37_an_address_taken_in_keycloak_is_held_for_review(rig: Rig, admin: Admin) -> None:
    user, holder = admin.create_user(), admin.create_user()
    assert rig.sign_in(user).status_code == 302
    user_id, session_id = (
        UUID(str(v)) for v in rig.rows("SELECT user_id, id FROM user_sessions")[0]
    )
    with session_scope(rig.runtime.factory, RequestContext(user_id=user_id)) as db:
        operation, token = create_request(
            db, user_id=user_id, session_id=session_id, new_email=holder.email
        )
        assert confirm_request(db, user_id=user_id, operation_id=operation, token=token)
    run_once(create_session_factory(rig.role_env.engine("worker")), settings_admin(rig), None)
    assert rig.rows("SELECT status FROM email_change_operations") == [("MANUAL_REVIEW",)]
    assert keycloak_user(admin, user)[0] == user.email
    assert keycloak_user(admin, holder)[0] == holder.email
    assert rig.rows("SELECT email FROM users") == [(user.email,)]


# --- S3: age of the level of authentication, second factors -------------------------------------
def loa_condition(admin: Admin, level: str) -> dict[str, Any]:
    executions = admin.master("GET", "/authentication/flows/browser-loa/executions").json()
    for execution in executions:
        if config_id := execution.get("authenticationConfig"):
            config: dict[str, Any] = admin.master(
                "GET", f"/authentication/config/{config_id}"
            ).json()
            if config["config"].get("loa-condition-level") == level:
                return config
    raise AssertionError(f"no condition for level {level}")


def configure_otp(browser: Browser, page: Any) -> tuple[str, Any]:
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    if not secret:
        manual = re.search(r'href="([^"]*mode=manual[^"]*)"', page.text)
        assert manual, page.summary
        page = browser.get(manual.group(1).replace("&amp;", "&"))
        secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    assert secret, page.summary
    value = secret.group(1).strip()
    fields = hidden_inputs(page.text)
    fields.update({"totp": totp(value), "userLabel": "rec"})
    return value, browser.submit(page, fields, action=form_action(page.text))


def test_s03_level_two_expires_after_its_configured_age(env: Env, admin: Admin) -> None:
    level_one, level_two = loa_condition(admin, "1"), loa_condition(admin, "2")
    assert level_one["config"]["loa-max-age"] == "43200"
    assert level_two["config"]["loa-max-age"] == "600"  # the committed value (D23)
    original = dict(level_two["config"])
    level_two["config"]["loa-max-age"] = "5"  # shortened: no ten-minute sleep
    path = f"/authentication/config/{level_two['id']}"
    admin.master("PUT", path, json=level_two).raise_for_status()
    try:
        user = admin.create_user()
        browser = Browser(env)
        browser.login(user, acr_values="loa1").require_code()
        _, done = configure_otp(
            browser, browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
        )
        done.require_code()
        within = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
        tokens = browser.token("at-web", within.require_code(), WEB_REDIRECT)
        assert decode_jwt(tokens["id_token"])["acr"] == "loa2"
        time.sleep(7)
        low = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa1")
        tokens = browser.token("at-web", low.require_code(), WEB_REDIRECT)
        assert decode_jwt(tokens["id_token"])["acr"] == "loa1"
        again = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
        assert again.code is None and 'name="otp"' in again.text, again.summary
    finally:
        level_two["config"] = original
        admin.master("PUT", path, json=level_two).raise_for_status()


def test_keycloak_needs_level_two_to_remove_a_second_factor(env: Env, admin: Admin) -> None:
    """The application asks LoA2 to remove a factor. Keycloak removes none at all: neither a
    request with the password alone nor the account console of a person who proved the factor
    (F-1R-B: the last permanent factor must not go while recovery codes stay)."""
    who = account(admin, OTP)
    credential = who.credential_id(OTP)
    weak = Browser(env)
    page = weak.login(who.user, kc_action=f"delete_credential:{credential}", acr_values="loa1")
    assert page.code is None and 'name="otp"' in page.text, page.summary
    console_url = f"{env.base_url}/realms/{REALM}/account/"
    console = Browser(env)
    signed = who.sign_in(
        console, client_id="account-console", redirect_uri=console_url, acr_values="loa2"
    )
    tokens = console.token("account-console", signed.require_code(), console_url)
    refused = console.http.delete(
        f"{console_url}credentials/{credential}",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"},
    )
    assert refused.status_code == 400, refused.text
    assert who.kinds() == [OTP]


PASSKEY_ACTIONS = ("webauthn-register", "webauthn-register-passwordless")


@contextmanager
def required_action_enabled(admin: Admin, alias: str) -> Iterator[None]:
    path = f"/authentication/required-actions/{alias}"
    committed = admin.master("GET", path).json()
    assert committed["enabled"] is False
    admin.master("PUT", path, json={**committed, "enabled": True}).raise_for_status()
    try:
        yield
    finally:
        admin.master("PUT", path, json=committed).raise_for_status()


@pytest.mark.parametrize("alias", PASSKEY_ACTIONS)
def test_f1_nobody_can_register_a_passkey(env: Env, admin: Admin, alias: str) -> None:
    """F-1 (b): both registration actions are off, so neither a crafted authorization request
    nor the account console can add a passkey."""
    user = admin.create_user()
    browser = Browser(env)
    browser.login(user).require_code()
    page = browser.authorize("at-web", WEB_REDIRECT, kc_action=alias)
    assert "registerWebAuthn" not in page.text and 'name="attestationObject"' not in page.text
    account = f"{env.base_url}/realms/{REALM}/account/"
    console = Browser(env)
    signed = console.login(user, client_id="account-console", redirect_uri=account)
    tokens = console.token("account-console", signed.require_code(), account)
    listed = console.http.get(
        f"{account}credentials",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"},
    )
    assert listed.status_code == 200
    offered = {entry.get("createAction") for entry in listed.json()}
    assert alias not in offered, offered
    kinds = {c["type"] for c in admin.master("GET", f"/users/{user.id}/credentials").json()}
    assert kinds == {"password"}


def test_s03_a_passkey_enrolled_earlier_is_the_second_level(
    rig: Rig, env: Env, admin: Admin
) -> None:
    """F-1R (d): registration stays off (F-1 b), but a passkey an account already has is proven
    at level two; it is never answered with the offer to set up a one-time code."""
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    key = SoftwareKey()
    with required_action_enabled(admin, "webauthn-register"):
        page = rig.browser.authorize("at-web", WEB_REDIRECT, kc_action="webauthn-register")
        if 'name="password"' in page.text:  # a credential changes only after a fresh sign-in
            page = rig.browser.submit(
                page, {"username": user.email, "password": user.password, "credentialId": ""}
            )
        done = register(rig.browser, page, env.base_url, key)
    assert done.location and "kc_action_status=success" in done.location, done.summary
    factors = rig.api.get(f"{API}/me/security").json()["second_factors"]
    assert [f["type"] for f in factors] == ["webauthn"]
    removal = rig.api.delete(
        f"{API}/me/security/second-factors/{factors[0]['id']}", headers=secure(rig)
    )
    assert removal.status_code == 401 and removal.json()["code"] == "STEP_UP_REQUIRED"
    password_only = Browser(env)
    refused = password_only.login(user, acr_values="loa1")
    assert refused.code is None and 'id="webauth"' in refused.text, refused.summary
    second = Browser(env)
    asked = second.login(user, acr_values="loa2")
    assert asked.code is None and 'id="webauth"' in asked.text, asked.summary
    assert "kc-totp-secret-key" not in asked.text and "mode=manual" not in asked.text
    proven = authenticate(second, asked, env.base_url, key)
    tokens = second.token("at-web", proven.require_code(), WEB_REDIRECT)
    assert decode_jwt(tokens["id_token"])["acr"] == "loa2"


def test_recovery_codes_alone_protect_level_two(rig: Rig, env: Env, admin: Admin) -> None:
    """F-1R: an account whose only second factor is a set of recovery codes (from before the
    final MFA decision, marked by an operator) must use one; the password alone opens no level."""
    who = codes_only_account(admin, marked=True)
    for level in ("loa1", "loa2"):
        asked = Browser(env).login(who.user, acr_values=level)
        assert asked.code is None and 'name="recoveryCodeInput"' in asked.text, asked.summary
        assert "kc-totp-secret-key" not in asked.text and "mode=manual" not in asked.text


# --- what Keycloak tells the application --------------------------------------------------------
def reset_password(env: Env, link: str, *, sign_out_other_devices: bool) -> None:
    browser = Browser(env)
    browser._last = f"{ORIGIN}/"
    page = browser.get(link)
    for _ in range(3):
        if "password-new" in page.text:
            break
        proceed = re.search(r'href="([^"]*(?:action-token|login-actions)[^"]*)"', page.text)
        assert proceed, page.summary
        page = browser.get(proceed.group(1).replace("&amp;", "&"))
    box = re.search(r'<input[^>]*name="logout-sessions"[^>]*>', page.text)
    assert box and "checked" not in box.group(0)  # offered, not preselected
    fields = {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    if sign_out_other_devices:
        fields["logout-sessions"] = "on"
    assert browser.submit(page, fields).status in (200, 302)
    browser.close()


def logout_for(backchannel: BackchannelSink, sid: str, wait: float) -> str | None:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for body in list(backchannel.bodies):
            token = body.get("logout_token", [None])[0]
            if token and decode_jwt(token).get("sid") == sid:
                return token
        time.sleep(0.2)
    return None


@pytest.mark.parametrize("sign_out", [True, False], ids=["signs_out_others", "keeps_others"])
def test_a_password_reset_and_the_sessions_that_existed_before_it(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink, backchannel: BackchannelSink, sign_out: bool
) -> None:
    """AC-POL-05. Keycloak notifies the application at once only when the person ticks "sign out
    from other devices". Otherwise the old application session lives until the periodic check
    (next test; not running here) or the next sign-in sees the change; that sign-in ends it,
    and the surviving Keycloak session cannot open a new one."""
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    sid = str(rig.rows("SELECT kc_session_id FROM user_sessions")[0][0])
    time.sleep(3.2)  # beyond the whole-second tolerance of auth_time
    response = rig.another_client().post(
        f"{API}/auth/password-recovery", json={"email": user.email}
    )
    assert response.status_code == 202
    reset_password(env, mail_link(smtp, user.email), sign_out_other_devices=sign_out)
    token = logout_for(backchannel, sid, wait=8 if sign_out else 4)
    assert (token is not None) is sign_out
    if token is not None:
        delivered = rig.api.post(
            f"{API}/auth/oidc/backchannel-logout", data={"logout_token": token}
        )
        assert delivered.status_code == 204
        assert rig.api.get(f"{API}/auth/session").status_code == 401
        return
    assert rig.api.get(f"{API}/auth/session").status_code == 200  # until a check or a sign-in
    old_cookie = rig.api.cookies[SESSION]
    # the old single sign-on session comes back first: nothing survives it
    stale = rig.another_client()
    start = stale.get(f"{AUTH_API}/login", params={"return_to": "/app"})
    silent = rig.at_keycloak(start.headers["location"], None)
    forced = stale.get(silent)
    assert parse_qs(urlparse(forced.headers["location"]).query)["prompt"] == ["login"]
    assert SESSION not in stale.cookies
    assert rig.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(0,)]
    revoked = rig.api.get(f"{AUTH_API}/session", headers={"Cookie": f"{SESSION}={old_cookie}"})
    assert revoked.status_code == 401
    renewed = TestUser(id=user.id, email=user.email, password=NEW_PASSWORD)
    owner = rig.another_client()
    assert rig.sign_in(renewed, client=owner, browser=Browser(env)).status_code == 302
    assert owner.get(f"{AUTH_API}/session").status_code == 200


def test_f0_the_periodic_check_ends_old_sessions_after_a_reset_without_a_sign_in(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink, backchannel: BackchannelSink
) -> None:
    """AC-POL-05 with F-0 (a): the person does not tick "sign out from other devices" and
    nobody signs in; the worker notices the new password and ends the old sessions."""
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    second = rig.another_client()
    assert rig.sign_in(user, client=second, browser=Browser(env)).status_code == 302
    time.sleep(3.2)  # beyond the whole-second tolerance of auth_time

    def check(should_stop: Callable[[], bool]) -> None:
        recovery.check_pending_password_changes(
            rig.runtime,
            create_session_factory(rig.role_env.engine("worker")),
            rig.notices,
            should_stop=should_stop,
        )

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
        response = rig.another_client().post(
            f"{API}/auth/password-recovery", json={"email": user.email}
        )
        assert response.status_code == 202
        link = mail_link(smtp, user.email)
        time.sleep(1)  # several cycles with a pending request and an unchanged password
        assert rig.api.get(f"{AUTH_API}/session").status_code == 200
        reset_password(env, link, sign_out_other_devices=False)
        wait_for(
            lambda: (
                rig.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(0,)]
            )
        )
        wait_for(lambda: bool(rig.notices.notices))
        time.sleep(1)  # further cycles add nothing
    finally:
        assert worker.stop()
    assert rig.api.get(f"{AUTH_API}/session").status_code == 401
    assert second.get(f"{AUTH_API}/session").status_code == 401
    assert [n.kind for n in rig.notices.notices] == [NoticeKind.PASSWORD_RESET_COMPLETED]
    assert rig.rows(
        "SELECT actor_type FROM audit_events WHERE action = 'security.password.changed'"
    ) == [("SYSTEM",)]
    renewed = TestUser(id=user.id, email=user.email, password=NEW_PASSWORD)
    owner = rig.another_client()
    assert rig.sign_in(renewed, client=owner, browser=Browser(env)).status_code == 302
    assert owner.get(f"{AUTH_API}/session").status_code == 200
    assert len(rig.notices.notices) == 1


def test_after_a_password_change_another_signed_in_browser_must_authenticate_again(
    rig: Rig, env: Env, admin: Admin
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    second, elsewhere = rig.another_client(), Browser(env)
    assert rig.sign_in(user, client=second, browser=elsewhere).status_code == 302
    time.sleep(3.2)
    started = rig.api.post(
        f"{API}/me/security/password-change-requests",
        json={"return_to": "/me"},
        headers=secure(rig),
    )
    page = password_form(rig, user, started.json()["redirect_url"])
    done = rig.browser.submit(
        page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location, done.summary
    assert rig.api.get(done.location).status_code == 302
    assert second.get(f"{AUTH_API}/session").status_code == 401
    start = second.get(f"{AUTH_API}/login", params={"return_to": "/app"})
    silent = rig.at_keycloak(start.headers["location"], None, elsewhere)
    forced = second.get(silent)
    assert parse_qs(urlparse(forced.headers["location"]).query)["prompt"] == ["login"]
    assert second.get(f"{AUTH_API}/session").status_code == 401
    assert rig.api.get(f"{AUTH_API}/session").status_code == 200  # the changing browser stays


def test_refresh_token_reuse_is_refused_by_keycloak_without_telling_the_application(
    rig: Rig, env: Env, admin: Admin, backchannel: BackchannelSink
) -> None:
    """AC-MOB-04 / AC-POL-13: the identity provider side holds. The application learns nothing,
    so recording REFRESH_REUSE depends on the event ingestion of F2-T11."""
    user = admin.create_user()
    browser = Browser(env)
    code = browser.login(user, client_id="at-mobile", redirect_uri=MOBILE_REDIRECT).require_code()
    tokens = browser.token("at-mobile", code, MOBILE_REDIRECT)
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert rig.api.post(f"{API}/auth/mobile/session", json={}, headers=bearer).status_code == 201
    sid = decode_jwt(tokens["access_token"])["sid"]
    rotated = browser.refresh("at-mobile", tokens["refresh_token"])
    assert rotated["_status"] == 200
    assert browser.refresh("at-mobile", tokens["refresh_token"])["_status"] == 400
    assert browser.refresh("at-mobile", rotated["refresh_token"])["_status"] == 400
    assert logout_for(backchannel, sid, wait=3) is None
    assert rig.api.get(f"{API}/auth/session", headers=bearer).status_code == 200
    assert rig.rows("SELECT revoked_reason FROM user_sessions") == [(None,)]
