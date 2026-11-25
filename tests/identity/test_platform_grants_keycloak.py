"""F2-T10 against the real Keycloak 26.8.2 with the AutoTramita security provider (identity CI
job): AC-PLT-11 (bootstrap), AC-POL-09 (grant holders must keep a second factor), AC-POL-10 (the
five-minute window from the real level-two proof) and the T10 part of D22/D44: a grant takes
effect only for a person with a one-time code or passkey, after the provider marked the account
``at_mfa_mandatory``; from then on the provider itself refuses the switch-off."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.db import create_session_factory
from app.core.pagination import CursorCodec
from app.platform.bootstrap import BootstrapRefused, bootstrap_platform_admin
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import RoleEnv
from tests.identity.accounts import OTP, Account, account, codes_only_account
from tests.identity.kc import Admin, Browser, Env
from tests.identity.rig import Rig
from tests.identity.test_security_keycloak import secure, settings_admin
from tests.identity.test_security_provider_keycloak import attributes, kinds, obliged, outcome

pytestmark = pytest.mark.keycloak

API = "/api/v1"
GRANTS = f"{API}/platform/grants"


def platform_on(rig: Rig, role_env: RoleEnv) -> None:
    rig.runtime.platform_factory = create_session_factory(role_env.engine("platform"))
    rig.runtime.cursor_codec = CursorCodec(b"c" * 32)


def step_up(rig: Rig, client: TestClient, browser: Browser, who: Account) -> None:
    """The MFA step-up a platform user performs: password and factor again at Keycloak."""
    asked = client.post(
        f"{API}/auth/step-up",
        json={"purpose": "MFA", "return_to": "/admin"},
        headers=secure(rig, client),
    )
    assert asked.status_code == 200, asked.text
    callback = rig.at_keycloak(asked.json()["redirect_url"], who.user, browser, prove=who.answer)
    assert client.get(callback).status_code == 302


def signed_in(
    rig: Rig, env: Env, who: Account, *, level_two: bool = True
) -> tuple[TestClient, Browser]:
    """The person's own application session, from a fresh Keycloak sign-in in their own browser,
    stepped up to level two unless told otherwise."""
    client, browser = rig.another_client(), Browser(env)
    done = rig.sign_in(who.user, client=client, browser=browser, prove=who.answer)
    assert done.status_code == 302, done.text
    if level_two:
        step_up(rig, client, browser, who)
    return client, browser


def bootstrap(rig: Rig, role_env: RoleEnv, who: Account) -> None:
    bootstrap_platform_admin(
        create_session_factory(role_env.engine("owner")),
        rig.runtime.admin,
        email=who.user.email,
        environment="test",
        now=datetime.now(UTC),
    )


def request(rig: Rig, client: TestClient, user_id: Any, grant_type: str) -> httpx.Response:
    response: httpx.Response = client.post(
        GRANTS,
        json={
            "user_id": str(user_id),
            "grant_type": grant_type,
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "reason": "needed for the support rota",
        },
        headers=secure(rig, client),
    )
    return response


def app_user(role_env: RoleEnv, subject: str) -> uuid.UUID:
    with role_env.admin_engine().connect() as c:
        return uuid.UUID(
            str(
                c.execute(
                    text("SELECT id FROM users WHERE auth_subject = :s"), {"s": subject}
                ).scalar_one()
            )
        )


def test_the_admin_client_marks_the_factor_mandatory_and_keeps_everything_else(
    rig: Rig, admin: Admin
) -> None:
    who = account(admin, OTP)
    path = f"/users/{who.user.id}"
    before = admin.master("GET", path).json()
    client = settings_admin(rig)
    assert not client.is_factor_mandatory(who.user.id) and client.has_factor_obligation(who.user.id)
    client.set_factor_mandatory(who.user.id)
    client.set_factor_mandatory(who.user.id)  # once more: nothing else happens
    after = admin.master("GET", path).json()
    assert after["attributes"]["at_mfa_mandatory"] == ["true"]
    assert after["attributes"]["at_mfa_required"] == ["true"]
    for field in ("email", "username", "enabled", "emailVerified", "requiredActions", "firstName"):
        assert after[field] == before[field], field
    assert {k: v for k, v in after["attributes"].items() if k != "at_mfa_mandatory"} == before[
        "attributes"
    ]
    assert who.kinds() == [OTP] and client.is_factor_mandatory(who.user.id)


def test_a_grant_takes_effect_only_for_a_permanent_factor_and_the_provider_then_keeps_it(
    rig: Rig, env: Env, admin: Admin, role_env: RoleEnv
) -> None:
    platform_on(rig, role_env)
    a, b, c = account(admin, OTP), account(admin, OTP), account(admin, OTP)
    (as_a, _), (as_b, _) = signed_in(rig, env, a), signed_in(rig, env, b)
    signed_in(rig, env, c, level_two=False)  # c signs in once: the application knows it
    for who in (a, b):
        bootstrap(rig, role_env, who)
        assert attributes(admin, who.user)["at_mfa_mandatory"] == ["true"]
    # a password-only person and an account holding recovery codes only (from before)
    password_only = admin.create_user()
    first = rig.sign_in(password_only, client=rig.another_client(), browser=Browser(env))
    assert first.status_code == 302, first.text
    codes = codes_only_account(admin, marked=True)  # refused at sign-in: the row is made here
    with role_env.admin_engine().connect() as db:
        db.execute(
            text("INSERT INTO users (auth_subject, email, email_normalized, status, email_verified_at) "
                 "VALUES (:s, :e, :e, 'ACTIVE', now())"), {"s": codes.user.id, "e": codes.user.email})  # fmt: skip
    for user in (password_only, codes.user):
        pending = request(rig, as_a, app_user(role_env, user.id), "PLATFORM_USER_ADMIN")
        assert pending.status_code == 201 and pending.json()["status"] == "PENDING_APPROVAL", (
            pending.text
        )
        refused = as_b.post(f"{GRANTS}/{pending.json()['id']}/approve", headers=secure(rig, as_b))
        assert refused.status_code == 409 and refused.json()["code"] == "NO_SECOND_FACTOR", (
            refused.text
        )
        assert "at_mfa_mandatory" not in attributes(admin, user)
        with pytest.raises(BootstrapRefused, match="one-time code or passkey"):
            bootstrap_platform_admin(
                create_session_factory(role_env.engine("owner")), rig.runtime.admin,
                email=user.email, environment="test", now=datetime.now(UTC),
            )  # fmt: skip
    assert kinds(admin, codes.user) == ["password", "recovery-authn-codes"]  # nothing removed
    granted = request(rig, as_a, app_user(role_env, c.user.id), "PLATFORM_USER_ADMIN")
    approved = as_b.post(f"{GRANTS}/{granted.json()['id']}/approve", headers=secure(rig, as_b))
    assert approved.status_code == 200 and approved.json()["status"] == "ACTIVE", approved.text
    assert attributes(admin, c.user)["at_mfa_mandatory"] == ["true"] and obliged(admin, c.user)
    # the provider itself refuses the switch-off, even when asked directly past the application
    browser = Browser(env)
    page = c.prove(browser, browser.login(c.user, kc_action="at-disable-mfa"), OTP)
    assert outcome(page) == "refused", page.summary
    assert kinds(admin, c.user) == ["otp", "password"] and obliged(admin, c.user)
    # and the application does not start it
    as_c, _ = signed_in(rig, env, c)
    asked = as_c.post(
        f"{API}/me/security/mfa-disable-requests",
        json={"confirm": "DISABLE_MFA", "return_to": "/me"},
        headers=secure(rig, as_c),
    )
    assert asked.status_code == 403 and asked.json()["code"] == "SECOND_FACTOR_MANDATORY", (
        asked.text
    )


def test_grant_changes_count_five_minutes_from_the_real_proof_of_the_factor(
    rig: Rig, env: Env, admin: Admin, role_env: RoleEnv
) -> None:
    platform_on(rig, role_env)
    a, b = account(admin, OTP), account(admin, OTP)
    as_a, browser_a = signed_in(rig, env, a)
    signed_in(rig, env, b, level_two=False)
    for who in (a, b):
        bootstrap(rig, role_env, who)
    assert as_a.get(GRANTS).status_code == 200  # level two from the step-up with the code
    with role_env.admin_engine().connect() as db:  # the proof lies six minutes back now
        db.execute(
            text("UPDATE user_sessions SET step_up_at = step_up_at - interval '6 minutes' "
                 "WHERE user_id = :u AND revoked_at IS NULL"), {"u": app_user(role_env, a.user.id)})  # fmt: skip
    refused = as_a.get(GRANTS)
    assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED", refused.text
    assert 'acr_values="loa2"' in refused.headers["www-authenticate"]
    assert as_a.get(f"{API}/platform/grant-types").status_code == 200  # ten minutes for reading
    step_up(rig, as_a, browser_a, a)
    assert as_a.get(GRANTS).status_code == 200  # a fresh proof opens it again


def test_a_sign_in_without_the_step_up_does_not_open_the_platform(
    rig: Rig, env: Env, admin: Admin, role_env: RoleEnv
) -> None:
    """Even a grant holder who entered the one-time code at sign-in acts at level two only after
    the explicit step-up (the platform routes never take the sign-in level for granted)."""
    platform_on(rig, role_env)
    a = account(admin, OTP)
    as_a, _ = signed_in(rig, env, a, level_two=False)
    bootstrap(rig, role_env, a)
    refused = as_a.get(f"{API}/platform/grant-types")
    assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED", refused.text
