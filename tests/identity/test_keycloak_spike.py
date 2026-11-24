"""F2-T01 spike S1-S10: each test proves (or refutes) one assumption of the F2 design against
a real Keycloak 26.4.7 container. Run only in the ``keycloak`` CI job (disposable container).
A failing test means a design assumption does not hold: STOP and report at CP01."""

import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from tests.identity.kc import (
    MOBILE_REDIRECT,
    REALM,
    WEB_REDIRECT,
    Admin,
    BackchannelSink,
    Browser,
    Env,
    SmtpSink,
    decode_jwt,
    form_action,
    hidden_inputs,
    pkce_pair,
    record_result,
    totp,
)

pytestmark = pytest.mark.keycloak

BAD = "Wrong-password-0000"
INVALID = re.compile(r"Invalid username or password", re.I)


def _error_text(page_text: str) -> str:
    """Normalised user-visible feedback of a failed login page."""
    found = re.findall(
        r"(Invalid username or password\.?|Account is[^<]{0,80}|temporarily[^<]{0,80})",
        page_text,
        re.I,
    )
    return found[0].strip().rstrip(".").lower() if found else page_text[:120]


def _tokens_for(
    env: Env, user_email: str, password: str, *, client: str = "at-web"
) -> dict[str, object]:
    b = Browser(env)
    try:
        verifier, challenge = pkce_pair()
        redirect = WEB_REDIRECT if client == "at-web" else MOBILE_REDIRECT
        page = b.login(
            user_email, password, client_id=client, redirect_uri=redirect, challenge=challenge
        )
        page.require_code()
        return {"browser": b, **b.token(client, page.require_code(), redirect, verifier=verifier)}
    except BaseException:
        b.close()
        raise


# --- S7: realm import with ${ENV} secrets, least-privilege service account --------------------
def test_s07_realm_import_resolves_env_secrets_and_service_account_is_least_privilege(
    env: Env, admin: Admin
) -> None:
    r = httpx.post(
        f"{env.base_url}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "at-admin-svc",
            "client_secret": env.svc_secret,
        },
    )
    assert r.status_code == 200
    wrong = httpx.post(
        f"{env.base_url}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "at-admin-svc",
            "client_secret": "not-the-secret",
        },
    )
    assert wrong.status_code == 401
    assert admin.service("GET", "/users", params={"max": 1}).status_code == 200  # view-users
    assert admin.service("GET", "/events", params={"max": 1}).status_code == 200  # view-events
    # reading the realm is implied by any realm-management role; writing is not
    assert admin.service("PUT", "", json={"realm": REALM}).status_code == 403  # no manage-realm
    assert admin.service("POST", "/clients", json={"clientId": "x"}).status_code == 403
    b = Browser(env)
    no_pkce = b.authorize("at-web", WEB_REDIRECT, no_pkce=True)
    b.close()
    assert no_pkce.location and "error=invalid_request" in no_pkce.location, "PKCE not enforced"
    imported = admin.realm()
    assert imported["resetPasswordAllowed"] is False and imported["verifyEmail"] is True
    clients = {c["clientId"]: c for c in admin.master("GET", "/clients").json()}
    assert clients["at-mobile"]["publicClient"] is True
    assert clients["at-web"]["directAccessGrantsEnabled"] is False
    assert clients["at-web"]["attributes"]["pkce.code.challenge.method"] == "S256"


# --- S1: brute-force detection ---------------------------------------------------------------
def test_s01_brute_force_five_failures_lock_and_do_not_disclose(env: Env, admin: Admin) -> None:
    realm = admin.realm()
    assert (realm["failureFactor"], realm["maxDeltaTimeSeconds"], realm["permanentLockout"]) == (
        5,
        900,
        False,
    )
    # four failures in a row do not lock: the correct password still works
    careful = admin.create_user()
    for _ in range(4):
        b = Browser(env)
        assert INVALID.search(b.login(careful.email, BAD).text)
        b.close()
    b = Browser(env)
    careful_page = b.login(careful)
    careful_page.require_code()
    b.close()
    # five failures lock: the correct password is then refused with the same message
    locked = admin.create_user()
    messages = []
    for _ in range(5):
        b = Browser(env)
        messages.append(_error_text(b.login(locked.email, BAD).text))
        b.close()
    b = Browser(env)
    after = b.login(locked)
    b.close()
    assert after.code is None, "a locked account must not log in"
    message_after = _error_text(after.text)
    record_result("S1.message_wrong_password", messages[0])
    record_result("S1.message_when_locked", message_after)
    assert message_after == messages[0], "lockout must not be disclosed in the message"
    status = admin.master("GET", f"/attack-detection/brute-force/users/{locked.id}").json()
    assert status["disabled"] is True


# --- S2: password recovery cannot be limited per account natively ----------------------------
def test_s02_no_native_recovery_limit_and_closed_path_and_admin_email(
    env: Env, admin: Admin, smtp: SmtpSink
) -> None:
    user = admin.create_user()
    # (a) with resetPasswordAllowed=false the login page has no recovery link
    b = Browser(env)
    page = b.authorize("at-web", WEB_REDIRECT)
    assert "reset-credentials" not in page.text
    b.close()
    # (b) admin-initiated email works with the least-privilege service account, 30 min lifespan
    redirect = {"client_id": "at-web", "redirect_uri": WEB_REDIRECT, "lifespan": 1800}
    sent = admin.service(
        "PUT", f"/users/{user.id}/execute-actions-email", params=redirect, json=["UPDATE_PASSWORD"]
    )
    assert sent.status_code == 204, sent.text
    mails = smtp.for_recipient(user.email)
    assert mails, "no email received"
    link = re.search(r"https?://[^\s\"<>]+action-token[^\s\"<>]*", mails[0]["body"])
    assert link, mails[0]["body"][:300]
    key = parse_qs(urlparse(link.group(0).replace("&amp;", "&")).query)["key"][0]
    expires_in = decode_jwt(key)["exp"] - time.time()
    record_result("S2.admin_link_lifetime_seconds", round(expires_in))
    assert 1700 <= expires_in <= 1800
    # (c) with the user-facing flow enabled, five requests for one account send five emails:
    #     Keycloak has no native per-account limit (so D20 needs the application mechanism)
    victim = admin.create_user()
    admin.update_realm(resetPasswordAllowed=True)
    try:
        for _ in range(5):
            br = Browser(env)
            login_page = br.authorize("at-web", WEB_REDIRECT)
            href = re.search(r'href="([^"]*reset-credentials[^"]*)"', login_page.text)
            assert href, "recovery link missing while enabled"
            form = br.get(re.sub("&amp;", "&", href.group(1)))
            br.submit(form, {"username": victim.email})
            br.close()
        mails = [m for m in smtp.messages if victim.email in m["to"]]
        deadline = time.monotonic() + 10
        while len(mails) < 5 and time.monotonic() < deadline:
            time.sleep(0.3)
            mails = [m for m in smtp.messages if victim.email in m["to"]]
        record_result("S2.native_recovery_emails_for_5_requests", len(mails))
        assert len(mails) == 5, "Keycloak limited recovery emails natively; revisit D20"
    finally:
        admin.update_realm(resetPasswordAllowed=False)


# --- S3: step-up (LoA) and optional MFA -------------------------------------------------------
def test_s03_step_up_loa2_requires_otp_and_loa1_does_not(env: Env, admin: Admin) -> None:
    user = admin.create_user()
    b = Browser(env)
    verifier, challenge = pkce_pair()
    first = b.login(
        user, client_id="at-web", redirect_uri=WEB_REDIRECT, challenge=challenge, acr_values="loa1"
    )
    first.require_code()  # password-only login (dealership user without MFA) must succeed
    tokens = b.token("at-web", first.require_code(), WEB_REDIRECT, verifier=verifier)
    assert decode_jwt(tokens["id_token"]).get("acr") == "loa1", decode_jwt(tokens["id_token"])
    # step-up: same browser (SSO cookie), loa2 requested; user has no OTP yet -> setup prompt
    verifier2, challenge2 = pkce_pair()
    page = b.authorize("at-web", WEB_REDIRECT, challenge=challenge2, acr_values="loa2")
    assert page.code is None, "loa2 must not be satisfied by a password-only session"
    assert "totp" in page.text.lower() or "authenticator" in page.text.lower(), page.text[:300]
    secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    if not secret:  # the QR page offers a manual-entry link first
        manual = re.search(r'href="([^"]*mode=manual[^"]*)"', page.text)
        assert manual, page.text[:500]
        page = b.get(manual.group(1).replace("&amp;", "&"))
        secret = re.search(r'id="kc-totp-secret-key"[^>]*>([^<]+)<', page.text)
    assert secret, page.text[:500]
    fields = hidden_inputs(page.text)
    fields.update({"totp": totp(secret.group(1).strip()), "userLabel": "spike"})
    done = b.submit(page, fields, action=form_action(page.text))
    done.require_code()
    second = b.token("at-web", done.require_code(), WEB_REDIRECT, verifier=verifier2)
    assert decode_jwt(second["id_token"]).get("acr") == "loa2", decode_jwt(second["id_token"])
    b.close()
    record_result("S3.step_up", "loa1 password-only; loa2 prompts OTP setup then acr=2")


# --- S5: back-channel logout and sid --------------------------------------------------------
def test_s05_backchannel_logout_token_and_sid_claims(
    env: Env, admin: Admin, backchannel: BackchannelSink
) -> None:
    user = admin.create_user()
    issued = _tokens_for(env, user.email, user.password)
    browser = issued.pop("browser")
    assert isinstance(browser, Browser)
    try:
        access, ident = decode_jwt(str(issued["access_token"])), decode_jwt(str(issued["id_token"]))
        record_result("S5.access_token_claims", sorted(access))
        assert "sid" in ident
        assert "sid" in access, "access token must carry sid (or add a session-state mapper)"
        assert access["sid"] == ident["sid"]
        assert "at-api" in (access["aud"] if isinstance(access["aud"], list) else [access["aud"]])
        assert access["azp"] == "at-web" and access["typ"] == "Bearer"
        assert "tenant_id" not in access and "roles" not in access
        assert admin.service("POST", f"/users/{user.id}/logout").status_code == 204
        tokens = [t for t in backchannel.logout_tokens() if t.get("sid") == ident["sid"]]
        assert tokens, "no back-channel logout token received"
        token = tokens[0]
        assert "http://schemas.openid.net/event/backchannel-logout" in token["events"]
        assert token["jti"] and "nonce" not in token
        assert token["iss"] == ident["iss"] and token["aud"] in ("at-web", ["at-web"])
    finally:
        browser.close()


# --- S6: refresh rotation and reuse detection on the public client --------------------------
def test_s06_refresh_rotation_and_reuse_detection(env: Env, admin: Admin) -> None:
    user = admin.create_user()
    issued = _tokens_for(env, user.email, user.password, client="at-mobile")
    browser = issued.pop("browser")
    assert isinstance(browser, Browser)
    try:
        first = str(issued["refresh_token"])
        rotated = browser.refresh("at-mobile", first)
        assert rotated["_status"] == 200 and rotated["refresh_token"] != first
        reuse = browser.refresh("at-mobile", first)
        assert reuse["_status"] == 400 and reuse.get("error") == "invalid_grant"
        after = browser.refresh("at-mobile", str(rotated["refresh_token"]))
        record_result("S6.newest_token_after_reuse_status", after["_status"])
        assert after["_status"] == 400, "reuse must invalidate the whole token family/session"
    finally:
        browser.close()


# --- S8: events and admin events ------------------------------------------------------------
def test_s08_events_have_ip_and_no_secrets_and_admin_events_have_no_representation(
    env: Env, admin: Admin
) -> None:
    user = admin.create_user()
    b = Browser(env)
    b.login(user.email, BAD)
    b.close()
    events = admin.service("GET", "/events", params={"type": "LOGIN_ERROR", "user": user.id}).json()
    if not events:  # unknown user id is not recorded for some errors; fall back to all errors
        events = admin.service("GET", "/events", params={"type": "LOGIN_ERROR", "max": 20}).json()
    assert events, "no LOGIN_ERROR event stored"
    event = events[0]
    record_result("S8.event_keys", sorted(event))
    assert event.get("ipAddress")
    blob = str(event).lower()
    assert BAD.lower() not in blob and "password" not in " ".join(event.get("details", {}))
    admin.update_realm(displayName="AutoTramita")  # produces an admin event
    time.sleep(1)
    admin_events = admin.service("GET", "/admin-events", params={"max": 10}).json()
    assert admin_events, "no admin event stored"
    assert all(not e.get("representation") for e in admin_events)
    paged = admin.service("GET", "/events", params={"first": 0, "max": 1}).json()
    assert len(paged) <= 1


# --- S9: application-initiated actions ------------------------------------------------------
def test_s09_kc_action_update_password_and_configure_totp(env: Env, admin: Admin) -> None:
    user = admin.create_user()
    b = Browser(env)
    b.login(user).require_code()
    page = b.authorize("at-web", WEB_REDIRECT, kc_action="UPDATE_PASSWORD")
    assert page.code is None and "password-new" in page.text, page.text[:300]
    new_password = "Another-correct-horse-9"
    done = b.submit(page, {"password-new": new_password, "password-confirm": new_password})
    status = done.query.get("kc_action_status", [None])[0]
    record_result("S9.update_password_status", status)
    assert status == "success", done.location or done.text[:300]
    totp_page = b.authorize("at-web", WEB_REDIRECT, kc_action="CONFIGURE_TOTP")
    assert totp_page.code is None and "totp" in totp_page.text.lower()
    # UPDATE_EMAIL and recovery codes are reported, not asserted (feature availability, S4)
    actions = {
        a["alias"]: a["enabled"]
        for a in admin.master("GET", "/authentication/required-actions").json()
    }
    record_result("S9.required_actions", actions)
    record_result(
        "S4.recovery_codes_action_present", any("RECOVERY" in alias.upper() for alias in actions)
    )
    record_result("S9.update_email_enabled", actions.get("UPDATE_EMAIL"))
    email_page = b.authorize("at-web", WEB_REDIRECT, kc_action="UPDATE_EMAIL")
    record_result(
        "S9.update_email_prompted", "email" in email_page.text.lower() and email_page.code is None
    )
    b.close()


# --- S4: recovery codes availability (informational) ----------------------------------------
def test_s04_recovery_codes_availability_is_reported(admin: Admin) -> None:
    info = admin.master("GET", "/authentication/authenticator-providers").json()
    ids = [p.get("id", "") for p in info]
    present = [i for i in ids if "recovery" in i]
    record_result("S4.authenticator_providers_with_recovery", present)
    assert isinstance(info, list) and info


# --- S10: password policy -------------------------------------------------------------------
def test_s10_password_policy_enforced_including_blacklist(admin: Admin) -> None:
    server = httpx.get(  # server info needs a master token
        f"{admin.env.base_url}/admin/serverinfo",
        headers={"Authorization": f"Bearer {admin._master_token()}"},
    ).json()
    policies = {p["id"] for p in server.get("passwordPolicies", [])}
    record_result("S10.policies_available", sorted(policies))
    assert {"length", "notUsername", "notEmail", "passwordBlacklist"} <= policies
    user = admin.create_user()
    for rejected in ("Short-1aA", "password1234"):
        r = admin.master(
            "PUT",
            f"/users/{user.id}/reset-password",
            json={"type": "password", "value": rejected, "temporary": False},
        )
        assert r.status_code == 400, (rejected, r.status_code)
    ok = admin.master(
        "PUT",
        f"/users/{user.id}/reset-password",
        json={"type": "password", "value": "Fine-long-passphrase-42", "temporary": False},
    )
    assert ok.status_code == 204


# --- AC-KC-05: signing key rotation ---------------------------------------------------------
def test_kc05_key_rotation_new_key_published_and_old_kept(env: Env, admin: Admin) -> None:
    jwks_url = f"{env.base_url}/realms/{REALM}/protocol/openid-connect/certs"
    before = {k["kid"] for k in httpx.get(jwks_url).json()["keys"] if k.get("use") == "sig"}
    user = admin.create_user()
    old = _tokens_for(env, user.email, user.password)
    old_browser = old.pop("browser")
    assert isinstance(old_browser, Browser)
    old_browser.close()
    old_kid = decode_header_kid(str(old["access_token"]))
    assert old_kid in before
    created = admin.master(
        "POST",
        "/components",
        json={
            "name": "rsa-rotated",
            "providerId": "rsa-generated",
            "providerType": "org.keycloak.keys.KeyProvider",
            "config": {
                "priority": ["200"],
                "enabled": ["true"],
                "active": ["true"],
                "keySize": ["2048"],
            },
        },
    )
    assert created.status_code == 201, created.text
    component = created.headers["Location"].rsplit("/", 1)[1]
    try:
        user2 = admin.create_user()
        new = _tokens_for(env, user2.email, user2.password)
        new_browser = new.pop("browser")
        assert isinstance(new_browser, Browser)
        new_browser.close()
        new_kid = decode_header_kid(str(new["access_token"]))
        after = {k["kid"] for k in httpx.get(jwks_url).json()["keys"] if k.get("use") == "sig"}
        assert new_kid != old_kid, "new tokens must use the higher-priority key"
        assert {old_kid, new_kid} <= after, "the old key must stay published until removed"
    finally:
        admin.master("DELETE", f"/components/{component}")


def decode_header_kid(token: str) -> str:
    import base64
    import json

    header = token.split(".")[0]
    header += "=" * (-len(header) % 4)
    kid: str = json.loads(base64.urlsafe_b64decode(header))["kid"]
    return kid
