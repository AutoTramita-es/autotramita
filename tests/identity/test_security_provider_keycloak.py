"""The AutoTramita Keycloak security provider (identity/keycloak/provider) against the real
Keycloak 26.4.7 image it is built into. Runs only in the ``keycloak`` CI job.

The provider takes the credential decision when a form is *submitted*: under a database row lock
of the person (held across Keycloak instances sharing the database), on freshly read state, in the
same transaction as the change. These tests turn the three findings the realm alone could not close
(F-1R-C, the rest of F-3K, a held sign-in with a recovery code) into regressions and prove the
automatic obligation, the controlled switch-off and the concurrency guarantees. The tests on two
instances use ``TEST_KEYCLOAK_NODE_URLS`` (two nodes on one PostgreSQL database, local caches)."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from tests.identity.accounts import (
    CODES,
    OTP,
    PASSKEY,
    Account,
    account,
    codes_only_account,
    registration_allowed,
    set_up_codes,
    set_up_otp,
    shown,
)
from tests.identity.kc import (
    REALM,
    WEB_REDIRECT,
    Admin,
    Browser,
    Env,
    Page,
    TestUser,
    form_action,
    hidden_inputs,
    totp,
)
from tests.identity.rig import API as AUTH_API
from tests.identity.rig import Rig
from tests.identity.test_second_factor_keycloak import follow, password_then_factor, step_up
from tests.identity.test_security_keycloak import NEW_PASSWORD, secure
from tests.identity.webauthn import SoftwareKey, register

pytestmark = pytest.mark.keycloak

API = "/api/v1"
GUARDED = (
    "CONFIGURE_TOTP",
    "CONFIGURE_RECOVERY_AUTHN_CODES",
    "UPDATE_PASSWORD",
    "webauthn-register",
    "webauthn-register-passwordless",
    "at-disable-mfa",
)


# --- helpers -----------------------------------------------------------------------------------
def outcome(page: Page) -> str:
    """``code`` (done), ``refused`` (the provider said no), or the page shown."""
    if page.location:
        if page.code:
            return "code"
        if "error=access_denied" in page.location:
            return "refused"
        return "redirect"
    return shown(page)


def open_totp_form(browser: Browser, user: TestUser, **kw: str) -> Page:
    """The one-time code set-up form with its secret, as the browser holds it."""
    page = browser.login(user, kc_action="CONFIGURE_TOTP", **kw)
    manual = re.search(r'href="([^"]*mode=manual[^"]*)"', page.text)
    if manual:
        page = browser.get(manual.group(1).replace("&amp;", "&"))
    assert 'id="kc-totp-secret-key"' in page.text, page.summary
    return page


def submit_totp(browser: Browser, page: Page, label: str) -> Page:
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    assert secret, page.summary
    fields = {**hidden_inputs(page.text), "totp": totp(secret.group(1).strip()), "userLabel": label}
    return browser.submit(page, fields, action=form_action(page.text))


def submit_codes(browser: Browser, page: Page) -> Page:
    fields = hidden_inputs(page.text)
    for box in re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"', page.text):
        fields[box] = "on"
    return browser.submit(page, fields, action=form_action(page.text))


def attributes(admin: Admin, user: TestUser) -> dict[str, list[str]]:
    found: dict[str, list[str]] = (
        admin.master("GET", f"/users/{user.id}").json().get("attributes") or {}
    )
    return found


def obliged(admin: Admin, user: TestUser) -> bool:
    return attributes(admin, user).get("at_mfa_required") == ["true"]


def kinds(admin: Admin, user: TestUser) -> list[str]:
    found = admin.master("GET", f"/users/{user.id}/credentials").json()
    return sorted(str(c["type"]) for c in found)


def together(*calls: Callable[[], Page]) -> list[Page]:
    """Run the calls at the same moment, one thread each."""
    results: list[Page | None] = [None] * len(calls)
    barrier = threading.Barrier(len(calls))

    def run(index: int) -> None:
        barrier.wait(timeout=30)
        results[index] = calls[index]()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert all(r is not None for r in results)
    return [r for r in results if r is not None]


def refusals(admin: Admin, user: TestUser) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = admin.master(
        "GET", "/events", params={"type": "CUSTOM_REQUIRED_ACTION_ERROR", "user": user.id}
    ).json()
    return [e for e in events if e.get("error") == "credential_change_refused"]


# --- the provider is there and replaces the built-in actions ---------------------------------
def test_the_provider_replaces_every_credential_action_and_guards_the_sign_in(admin: Admin) -> None:
    providers = admin.server("GET", "/serverinfo").json()["providers"]
    actions = providers["required-action"]["providers"]
    for action in GUARDED:
        assert actions[action]["operationalInfo"]["autotramita-guard"] == "1.0.0", action
    assert "at-security-guard" in providers["authenticator"]["providers"]
    executions = admin.master("GET", "/authentication/flows/browser-loa-forms/executions").json()
    assert executions[0]["providerId"] == "at-security-guard"
    assert executions[0]["requirement"] == "REQUIRED"


# --- the three findings (F-1R-C, the rest of F-3K, a held sign-in with a code) are regressions in
# test_second_factor_keycloak.py and test_recovery_codes_keycloak.py; here what remains of them.
def test_a_held_form_is_refused_and_the_refusal_is_recorded(env: Env, admin: Admin) -> None:
    who = account(admin)
    intruder = Browser(env)
    held = open_totp_form(intruder, who.user)
    who.enrol(OTP)
    done = submit_totp(intruder, held, "intruder")
    assert outcome(done) == "refused", done.summary
    assert kinds(admin, who.user) == ["otp", "password"]
    reasons = [e["details"].get("reason") for e in refusals(admin, who.user)]
    assert reasons == ["permanent_factor_required"]


# --- the automatic obligation ------------------------------------------------------------------
def test_the_first_permanent_factor_makes_the_obligation_permanent(env: Env, admin: Admin) -> None:
    who = account(admin)
    page = Browser(env).login(who.user, kc_action="CONFIGURE_TOTP")
    assert not obliged(admin, who.user)  # opening the form changes nothing
    who.enrol(OTP)
    assert obliged(admin, who.user)
    passkey = account(admin)
    passkey.enrol(PASSKEY)
    assert obliged(admin, passkey.user)
    assert page.code is None


def test_opening_and_abandoning_a_set_up_never_sets_the_obligation(env: Env, admin: Admin) -> None:
    who = account(admin)
    browser = Browser(env)
    held = open_totp_form(browser, who.user)
    wrong = browser.submit(
        held,
        {**hidden_inputs(held.text), "totp": "000000", "userLabel": "x"},
        action=form_action(held.text),
    )
    assert wrong.code is None and kinds(admin, who.user) == ["password"]
    assert not obliged(admin, who.user)


# --- what may change, and with which proof ----------------------------------------------------
@pytest.mark.parametrize("proof", [OTP, CODES])
def test_a_second_one_time_code_needs_the_permanent_factor_in_this_sign_in(
    env: Env, admin: Admin, proof: str
) -> None:
    who = account(admin, OTP, CODES)
    browser = Browser(env)
    page = browser.login(who.user, kc_action="CONFIGURE_TOTP")
    page = who.prove(browser, page, proof)
    if proof == CODES:
        # the realm accepts the code for the sign-in; the provider refuses the set-up
        assert outcome(page) == "refused", page.summary
        assert kinds(admin, who.user) == ["otp", "password", "recovery-authn-codes"]
        return
    _, done = set_up_otp(browser, page, label="second")
    assert outcome(done) == "code", done.summary
    assert kinds(admin, who.user) == ["otp", "otp", "password", "recovery-authn-codes"]


def test_new_recovery_codes_follow_a_one_time_code_set_up_in_the_same_sign_in(
    env: Env, admin: Admin
) -> None:
    who = account(admin)
    browser = Browser(env)
    page = browser.login(who.user, kc_action="CONFIGURE_RECOVERY_AUTHN_CODES")
    assert shown(page) == "otp-setup", page.summary
    who.otp, page = set_up_otp(browser, page)
    assert shown(page) == "codes-setup", page.summary
    who.codes, done = set_up_codes(browser, page)
    assert outcome(done) == "code" and kinds(admin, who.user) == [
        "otp",
        "password",
        "recovery-authn-codes",
    ]


def test_a_password_change_needs_the_permanent_factor_not_a_code(env: Env, admin: Admin) -> None:
    who = account(admin, OTP, CODES)
    browser = Browser(env)
    page = who.prove(browser, browser.login(who.user, kc_action="UPDATE_PASSWORD"), CODES)
    assert outcome(page) == "refused", page.summary
    browser = Browser(env)
    page = who.prove(browser, browser.login(who.user, kc_action="UPDATE_PASSWORD"), OTP)
    assert shown(page) == "new-password", page.summary
    done = browser.submit(page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD})
    assert outcome(done) == "code", done.summary


def test_people_without_a_factor_change_their_password_as_before(env: Env, admin: Admin) -> None:
    who = account(admin)
    browser = Browser(env)
    page = browser.login(who.user, kc_action="UPDATE_PASSWORD")
    done = browser.submit(page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD})
    assert outcome(done) == "code" and not obliged(admin, who.user)


def test_an_obliged_account_without_a_factor_cannot_set_one_up(env: Env, admin: Admin) -> None:
    who = account(admin, OTP)
    who.remove_as_administrator(OTP)  # obliged, nothing left: closed until a controlled recovery
    for action in ("CONFIGURE_TOTP", "CONFIGURE_RECOVERY_AUTHN_CODES", "UPDATE_PASSWORD"):
        page = Browser(env).login(who.user, kc_action=action)
        assert page.code is None and shown(page) in ("denied", "password"), (action, page.summary)
    assert kinds(admin, who.user) == ["password"] and obliged(admin, who.user)


def test_an_existing_passkey_user_proves_the_passkey_for_a_new_factor(
    env: Env, admin: Admin
) -> None:
    who = account(admin, PASSKEY)
    assert obliged(admin, who.user)
    browser = Browser(env)
    page = who.prove(browser, browser.login(who.user, kc_action="CONFIGURE_TOTP"), PASSKEY)
    assert shown(page) == "otp-setup", page.summary
    with registration_allowed(admin, PASSKEY):  # registration stays off: only for this check
        stale = account(admin)
        held = Browser(env)
        page = held.login(stale.user, kc_action="webauthn-register")
        stale.enrol(OTP)
        done = register(held, page, env.base_url, SoftwareKey())
        assert outcome(done) == "refused", done.summary


# --- the controlled switch-off ---------------------------------------------------------------
def start_switch_off(rig: Rig, who: Account) -> Page:
    started = rig.api.post(
        f"{API}/me/security/mfa-disable-requests",
        json={"confirm": "DISABLE_MFA", "return_to": "/me"},
        headers=secure(rig),
    )
    assert started.status_code == 200, started.text
    return follow(rig, started.json()["redirect_url"])


def test_a_person_switches_the_second_factor_off_with_the_factor_and_a_confirmation(
    rig: Rig, env: Env, admin: Admin
) -> None:
    who = account(admin, OTP, CODES)
    other = Browser(env)
    who.sign_in(other).require_code()
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    step_up(rig, who)
    page = start_switch_off(rig, who)
    page = password_then_factor(rig, who, page, OTP)
    assert 'id="at-disable-mfa-form"' in page.text, page.summary
    fields = {**hidden_inputs(page.text), "accept": ""}
    done = rig.browser.submit(page, fields, action=form_action(page.text))
    assert done.location and "kc_action_status=success" in done.location, done.summary
    finished = rig.api.get(done.location)
    assert finished.headers["location"] == "/me?security_action=success"
    assert kinds(admin, who.user) == ["password"] and not obliged(admin, who.user)
    assert rig.api.get(f"{AUTH_API}/session").status_code == 401
    assert shown(other.authorize("at-web", WEB_REDIRECT)) == "password"  # other session ended
    assert rig.rows("SELECT outcome FROM audit_events WHERE action = 'security.mfa.disabled'") == [
        ("SUCCESS",)
    ]
    page = Browser(env).login(who.user)
    assert outcome(page) == "code"  # the password alone now, as the person chose


def test_a_recovery_code_cannot_switch_the_second_factor_off(
    rig: Rig, env: Env, admin: Admin
) -> None:
    who = account(admin, OTP, CODES)
    assert rig.sign_in(who.user, prove=who.answer).status_code == 302
    step_up(rig, who)
    page = password_then_factor(rig, who, start_switch_off(rig, who), CODES)
    assert outcome(page) == "refused", page.summary
    assert kinds(admin, who.user) == ["otp", "password", "recovery-authn-codes"]
    assert obliged(admin, who.user)


@pytest.mark.parametrize("case", ["no_confirmation", "mandatory", "password_only"])
def test_the_switch_off_is_refused_at_the_provider_itself(
    env: Env, admin: Admin, case: str
) -> None:
    """Even when somebody calls Keycloak directly, past the application."""
    who = account(admin, OTP)
    if case == "mandatory":
        path = f"/users/{who.user.id}"
        person = admin.master("GET", path).json()
        person["attributes"]["at_mfa_mandatory"] = ["true"]
        admin.master("PUT", path, json=person).raise_for_status()
    browser = Browser(env)
    page = browser.login(who.user, kc_action="at-disable-mfa")
    if case == "password_only":
        assert page.code is None and shown(page) == OTP  # the realm asks for the factor first
    else:
        page = who.prove(browser, page, OTP)
        if case == "mandatory":
            assert outcome(page) == "refused", page.summary
        else:
            fields = {k: v for k, v in hidden_inputs(page.text).items() if k != "confirm"}
            page = browser.submit(page, {**fields, "accept": ""}, action=form_action(page.text))
            assert 'id="at-disable-mfa-form"' in page.text  # asked again, nothing removed
    assert kinds(admin, who.user) == ["otp", "password"] and obliged(admin, who.user)


# --- logs and events carry no secret -----------------------------------------------------------
def test_a_refusal_event_names_the_action_and_reason_only(env: Env, admin: Admin) -> None:
    who = account(admin)
    intruder = Browser(env)
    held = open_totp_form(intruder, who.user)
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', held.text)
    assert secret
    who.enrol(OTP)
    submit_totp(intruder, held, "intruder")
    [event] = refusals(admin, who.user)
    assert set(event["details"]) <= {
        "custom_required_action", "reason", "auth_method", "response_type", "redirect_uri",
        "remember_me", "code_id", "response_mode", "username",
    }  # fmt: skip
    text = repr(event)
    assert secret.group(1).strip().replace(" ", "") not in text.replace(" ", "")
    assert who.user.password not in text and "intruder" not in text


# --- concurrency on one instance ---------------------------------------------------------------
def test_two_first_activations_at_once_leave_exactly_one_factor(env: Env, admin: Admin) -> None:
    for _ in range(3):
        who = account(admin)
        forms = [(b, open_totp_form(b, who.user)) for b in (Browser(env), Browser(env))]
        results = together(
            *[
                lambda b=b, p=p, i=i: submit_totp(b, p, f"device{i}")
                for i, (b, p) in enumerate(forms)
            ]
        )
        assert sorted(outcome(r) == "code" for r in results) == [False, True], [
            outcome(r) for r in results
        ]
        assert kinds(admin, who.user) == ["otp", "password"] and obliged(admin, who.user)


# --- two instances on one database -----------------------------------------------------------
@pytest.fixture(scope="module")
def nodes(env: Env) -> Iterator[list[tuple[Env, Admin]]]:
    urls = os.environ.get("TEST_KEYCLOAK_NODE_URLS", "").split()
    if len(urls) != 2:
        if os.environ.get("CI"):
            pytest.fail("TEST_KEYCLOAK_NODE_URLS must name two nodes in CI")
        pytest.skip("TEST_KEYCLOAK_NODE_URLS not set")
    pairs = []
    for url in urls:
        node = Env(url, env.admin_user, env.admin_password, env.web_secret, env.svc_secret)
        pairs.append((node, Admin(node)))
    windows = []
    for _, node_admin in pairs:  # each node writes it, so neither cache keeps the old value
        windows.append(node_admin.realm()["otpPolicyLookAheadWindow"])
        node_admin.update_realm(otpPolicyLookAheadWindow=30)
    yield pairs
    for (_, node_admin), window in zip(pairs, windows, strict=True):
        node_admin.update_realm(otpPolicyLookAheadWindow=window)
        node_admin.close()


def test_a_form_held_on_one_node_is_refused_after_the_factor_was_set_up_on_the_other(
    nodes: list[tuple[Env, Admin]],
) -> None:
    (first, first_admin), (_, second_admin) = nodes
    user = first_admin.create_user()
    intruder = Browser(first)
    held = open_totp_form(intruder, user)
    Account(second_admin, user).enrol(OTP)  # the person, on the other node
    done = submit_totp(intruder, held, "intruder")
    assert outcome(done) == "refused", done.summary
    assert kinds(first_admin, user) == ["otp", "password"]


@pytest.mark.parametrize("guard_row", [False, True], ids=["first_change", "lock_wait"])
def test_first_activations_on_two_nodes_at_once_leave_exactly_one_factor(
    nodes: list[tuple[Env, Admin]], guard_row: bool
) -> None:
    """Without a guard row the two inserts collide on its key and the loser rolls back; with one
    the loser waits for the lock, reads the new factor and is refused."""
    (first, first_admin), (second, second_admin) = nodes
    for _ in range(3):
        user = first_admin.create_user()
        if guard_row:  # an earlier guarded change created the person's row
            browser = Browser(second)
            page = browser.login(user, kc_action="UPDATE_PASSWORD")
            done = browser.submit(
                page, {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
            )
            assert outcome(done) == "code", done.summary
            user = TestUser(id=user.id, email=user.email, password=NEW_PASSWORD)
        forms = [(b, open_totp_form(b, user)) for b in (Browser(first), Browser(second))]
        results = together(
            *[lambda b=b, p=p, i=i: submit_totp(b, p, f"node{i}") for i, (b, p) in enumerate(forms)]
        )
        outcomes = [outcome(r) for r in results]
        assert sorted(o == "code" for o in outcomes) == [False, True], outcomes
        if guard_row:
            assert "refused" in outcomes
        assert kinds(first_admin, user) == ["otp", "password"]
        assert obliged(second_admin, user)


def test_new_recovery_codes_on_two_nodes_at_once_leave_one_set(
    nodes: list[tuple[Env, Admin]],
) -> None:
    (first, first_admin), (second, second_admin) = nodes
    who = account(first_admin, OTP, CODES)
    pages = []
    for node in (first, second):
        browser = Browser(node)
        page = browser.login(who.user, kc_action="CONFIGURE_RECOVERY_AUTHN_CODES")
        page = who.answer(browser, page, OTP)
        assert shown(page) == "codes-setup", page.summary
        pages.append((browser, page))
    results = together(*[lambda b=b, p=p: submit_codes(b, p) for b, p in pages])
    assert all(outcome(r) == "code" for r in results)  # one after the other, both proven
    assert kinds(second_admin, who.user) == ["otp", "password", "recovery-authn-codes"]


def test_a_password_form_and_a_first_activation_on_two_nodes_end_in_a_serial_state(
    nodes: list[tuple[Env, Admin]],
) -> None:
    """Either order is a valid history of a password-only account becoming protected; a password
    changed after the factor without it is not."""
    (first, first_admin), (second, _) = nodes
    new = {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD}
    for _ in range(3):
        user = first_admin.create_user()
        password_browser = Browser(first)
        password_page = password_browser.login(user, kc_action="UPDATE_PASSWORD")
        owner = Browser(second)
        form = open_totp_form(owner, user)

        def change(b: Browser = password_browser, p: Page = password_page) -> Page:
            return b.submit(p, new)

        def enrol(b: Browser = owner, p: Page = form) -> Page:
            return submit_totp(b, p, "owner")

        changed, enrolled = together(change, enrol)
        assert outcome(enrolled) == "code" or outcome(changed) == "code"
        found = kinds(first_admin, user)
        assert found in (["otp", "password"], ["password"])
        if outcome(changed) == "code" and found == ["otp", "password"]:
            # both went through: the password must have gone first, while nothing protected it
            events = first_admin.master("GET", "/events", params={"user": user.id}).json()
            assert not any(e.get("error") == "credential_change_refused" for e in events)


# --- reconciling the accounts of an existing realm ---------------------------------------------
def test_existing_accounts_are_reconciled_without_deleting_anything(env: Env, admin: Admin) -> None:
    from scripts.identity import reconcile_mfa_obligation as reconcile

    def unmark(who: Account) -> None:
        path = f"/users/{who.user.id}"
        person = admin.master("GET", path).json()
        person["attributes"].pop("at_mfa_required", None)
        admin.master("PUT", path, json=person).raise_for_status()

    permanent = account(admin, OTP)
    unmark(permanent)  # as before the provider
    passkey = account(admin, PASSKEY)
    unmark(passkey)
    codes = codes_only_account(admin, marked=False)
    locked = account(admin, OTP)
    locked.remove_as_administrator(OTP)
    never = account(admin)
    pending = account(admin)
    path = f"/users/{pending.user.id}"
    person = admin.master("GET", path).json()
    admin.master(
        "PUT", path, json={**person, "requiredActions": ["CONFIGURE_TOTP", "VERIFY_EMAIL"]}
    ).raise_for_status()
    people = [permanent, passkey, codes, locked, never, pending]
    before = {who.user.id: kinds(admin, who.user) for who in people}
    only = frozenset(before)
    with reconcile.admin_client(env.base_url, env.admin_user, env.admin_password) as client:
        dry = reconcile.reconcile(client, REALM, apply=False, only=only)
        assert not obliged(admin, permanent.user) and not obliged(admin, codes.user)  # read only
        applied = reconcile.reconcile(client, REALM, apply=True, only=only)
        again = reconcile.reconcile(client, REALM, apply=True, only=only)
    expected = {"permanent": 2, "codes_only": 1, "locked": 1, "never": 2, "pending": 1}
    assert dict(dry.counts) == dict(applied.counts) == expected
    assert again.changed == []  # idempotent
    for who in (permanent, passkey, codes, locked):
        assert obliged(admin, who.user)
    assert not obliged(admin, never.user) and not obliged(admin, pending.user)
    assert pending.required_actions() == ["VERIFY_EMAIL"]
    assert {who.user.id: kinds(admin, who.user) for who in people} == before  # nothing deleted
    assert sorted(applied.review) == sorted([locked.user.id, never.user.id, pending.user.id])
