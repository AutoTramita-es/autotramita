"""F2-T09-REC final MFA decision (2026-11-25) against real Keycloak 26.4.7: recovery codes are
the backup of a permanent factor, an account that once had a second factor never falls back to
the password alone, and no e-mail link runs a credential set-up. Runs only in the ``keycloak``
CI job.

The held sign-in with a recovery code was a known gap until the Keycloak security provider; its
test now asserts the protection."""

from __future__ import annotations

import html
import re

import httpx
import pytest
from app.auth.security import recovery
from app.core.db import create_session_factory
from tests.identity.accounts import (
    CODES,
    OTP,
    PASSKEY,
    PASSWORDLESS,
    Account,
    account,
    codes_only_account,
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
    form_action,
    hidden_inputs,
)
from tests.identity.rig import Rig
from tests.identity.test_security_keycloak import NEW_PASSWORD, mail_link

pytestmark = pytest.mark.keycloak

API = "/api/v1"
NEW_CODES = "CONFIGURE_RECOVERY_AUTHN_CODES"
# every way to ask: a level or a credential action
LEVELS: tuple[dict[str, str], ...] = ({}, {"acr_values": "loa1"}, {"acr_values": "loa2"})
CREDENTIAL_ACTIONS: tuple[dict[str, str], ...] = tuple(
    {"kc_action": name} for name in (NEW_CODES, "CONFIGURE_TOTP", "UPDATE_PASSWORD")
)
PERMANENT = (OTP, PASSKEY, PASSWORDLESS)
CLIENTS = {"at-web": WEB_REDIRECT, "at-mobile": MOBILE_REDIRECT}


def shown_kind(kind: str) -> str:
    return PASSKEY if kind == PASSWORDLESS else kind


def password_again(browser: Browser, page: Page, who: Account) -> Page:
    fields = {"password": who.user.password, "credentialId": ""}
    if 'name="username"' in page.text:
        fields["username"] = who.user.email
    return browser.submit(page, fields)


def sessions(admin: Admin, who: Account) -> int:
    return len(admin.master("GET", f"/users/{who.user.id}/sessions").json())


def sign_in_with_code(env: Env, who: Account, **kw: str) -> tuple[Browser, Page]:
    browser = Browser(env)
    page = who.select(browser, browser.login(who.user, **kw), CODES)
    return browser, who.answer_code(browser, page, who.next_code(page))


def spend_last_code(env: Env, who: Account) -> tuple[Browser, Page]:
    who.spend_codes(keep=1)
    return sign_in_with_code(env, who)


def try_to_skip(browser: Browser, page: Page, who: Account) -> None:
    """Every way around a forced one-time code set-up: cancelling it, asking for the next
    action instead, or posting that action's form directly."""
    action = html.unescape(form_action(page.text))
    elsewhere = re.sub(r"execution=[^&]+", f"execution={NEW_CODES}", action)
    before = who.credentials()
    cancelled = browser.submit(
        page, {**hidden_inputs(page.text), "cancel-aia": "true"}, action=action
    )
    assert shown(cancelled) == "otp-setup", cancelled.summary
    forged = {"generatedRecoveryAuthnCodes": ",".join(["ABCD1234EFGH"] * 12), "generatedAt": "1"}
    jumped = browser.get(elsewhere)
    posted = browser.submit(page, forged, action=elsewhere)
    for answer in (jumped, posted):
        assert answer.code is None and shown(answer) != "codes-setup", answer.summary
    assert who.credentials() == before


# --- recovery codes follow a permanent factor ---------------------------------------------------
@pytest.mark.parametrize("client_id", [*sorted(CLIENTS), "account-console"])
def test_a_person_without_a_factor_sets_up_a_one_time_code_before_recovery_codes(
    env: Env, admin: Admin, client_id: str
) -> None:
    """No account can come to hold recovery codes only."""
    redirect = CLIENTS.get(client_id, f"{env.base_url}/realms/{REALM}/account/")
    who = account(admin)
    browser = Browser(env)
    page = browser.login(who.user, client_id=client_id, redirect_uri=redirect, kc_action=NEW_CODES)
    assert shown(page) == "otp-setup", page.summary
    try_to_skip(browser, page, who)
    assert who.credentials() == ["password"]  # left there: nothing was created
    single_sign_on = account(admin)
    other = Browser(env)
    single_sign_on.sign_in(other).require_code()
    page = other.authorize("at-web", WEB_REDIRECT, kc_action=NEW_CODES)
    page = other.sign_in_again(page, single_sign_on.user)
    assert shown(page) == "otp-setup", page.summary
    single_sign_on.otp, page = set_up_otp(other, page)
    assert shown(page) == "codes-setup", page.summary  # only now, after the code was verified
    single_sign_on.codes, done = set_up_codes(other, page)
    done.require_code()
    assert single_sign_on.kinds() == sorted([OTP, CODES])


@pytest.mark.parametrize("first_proof", ["permanent", "recovery_code"])
@pytest.mark.parametrize(
    "factors", [(OTP,), (OTP, CODES), (PASSKEY, CODES), (PASSWORDLESS, CODES)], ids="+".join
)
def test_recovery_codes_are_generated_only_after_a_permanent_factor(
    env: Env, admin: Admin, factors: tuple[str, ...], first_proof: str
) -> None:
    who = account(admin, *factors)
    if first_proof == "recovery_code" and CODES not in factors:
        who.enrol(CODES)
    permanent = shown_kind(factors[0])
    before = who.credential_id(CODES) if CODES in who.kinds() else None
    browser = Browser(env)
    page = browser.login(who.user, kc_action=NEW_CODES)
    if first_proof == "recovery_code":
        page = who.prove(browser, page, CODES)  # accepted for the sign-in, then:
        assert page.code is None, "a recovery code was enough for new recovery codes"
        assert who.offered(browser, page) == {permanent}
        page = who.prove(browser, page, factors[0])
    else:
        page = who.prove(browser, page, factors[0])
    assert shown(page) == "codes-setup", page.summary
    who.codes, done = set_up_codes(browser, page)
    done.require_code()
    assert who.credential_id(CODES) != before


@pytest.mark.parametrize("signed_in_with", [OTP, CODES])
def test_new_recovery_codes_from_single_sign_on_need_the_permanent_factor_again(
    env: Env, admin: Admin, signed_in_with: str
) -> None:
    who = account(admin, OTP, CODES)
    browser = Browser(env)
    who.sign_in(browser, signed_in_with).require_code()
    page = browser.authorize("at-web", WEB_REDIRECT, kc_action=NEW_CODES)
    page = browser.sign_in_again(page, who.user)
    assert page.code is None and who.offered(browser, page) == {OTP}, page.summary
    page = who.prove(browser, page, OTP)
    assert shown(page) == "codes-setup", page.summary  # one question, not two


def test_a_step_up_of_an_existing_session_never_takes_a_recovery_code(
    env: Env, admin: Admin
) -> None:
    """So a set of codes can only run out at a password sign-in, where it is handled."""
    who = account(admin, OTP, CODES)
    browser = Browser(env)
    who.sign_in(browser).require_code()
    page = browser.authorize("at-web", WEB_REDIRECT, acr_values="loa2")
    assert page.code is None and who.offered(browser, page) == {OTP}, page.summary
    who.prove(browser, page, OTP).require_code()


# --- the last recovery code ---------------------------------------------------------------------
@pytest.mark.parametrize("factor", [OTP, PASSKEY])
def test_spending_the_last_code_needs_the_permanent_factor_and_ends_every_other_session(
    env: Env, admin: Admin, factor: str
) -> None:
    who = account(admin, factor, CODES)
    web, signed = sign_in_with_code(env, who)
    web_tokens = web.token("at-web", signed.require_code(), WEB_REDIRECT)
    phone, signed = sign_in_with_code(env, who, client_id="at-mobile", redirect_uri=MOBILE_REDIRECT)
    phone_tokens = phone.token("at-mobile", signed.require_code(), MOBILE_REDIRECT)
    browser, page = spend_last_code(env, who)
    assert page.code is None and who.offered(browser, page) == {factor}, page.summary
    assert who.kinds() == [factor] and who.required_actions() == [NEW_CODES]
    assert sessions(admin, who) == 0
    assert web.refresh("at-web", web_tokens["refresh_token"])["_status"] == 400
    assert phone.refresh("at-mobile", phone_tokens["refresh_token"])["_status"] == 400
    for other, client_id in ((web, "at-web"), (phone, "at-mobile")):
        again = other.authorize(client_id, CLIENTS[client_id])
        assert shown(again) == "password", again.summary
    page = who.prove(browser, page, factor)  # the owner goes on:
    assert shown(page) == "codes-setup", page.summary  # new codes, after the factor
    who.codes, done = set_up_codes(browser, page)
    done.require_code()
    assert who.kinds() == sorted([factor, CODES])


def test_an_abandoned_regeneration_is_never_served_to_the_password_alone(
    env: Env, admin: Admin
) -> None:
    """F-1R-B, closed: the pending set-up stays on the account and is reached only through the
    permanent factor."""
    who = account(admin, OTP, CODES)
    spend_last_code(env, who)  # and leaves
    assert who.required_actions() == [NEW_CODES]
    for client_id, redirect in CLIENTS.items():
        for extra in (*LEVELS, *CREDENTIAL_ACTIONS):
            browser = Browser(env)
            page = browser.login(who.user, client_id=client_id, redirect_uri=redirect, **extra)
            assert page.code is None and shown(page) == OTP, (extra, page.summary)
    assert who.credentials() == [OTP, "password"]
    browser = Browser(env)
    page = who.sign_in(browser)
    assert shown(page) == "codes-setup", page.summary


def test_without_the_permanent_factor_the_last_code_signs_nobody_in(env: Env, admin: Admin) -> None:
    """A lost authenticator and the last code: the account stays closed until a controlled
    recovery (T10/T11), it does not open to the password."""
    who = account(admin, OTP, CODES)
    browser, page = spend_last_code(env, who)
    wrong = browser.submit(
        page, {**hidden_inputs(page.text), "otp": "000000"}, action=form_action(page.text)
    )
    assert wrong.code is None and shown(wrong) == OTP
    again = Browser(env)
    page = again.login(who.user, acr_values="loa2")
    assert page.code is None and shown(page) == OTP and sessions(admin, who) == 0


def test_two_sign_ins_at_once_leave_no_session_from_before_the_last_code(
    env: Env, admin: Admin
) -> None:
    who = account(admin, OTP, CODES)
    who.spend_codes(keep=2)
    first, second = Browser(env), Browser(env)
    first_page = who.select(first, first.login(who.user), CODES)
    second_page = second.login(who.user)
    number = who.asked_number(first_page)
    who.answer_code(first, first_page, who.codes[number - 1]).require_code()
    second_page = who.select(second, second_page, CODES)
    asked = who.answer_code(second, second_page, who.next_code(second_page))
    assert asked.code is None and shown(asked) == OTP, asked.summary
    assert sessions(admin, who) == 0
    assert shown(first.authorize("at-web", WEB_REDIRECT)) == "password"


def test_a_sign_in_held_open_with_a_code_gets_no_new_codes_after_the_last_one(
    env: Env, admin: Admin
) -> None:
    """The open recovery authentication finding, closed by the Keycloak security provider:
    whoever has the password and an unused recovery code holds a sign-in open on another pending
    page while the last code is spent elsewhere. When the held sign-in goes on, the pending new
    codes are refused: it proved a recovery code, not a permanent factor."""
    who = account(admin, OTP, CODES)
    who.spend_codes(keep=2)
    path = f"/users/{who.user.id}"
    found = admin.master("GET", path).json()
    admin.master(
        "PUT", path, json={**found, "requiredActions": ["UPDATE_PROFILE"]}
    ).raise_for_status()
    held, page = sign_in_with_code(env, who)
    assert 'name="firstName"' in page.text, page.summary  # the profile page, held open
    sign_in_with_code(env, who)  # the last code, elsewhere
    assert "CONFIGURE_RECOVERY_AUTHN_CODES" in who.required_actions()
    profile = {"firstName": "Ana", "lastName": "Test", "email": who.user.email}
    done = held.submit(page, {**hidden_inputs(page.text), **profile}, action=form_action(page.text))
    assert done.code is None and done.location and "error=access_denied" in done.location
    assert who.kinds() == [OTP]


# --- accounts that hold recovery codes only -----------------------------------------------------
@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_an_unmarked_codes_only_account_is_refused(env: Env, admin: Admin, client_id: str) -> None:
    """Fail closed: an account an operator has not marked cannot spend its codes at all."""
    who = codes_only_account(admin, marked=False)
    browser = Browser(env)
    page = browser.login(who.user, client_id=client_id, redirect_uri=CLIENTS[client_id])
    assert page.code is None and shown(page) == "denied", page.summary
    assert who.credentials() == ["password", CODES] and sessions(admin, who) == 0


@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_a_marked_codes_only_account_moves_to_a_permanent_factor(
    env: Env, admin: Admin, client_id: str
) -> None:
    who = codes_only_account(admin, marked=True)
    redirect = CLIENTS[client_id]
    for _ in range(2):  # abandoning the set-up changes nothing but the spent code
        browser = Browser(env)
        page = browser.login(who.user, client_id=client_id, redirect_uri=redirect)
        assert shown(page) == CODES, page.summary  # the existing factor first
        page = who.answer_code(browser, page, who.next_code(page))
        assert shown(page) == "otp-setup", page.summary
        try_to_skip(browser, page, who)
        assert who.credentials() == ["password", CODES] and sessions(admin, who) == 0
    who.otp, done = set_up_otp(browser, page)
    done.require_code()
    assert who.kinds() == sorted([OTP, CODES])
    for kind in (OTP, CODES):  # an ordinary account now, the codes its backup
        browser = Browser(env)
        who.sign_in(browser, kind).require_code()


def test_the_application_request_moves_a_codes_only_account_too(env: Env, admin: Admin) -> None:
    who = codes_only_account(admin, marked=True)
    browser = Browser(env)
    page = browser.login(
        who.user, kc_action="CONFIGURE_TOTP", acr_values="loa2", prompt="login", max_age="0"
    )
    page = who.prove(browser, page, CODES)
    for _ in range(2):  # the forced set-up, then the requested one
        if shown(page) == "otp-setup":
            who.otp, page = set_up_otp(browser, page)
    tokens = browser.token("at-web", page.require_code(), WEB_REDIRECT)
    claims = decode_jwt(tokens["id_token"])
    assert claims["acr"] == "loa2" and '"2"' in str(claims["loa_map"])


def locked_account(env: Env, admin: Admin) -> Account:
    """Marked, every code spent, the set-up of a one-time code abandoned each time. After the
    last code the set-up is refused too (the provider): nothing usable is left to prove."""
    who = codes_only_account(admin, marked=True)
    for position in range(len(who.codes)):
        _, page = sign_in_with_code(env, who)
        last = position == len(who.codes) - 1
        if last:
            assert page.code is None and page.location and "error=access_denied" in page.location
        else:
            assert page.code is None and shown(page) == "otp-setup", (position, page.summary)
    assert who.kinds() == [] and sessions(admin, who) == 0
    return who


def refused_everywhere(env: Env, who: Account) -> None:
    """Denied; after several refusals Keycloak's brute-force protection answers with its
    sign-in form instead. Never a code, a set-up or a password form."""
    account_console = f"{env.base_url}/realms/{REALM}/account/"
    for client_id, redirect in [*CLIENTS.items(), ("account-console", account_console)]:
        for extra in (*LEVELS, *CREDENTIAL_ACTIONS):
            browser = Browser(env)
            page = browser.login(who.user, client_id=client_id, redirect_uri=redirect, **extra)
            assert page.code is None, (client_id, extra)
            assert shown(page) in ("denied", "password"), (client_id, extra, page.summary)


def test_the_last_code_of_a_codes_only_account_leaves_it_closed(env: Env, admin: Admin) -> None:
    """Spending it never turns the account into a password-only one."""
    who = locked_account(env, admin)
    refused_everywhere(env, who)
    assert who.credentials() == ["password"]


@pytest.mark.parametrize("move", ["wrong_code", "reload", "other_method", "restart", "empty_post"])
def test_a_sign_in_left_at_the_code_question_gains_nothing_when_the_codes_run_out(
    env: Env, admin: Admin, move: str
) -> None:
    who = codes_only_account(admin, marked=True)
    parked = Browser(env)
    page = parked.login(who.user)  # the password, then it waits
    assert shown(page) == CODES
    for _ in range(len(who.codes)):
        sign_in_with_code(env, who)
    action = html.unescape(form_action(page.text))
    if move == "wrong_code":
        answer = who.answer_code(parked, page, "AAAAAAAAAAAA")
    elif move == "reload":
        answer = parked.get(action)
    elif move == "other_method":
        answer = parked.submit(
            page, {**hidden_inputs(page.text), "tryAnotherWay": "on"}, action=action
        )
    elif move == "restart":
        answer = parked.authorize("at-web", WEB_REDIRECT)
        if shown(answer) == "password":
            answer = password_again(parked, answer, who)
    else:
        answer = parked.submit(page, {}, action=action)
    assert answer.code is None and shown(answer) not in ("otp-setup", "codes-setup"), answer.summary
    assert who.credentials() == ["password"] and sessions(admin, who) == 0


def test_an_administrator_removing_the_factor_of_a_marked_account_does_not_open_it(
    env: Env, admin: Admin
) -> None:
    who = account(admin, OTP)
    who.mark()
    who.remove_as_administrator(OTP)
    refused_everywhere(env, who)


def test_the_user_can_neither_see_nor_lift_the_factor_obligation(env: Env, admin: Admin) -> None:
    who = account(admin, OTP)
    who.mark()
    base = f"{env.base_url}/realms/{REALM}/account/"
    browser = Browser(env)
    page = who.sign_in(browser, client_id="account-console", redirect_uri=base)
    tokens = browser.token("account-console", page.require_code(), base)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    profile = httpx.get(base, headers=headers).json()
    assert "at_mfa_required" not in str(profile)
    path = f"/users/{who.user.id}"
    attempts: tuple[dict[str, list[str]], ...] = (
        {},
        {"at_mfa_required": ["false"]},
        {"at_mfa_required": []},
    )
    for attributes in attempts:
        httpx.post(base, headers=headers, json={**profile, "attributes": attributes})
        assert admin.master("GET", path).json()["attributes"]["at_mfa_required"] == ["true"]


def test_people_without_the_marker_who_never_had_a_factor_are_not_affected(
    env: Env, admin: Admin
) -> None:
    who = account(admin)
    browser = Browser(env)
    browser.login(who.user).require_code()
    browser.authorize("at-web", WEB_REDIRECT).require_code()
    assert who.required_actions() == []


# --- a forgotten password -----------------------------------------------------------------------
def open_link(env: Env, link: str, password: str = NEW_PASSWORD) -> tuple[Browser, Page]:
    """Follow a link Keycloak mailed, setting the new password when asked."""
    browser = Browser(env)
    browser._last = WEB_REDIRECT
    page = browser.get(link)
    for _ in range(3):
        if shown(page) != "other":
            break
        proceed = re.search(r'href="([^"]*(?:action-token|login-actions)[^"]*)"', page.text)
        if not proceed:
            break
        page = browser.get(html.unescape(proceed.group(1)))
    if shown(page) == "new-password":
        page = browser.submit(page, {"password-new": password, "password-confirm": password})
    return browser, page


def with_new_password(who: Account) -> Account:
    who.user = TestUser(id=who.user.id, email=who.user.email, password=NEW_PASSWORD)
    return who


@pytest.mark.parametrize("state", ["spent_codes", "locked"])
def test_a_recovery_link_runs_no_pending_set_up(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink, state: str
) -> None:
    """The link proves the mailbox only. The application withdraws pending set-ups before it
    asks Keycloak to send it, so it changes the password and nothing else."""
    if state == "locked":
        who = locked_account(env, admin)
    else:
        who = account(admin, OTP, CODES)
        spend_last_code(env, who)
    assert who.required_actions() == [NEW_CODES]
    factors = who.kinds()
    asked = rig.api.post(f"{API}/auth/password-recovery", json={"email": who.user.email})
    assert asked.status_code == 202
    browser, page = open_link(env, mail_link(smtp, who.user.email))
    assert shown(page) not in ("codes-setup", "otp-setup"), page.summary
    with_new_password(who)
    assert who.kinds() == factors and who.required_actions() == []
    after = browser.authorize("at-web", WEB_REDIRECT)
    assert shown(after) == "password", "the link left somebody signed in"
    page = Browser(env).login(who.user)
    assert page.code is None
    assert shown(page) == ("denied" if state == "locked" else OTP), page.summary


def test_a_link_sent_past_the_application_runs_no_set_up_either(
    env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    """Keycloak runs every pending action for the holder of an e-mail link. Sent past the
    application (only administrators can: ``resetPasswordAllowed`` is off), the pending new codes
    are refused by the provider: a mailbox proves no factor."""
    who = account(admin, OTP, CODES)
    spend_last_code(env, who)
    sent = admin.service(
        "PUT",
        f"/users/{who.user.id}/execute-actions-email",
        params={"client_id": "at-web", "redirect_uri": WEB_REDIRECT},
        json=["UPDATE_PASSWORD"],
    )
    sent.raise_for_status()
    _, page = open_link(env, mail_link(smtp, who.user.email))
    assert page.code is None and page.location and "error=access_denied" in page.location
    assert who.kinds() == [OTP]


def test_the_worker_withdraws_a_set_up_that_became_pending_after_the_mail(
    rig: Rig, env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    who = account(admin, OTP, CODES)
    who.spend_codes(keep=1)
    asked = rig.api.post(f"{API}/auth/password-recovery", json={"email": who.user.email})
    assert asked.status_code == 202
    link = mail_link(smtp, who.user.email)
    sign_in_with_code(env, who)  # the last code, after the mail
    assert who.required_actions() == [NEW_CODES]
    recovery.check_pending_password_changes(
        rig.runtime, create_session_factory(rig.role_env.engine("worker")), rig.notices
    )
    assert who.required_actions() == []
    _, page = open_link(env, link)
    assert shown(page) not in ("codes-setup", "otp-setup"), page.summary
    assert who.kinds() == [OTP]
