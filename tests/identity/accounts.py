"""Accounts with second factors for the Keycloak tests: enrolment and proof of one-time codes,
recovery codes and passkeys through Keycloak's own pages. Test-only."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from tests.identity.kc import (
    WEB_REDIRECT,
    Admin,
    Browser,
    Page,
    TestUser,
    form_action,
    hidden_inputs,
    totp,
)
from tests.identity.webauthn import SoftwareKey, authenticate, register

OTP, CODES, PASSKEY, PASSWORDLESS = (
    "otp",
    "recovery-authn-codes",
    "webauthn",
    "webauthn-passwordless",
)
REGISTRATION = {PASSKEY: "webauthn-register", PASSWORDLESS: "webauthn-register-passwordless"}


def shown(page: Page) -> str:
    """Which question or form Keycloak shows."""
    if page.location:
        return "code" if page.code else "redirect"
    for marker, name in (
        ('id="kc-totp-secret-key"', "otp-setup"),
        ("mode=manual", "otp-setup"),
        ('name="generatedRecoveryAuthnCodes"', "codes-setup"),
        ('name="password-new"', "new-password"),
        ('name="otp"', OTP),
        ('name="recoveryCodeInput"', CODES),
        ('id="webauth"', PASSKEY),
        ('name="authenticationExecution"', "select"),
        ('name="password"', "password"),
    ):
        if marker in page.text:
            return name
    return "other"


@contextmanager
def registration_allowed(admin: Admin, kind: str) -> Iterator[None]:
    """Passkey registration is off in every realm (F-1 b); a test enrols one by switching it on
    for a moment, as an account that already exists in a real realm would have done."""
    path = f"/authentication/required-actions/{REGISTRATION[kind]}"
    committed = admin.master("GET", path).json()
    assert committed["enabled"] is False
    admin.master("PUT", path, json={**committed, "enabled": True}).raise_for_status()
    try:
        yield
    finally:
        admin.master("PUT", path, json=committed).raise_for_status()


@dataclass
class OtpDevice:
    secret: str
    used: int = 0  # the last time step whose code was used

    def code(self) -> str:
        """A code Keycloak has not accepted yet (codes are single use)."""
        while True:
            step = max(int(time.time() // 30), self.used + 1)
            if step <= int(time.time() // 30) + 1:
                self.used = step
                return totp(self.secret, at=step * 30)
            time.sleep(1)


@dataclass
class Account:
    admin: Admin
    user: TestUser
    otp: OtpDevice | None = None
    codes: list[str] = field(default_factory=list)
    keys: dict[str, SoftwareKey] = field(default_factory=dict)

    def credentials(self) -> list[str]:
        found = self.admin.master("GET", f"/users/{self.user.id}/credentials").json()
        return sorted(c["type"] for c in found)

    def credential_id(self, kind: str) -> str:
        found = self.admin.master("GET", f"/users/{self.user.id}/credentials").json()
        return str(next(c["id"] for c in found if c["type"] == kind))

    def kinds(self) -> list[str]:
        return [k for k in self.credentials() if k != "password"]

    def required_actions(self) -> list[str]:
        found: list[str] = self.admin.master("GET", f"/users/{self.user.id}").json()[
            "requiredActions"
        ]
        return found

    def select(self, browser: Browser, page: Page, kind: str) -> Page:
        """Choose the method ``kind`` ("try another way") unless it is already asked."""
        if shown(page) == kind:
            return page
        if shown(page) != "select":
            fields = {**hidden_inputs(page.text), "tryAnotherWay": "on"}
            page = browser.submit(page, fields, action=form_action(page.text))
        assert shown(page) == "select", page.summary
        selection = page
        options = re.findall(r'name="authenticationExecution"\s+value="([^"]+)"', selection.text)
        for option in options:
            asked = browser.submit(selection, {"authenticationExecution": option})
            if shown(asked) == kind:
                return asked
            back = {**hidden_inputs(asked.text), "tryAnotherWay": "on"}
            selection = browser.submit(asked, back, action=form_action(asked.text))
        raise AssertionError(f"{kind} is not offered: {selection.summary}")

    def offered(self, browser: Browser, page: Page) -> set[str]:
        """Every method Keycloak offers for this question (none besides the asked one when
        there is no "try another way")."""
        if shown(page) != "select":
            if "tryAnotherWay" not in page.text:
                return {shown(page)}
            fields = {**hidden_inputs(page.text), "tryAnotherWay": "on"}
            page = browser.submit(page, fields, action=form_action(page.text))
        assert shown(page) == "select", page.summary
        found = set()
        for option in re.findall(r'name="authenticationExecution"\s+value="([^"]+)"', page.text):
            asked = browser.submit(page, {"authenticationExecution": option})
            found.add(shown(asked))
            back = {**hidden_inputs(asked.text), "tryAnotherWay": "on"}
            page = browser.submit(asked, back, action=form_action(asked.text))
        return found

    def answer_code(self, browser: Browser, page: Page, code: str) -> Page:
        fields = hidden_inputs(page.text)
        fields.pop("tryAnotherWay", None)
        fields["recoveryCodeInput"] = code
        return browser.submit(page, fields, action=form_action(page.text))

    def next_code(self, page: Page) -> str:
        """The recovery code Keycloak asks for by number."""
        asked = re.search(r"#\s*(\d+)", page.summary)
        assert asked, page.summary
        return self.codes[int(asked.group(1)) - 1]

    def prove(self, browser: Browser, page: Page, kind: str | None = None) -> Page:
        """Answer the second-factor question with ``kind`` (default: whatever is asked)."""
        if kind is None:
            kind = shown(page)
        wanted = PASSKEY if kind == PASSWORDLESS else kind
        page = self.select(browser, page, wanted)
        if wanted == OTP:
            assert self.otp is not None
            fields = hidden_inputs(page.text)
            fields.pop("tryAnotherWay", None)
            fields["otp"] = self.otp.code()
            return browser.submit(page, fields, action=form_action(page.text))
        if wanted == CODES:
            return self.answer_code(browser, page, self.next_code(page))
        key = self.keys.get(kind) or next(iter(self.keys.values()))
        return authenticate(browser, page, browser.env.base_url, key)

    def level_two(self, kind: str | None = None) -> Browser:
        """A browser signed in at level two."""
        browser = Browser(self.admin.env)
        page = browser.login(self.user, acr_values="loa2")
        self.prove(browser, page, kind).require_code()
        return browser

    # --- enrolment (each time through a session that proved what the account already has) ------
    def action(self, name: str) -> tuple[Browser, Page]:
        browser = Browser(self.admin.env)
        browser.login(self.user).require_code()
        page = browser.authorize("at-web", WEB_REDIRECT, kc_action=name)
        if self.kinds():
            assert shown(page) in (OTP, CODES, PASSKEY), page.summary
            page = self.prove(browser, page)
        return browser, page

    def enrol(self, kind: str) -> Account:
        if kind == OTP:
            browser, page = self.action("CONFIGURE_TOTP")
            self.otp, done = set_up_otp(browser, page)
        elif kind == CODES:
            browser, page = self.action("CONFIGURE_RECOVERY_AUTHN_CODES")
            self.codes, done = set_up_codes(browser, page)
        else:
            with registration_allowed(self.admin, kind):
                browser, page = self.action(REGISTRATION[kind])
                self.keys[kind] = SoftwareKey()
                done = register(browser, page, self.admin.env.base_url, self.keys[kind])
        assert done.location and "kc_action_status=success" in done.location, done.summary
        assert kind in self.credentials()
        return self


def set_up_otp(browser: Browser, page: Page) -> tuple[OtpDevice, Page]:
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    if not secret:
        manual = re.search(r'href="([^"]*mode=manual[^"]*)"', page.text)
        assert manual, page.summary
        page = browser.get(manual.group(1).replace("&amp;", "&"))
        secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    assert secret, page.summary
    device = OtpDevice(secret.group(1).strip())
    fields = {**hidden_inputs(page.text), "totp": device.code(), "userLabel": "test"}
    return device, browser.submit(page, fields, action=form_action(page.text))


def set_up_codes(browser: Browser, page: Page) -> tuple[list[str], Page]:
    codes = re.search(r'name="generatedRecoveryAuthnCodes" value="([^"]+)"', page.text)
    assert codes, page.summary
    fields = hidden_inputs(page.text)
    for checkbox in re.findall(r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"', page.text):
        fields[checkbox] = "on"
    done = browser.submit(page, fields, action=form_action(page.text))
    return codes.group(1).split(","), done


def account(admin: Admin, *factors: str) -> Account:
    created = Account(admin, admin.create_user())
    for kind in factors:
        created.enrol(kind)
    return created
