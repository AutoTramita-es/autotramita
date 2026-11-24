"""F2-T09 against real Keycloak 26.4.7: the admin client, password recovery owned by the
application, password change and second-factor enrolment through ``kc_action``, and removal of
a factor, on real PostgreSQL and Redis. Runs only in the ``keycloak`` CI job.

AC-POL-01/02 (brute force, no lock-out hint), AC-POL-07 (password policy) and AC-POL-08 (no MFA
forced on a dealership user) are proven by the T01 realm tests S1, S10 and S3 in
``test_keycloak_spike.py``; they are not repeated here."""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from app.auth.idp import IdpAdminError
from app.auth.idp_admin import KeycloakAdmin
from app.auth.security.notify import NoticeKind
from app.auth.web.csrf import csrf_token
from tests.identity.kc import (
    Admin,
    Browser,
    Env,
    SmtpSink,
    TestUser,
    form_action,
    hidden_inputs,
    record_result,
    totp,
)
from tests.identity.rig import API as AUTH_API
from tests.identity.rig import ORIGIN, SESSION, Rig

pytestmark = pytest.mark.keycloak

API = "/api/v1"
NEW_PASSWORD = "Another-correct-horse-9"
HOME = f"{ORIGIN}/"


def secure(rig: Rig, client=None) -> dict[str, str]:  # type: ignore[no-untyped-def]
    jar = (client or rig.api).cookies
    return {"X-CSRF-Token": csrf_token(jar[SESSION]), "Origin": ORIGIN}


def mail_link(smtp: SmtpSink, email: str, *, after: int = 0) -> str:
    mails = smtp.for_recipient(email)
    assert len(mails) > after, f"no e-mail for {email}"
    link = re.search(r"https?://[^\s\"<>]+action-token[^\s\"<>]*", mails[after]["body"])
    assert link, mails[after]["body"][:300]
    return link.group(0).replace("&amp;", "&")


def set_new_password(env: Env, link: str, password: str = NEW_PASSWORD) -> None:
    """Follow the recovery link with a clean browser and fill Keycloak's new-password form."""
    browser = Browser(env)
    browser._last = HOME
    page = browser.get(link)
    for _ in range(3):  # an intermediate "proceed" page may come first
        if "password-new" in page.text:
            break
        proceed = re.search(r'href="([^"]*(?:action-token|login-actions)[^"]*)"', page.text)
        assert proceed, f"unexpected page while following the recovery link: {page.summary}"
        page = browser.get(proceed.group(1).replace("&amp;", "&"))
    assert "password-new" in page.text, page.summary
    done = browser.submit(page, {"password-new": password, "password-confirm": password})
    assert done.status in (200, 302), done.summary
    browser.close()


def settings_admin(rig: Rig) -> KeycloakAdmin:
    admin = rig.runtime.admin
    assert isinstance(admin, KeycloakAdmin)
    return admin


# --- the real admin client ------------------------------------------------------------------------
def test_the_admin_client_finds_users_lists_credentials_and_sends_the_recovery_mail(
    rig: Rig, admin: Admin, smtp: SmtpSink
) -> None:
    user = admin.create_user()
    client = settings_admin(rig)
    found = client.find_user_by_email(user.email)
    assert found is not None and found.subject == user.id and found.enabled and found.email_verified
    assert client.find_user_by_email("nobody-here@example.test") is None
    kinds = {c.type for c in client.list_credentials(user.id)}
    assert kinds == {"password"}
    client.send_actions_email(
        user.id, ["UPDATE_PASSWORD"], lifespan_seconds=1800, redirect_uri=HOME
    )
    assert smtp.for_recipient(user.email), "Keycloak sent no recovery mail"
    client.set_user_enabled(user.id, enabled=False)
    again = client.find_user_by_email(user.email)
    assert again is not None and not again.enabled
    client.set_user_enabled(user.id, enabled=True)
    with pytest.raises(IdpAdminError):
        client.send_actions_email(
            user.id,
            ["UPDATE_PASSWORD"],
            lifespan_seconds=1800,
            redirect_uri="https://evil.example/",
        )  # Keycloak refuses a redirect the client does not own


# --- recovery (AC-POL-03..05) -----------------------------------------------------------------
def test_recovery_through_keycloak_sends_one_mail_to_real_accounts_only_and_ends_sessions_after_the_reset(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    user = admin.create_user()
    other = admin.create_user()
    admin.master("PUT", f"/users/{other.id}", json={"enabled": False}).raise_for_status()
    assert rig.sign_in(user).status_code == 302
    old_cookie = rig.api.cookies[SESSION]
    answers = {
        label: rig.another_client().post(f"{API}/auth/password-recovery", json={"email": address})
        for label, address in {
            "real": user.email,
            "disabled": other.email,
            "unknown": "nobody-at-all@example.test",
        }.items()
    }
    assert {a.status_code for a in answers.values()} == {202}
    assert len({a.text for a in answers.values()}) == 1
    assert smtp.for_recipient(user.email)
    time.sleep(1.0)
    assert smtp.for_recipient(other.email, wait=1.0) == []
    assert rig.rows(
        "SELECT count(*) FROM audit_events WHERE action = 'security.password.recovery.requested'"
    ) == [(3,)]
    still = rig.api.get(f"{AUTH_API}/session")
    assert still.status_code == 200  # requesting recovery ends nothing
    set_new_password(env, mail_link(smtp, user.email))
    assert rig.sign_in(user).status_code == 302  # SSO still alive in the scripted browser
    stale = rig.api.get(f"{AUTH_API}/session", headers={"Cookie": f"{SESSION}={old_cookie}"})
    assert stale.status_code == 401
    assert NoticeKind.PASSWORD_RESET_COMPLETED in [n.kind for n in rig.notices.notices]
    assert rig.rows(
        "SELECT count(*) FROM user_sessions WHERE revoked_reason = 'PASSWORD_CHANGED'"
    ) == [(1,)]


def test_the_recovery_link_works_once(rig: Rig, env: Env, admin: Admin, smtp: SmtpSink) -> None:
    user = admin.create_user()
    rig.another_client().post(f"{API}/auth/password-recovery", json={"email": user.email})
    link = mail_link(smtp, user.email)
    set_new_password(env, link)
    again = Browser(env)
    again._last = HOME
    page = again.get(link)
    assert "password-new" not in page.text, "the recovery link was usable twice"
    again.close()


def test_the_fourth_recovery_request_in_an_hour_sends_no_fourth_mail(
    rig: Rig, admin: Admin, smtp: SmtpSink
) -> None:
    user = admin.create_user()
    codes = [
        rig.another_client()
        .post(f"{API}/auth/password-recovery", json={"email": user.email})
        .status_code
        for _ in range(4)
    ]
    assert codes == [202] * 4
    deadline = time.monotonic() + 10
    while len(smtp.for_recipient(user.email, wait=0.1)) < 3 and time.monotonic() < deadline:
        time.sleep(0.3)
    time.sleep(1.5)
    assert len([m for m in smtp.messages if user.email in m["to"]]) == 3


# --- password change through kc_action (AC-POL-06) ----------------------------------------------
def test_password_change_through_keycloak_ends_other_sessions_and_rotates_this_one(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    second = rig.another_client()
    assert rig.sign_in(user, client=second).status_code == 302
    old = rig.api.cookies[SESSION]
    started = rig.api.post(
        f"{API}/me/security/password-change-requests",
        json={"return_to": "/me"},
        headers=secure(rig),
    )
    assert started.status_code == 200, started.text
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    page = rig.browser._settle(
        rig.browser.http.get(started.json()["redirect_url"]), rig.browser._last
    )
    assert page.location is None and "password-new" in page.text, page.summary
    done = rig.browser.submit(
        page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    )
    assert done.location and parse_qs(urlparse(done.location).query)["kc_action_status"] == [
        "success"
    ], done.summary
    finished = rig.api.get(done.location)
    assert (
        finished.status_code == 302
        and finished.headers["location"] == "/me?security_action=success"
    )
    assert rig.api.cookies[SESSION] != old
    assert rig.api.get(f"{AUTH_API}/session").status_code == 200
    assert second.get(f"{AUTH_API}/session").status_code == 401
    assert [n.kind for n in rig.notices.notices] == [NoticeKind.PASSWORD_CHANGED]
    overview = rig.api.get(f"{API}/me/security").json()
    assert overview["password_changed_at"] is not None and overview["second_factors"] == []


# --- second factors (AC-POL-06/08/10) --------------------------------------------------------------
def enrol_totp(rig: Rig, user: TestUser) -> str:
    started = rig.api.post(
        f"{API}/me/security/mfa-enrollment-requests",
        json={"factor": "TOTP", "return_to": "/me"},
        headers=secure(rig),
    )
    assert started.status_code == 200, started.text
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    page = rig.browser._settle(
        rig.browser.http.get(started.json()["redirect_url"]), rig.browser._last
    )
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    if not secret:
        manual = re.search(r'href="([^"]*mode=manual[^"]*)"', page.text)
        assert manual, page.summary
        page = rig.browser.get(manual.group(1).replace("&amp;", "&"))
        secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    assert secret, page.summary
    fields = hidden_inputs(page.text)
    fields.update({"totp": totp(secret.group(1).strip()), "userLabel": "t09"})
    done = rig.browser.submit(page, fields, action=form_action(page.text))
    assert done.location and parse_qs(urlparse(done.location).query)["kc_action_status"] == [
        "success"
    ], done.summary
    finished = rig.api.get(done.location)
    assert finished.headers["location"] == "/me?security_action=success", finished.text
    return secret.group(1).strip()


def test_a_second_factor_is_enrolled_listed_required_for_removal_and_removed(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    assert (
        rig.sign_in(user).status_code == 302
    )  # password only: a dealership user is not forced to MFA
    secret = enrol_totp(rig, user)
    assert [n.kind for n in rig.notices.notices] == [NoticeKind.MFA_ENROLLED]
    factors = rig.api.get(f"{API}/me/security").json()["second_factors"]
    assert [f["type"] for f in factors] == ["otp"]
    refused = rig.api.delete(
        f"{API}/me/security/second-factors/{factors[0]['id']}", headers=secure(rig)
    )
    assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED"
    asked = rig.api.post(
        f"{AUTH_API}/step-up", json={"purpose": "MFA", "return_to": "/me"}, headers=secure(rig)
    )
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    page = rig.browser._settle(
        rig.browser.http.get(asked.json()["redirect_url"]), rig.browser._last
    )
    if page.location is None:  # Keycloak asks for the code (the next 30 s window: no reuse)
        fields = hidden_inputs(page.text)
        fields["otp"] = totp(secret, at=time.time() + 30)
        page = rig.browser.submit(page, fields, action=form_action(page.text))
    assert page.location, page.summary
    assert rig.api.get(page.location).status_code == 302
    assert rig.api.get(f"{AUTH_API}/session").json()["auth_level"] == "LOA2"
    gone = rig.api.delete(
        f"{API}/me/security/second-factors/{factors[0]['id']}", headers=secure(rig)
    )
    assert gone.status_code == 204, gone.text
    assert rig.api.get(f"{API}/me/security").json()["second_factors"] == []
    assert NoticeKind.MFA_REMOVED in [n.kind for n in rig.notices.notices]
    assert rig.rows(
        "SELECT details->>'factor' FROM audit_events WHERE action = 'security.mfa.removed'"
    ) == [("TOTP",)]


def test_recovery_codes_can_be_enrolled_through_keycloak_d41(rig: Rig, admin: Admin) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    started = rig.api.post(
        f"{API}/me/security/mfa-enrollment-requests",
        json={"factor": "RECOVERY_CODES", "return_to": "/me"},
        headers=secure(rig),
    )
    rig.browser._last = f"{ORIGIN}{AUTH_API}/callback"
    page = rig.browser._settle(
        rig.browser.http.get(started.json()["redirect_url"]), rig.browser._last
    )
    record_result("T09.recovery_codes_page", page.summary[:200])
    assert page.location is None and "recovery" in page.text.lower(), page.summary
    fields = hidden_inputs(page.text)
    for checkbox in re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"', page.text):
        fields[checkbox] = "on"
    done = rig.browser.submit(page, fields, action=form_action(page.text))
    assert done.location and parse_qs(urlparse(done.location).query).get("kc_action_status") == [
        "success"
    ], done.summary
    assert rig.api.get(done.location).headers["location"] == "/me?security_action=success"
    types = [f["type"] for f in rig.api.get(f"{API}/me/security").json()["second_factors"]]
    assert types == ["recovery-authn-codes"]
    record_result("T09.recovery_codes_full_flow", "works on 26.4.7")
