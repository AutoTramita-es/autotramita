"""F2-T06 against real Keycloak 26.8.2: the application's web sign-in, back-channel logout and
step-up with Keycloak's own pages, tokens and keys, on real PostgreSQL and Redis.
Runs only in the ``keycloak`` CI job."""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from app.auth.web.csrf import csrf_token
from sqlalchemy import text
from tests.identity.kc import Admin, BackchannelSink
from tests.identity.rig import ORIGIN, SESSION, Rig

pytestmark = pytest.mark.keycloak

API = "/api/v1/auth"


def secure_headers(rig: Rig) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(rig.api.cookies[SESSION]), "Origin": ORIGIN}


def test_sign_in_session_and_logout_with_keycloak(rig: Rig, admin: Admin) -> None:
    user = admin.create_user()
    done = rig.sign_in(user, "/app/cases")
    assert done.status_code == 302 and done.headers["location"] == "/app/cases", done.text
    info = rig.api.get(f"{API}/session")
    assert info.status_code == 200, info.text
    body = info.json()
    assert body["user"]["email"] == user.email and body["user"]["status"] == "ACTIVE"
    assert body["auth_level"] == "LOA1" and body["client_type"] == "WEB"
    assert rig.rows("SELECT count(*) FROM users") == [(1,)]
    logout = rig.api.post(f"{API}/logout", headers=secure_headers(rig))
    assert (
        logout.status_code == 200
        and "/protocol/openid-connect/logout" in logout.json()["end_session_url"]
    )
    assert rig.api.get(f"{API}/session").status_code == 401


def test_a_second_sign_in_after_logout_inside_the_same_keycloak_session_works(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    assert rig.api.post(f"{API}/logout", headers=secure_headers(rig)).status_code == 200
    again = rig.sign_in(user)  # Keycloak's SSO cookie is still in the browser: same sid
    assert again.status_code == 302 and rig.api.get(f"{API}/session").status_code == 200
    assert rig.rows("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL") == [(1,)]


def test_a_replayed_keycloak_callback_and_a_foreign_state_are_refused(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    start = rig.api.get(f"{API}/login")
    callback = rig.at_keycloak(start.headers["location"], user)
    assert rig.api.get(callback).status_code == 302
    replay = rig.api.get(callback)
    assert replay.status_code == 400 and replay.json()["code"] == "AUTH_CALLBACK_REJECTED"
    forged = parse_qs(urlparse(callback).query)
    forged["state"] = ["A" * 32]
    assert (
        rig.api.get(f"{API}/callback", params={k: v[0] for k, v in forged.items()}).status_code
        == 400
    )


def test_keycloaks_back_channel_logout_token_is_accepted_once_and_ends_the_session(
    rig: Rig, admin: Admin, backchannel: BackchannelSink
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    assert rig.api.get(f"{API}/session").status_code == 200
    before = len(backchannel.bodies)
    assert admin.service("POST", f"/users/{user.id}/logout").status_code == 204
    deadline = time.monotonic() + 15
    while len(backchannel.bodies) <= before and time.monotonic() < deadline:
        time.sleep(0.3)
    assert len(backchannel.bodies) > before, "Keycloak sent no logout token"
    raw = backchannel.bodies[-1]["logout_token"][0]
    form = {"content-type": "application/x-www-form-urlencoded"}
    first = rig.api.post(
        f"{API}/oidc/backchannel-logout", content=f"logout_token={raw}", headers=form
    )
    assert first.status_code == 204, first.text
    second = rig.api.post(
        f"{API}/oidc/backchannel-logout", content=f"logout_token={raw}", headers=form
    )
    assert second.status_code == 400 and second.json()["code"] == "LOGOUT_TOKEN_INVALID"
    gone = rig.api.get(f"{API}/session")
    assert gone.status_code == 401 and gone.json()["code"] == "SESSION_REVOKED"


def test_reauthentication_step_up_through_keycloak_rotates_the_credential(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    old = rig.api.cookies[SESSION]
    asked = rig.api.post(
        f"{API}/step-up",
        json={"purpose": "REAUTHENTICATE", "return_to": "/ops"},
        headers=secure_headers(rig),
    )
    assert asked.status_code == 200, asked.text
    callback = rig.at_keycloak(asked.json()["redirect_url"], user)  # prompt=login: password again
    done = rig.api.get(callback)
    assert done.status_code == 302 and done.headers["location"] == "/ops", done.text
    assert rig.api.cookies[SESSION] != old
    info = rig.api.get(f"{API}/session").json()
    assert info["step_up_expires_at"] is not None
    stale = rig.api.get(f"{API}/session", headers={"Cookie": f"{SESSION}={old}"})
    assert stale.status_code == 401


def test_a_deactivated_keycloak_user_is_refused_by_the_application_too(
    rig: Rig, admin: Admin
) -> None:
    user = admin.create_user()
    assert rig.sign_in(user).status_code == 302
    with rig.role_env.admin_engine().connect() as c:
        c.execute(text("UPDATE users SET status = 'DEACTIVATED'"))
    refused = rig.api.get(f"{API}/session")
    assert refused.status_code == 403 and refused.json()["code"] == "ACCOUNT_DISABLED"
