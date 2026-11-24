"""F2-T07 against real Keycloak 26.4.7: a native-style sign-in (authorization code + PKCE with
the public client), real access tokens against the application's mobile session routes.
Runs only in the ``keycloak`` CI job."""

import pytest
from tests.identity.kc import MOBILE_REDIRECT, WEB_REDIRECT, Admin, Browser, Env, TestUser
from tests.identity.rig import Rig

pytestmark = pytest.mark.keycloak

OPEN = "/api/v1/auth/mobile/session"
DEVICE = {"device": {"label": "Test phone", "platform": "android", "app_version": "1.0.0"}}


def access_token(env: Env, user: TestUser, client: str = "at-mobile") -> str:
    browser = Browser(env)
    redirect = MOBILE_REDIRECT if client == "at-mobile" else WEB_REDIRECT
    page = browser.login(user, client_id=client, redirect_uri=redirect)
    tokens = browser.token(client, page.require_code(), redirect)
    return str(tokens["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_real_access_token_opens_lists_and_closes_a_mobile_session(
    rig: Rig, env: Env, admin: Admin
) -> None:
    user = admin.create_user()
    token = access_token(env, user)
    first = rig.api.post(OPEN, json=DEVICE, headers=bearer(token))
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["client_type"] == "MOBILE" and body["user"]["email"] == user.email
    assert rig.api.post(OPEN, json=DEVICE, headers=bearer(token)).json()["session_id"] == (
        body["session_id"])  # fmt: skip
    listed = rig.api.get("/api/v1/sessions", headers=bearer(token)).json()
    assert [i["current"] for i in listed["items"]] == [True]
    state = rig.api.get("/api/v1/auth/session", headers=bearer(token))
    assert state.status_code == 200 and state.json()["csrf_token"] is None
    # the token is still valid, but the application session is gone: revocation wins
    gone = rig.api.delete(f"/api/v1/sessions/{body['session_id']}", headers=bearer(token))
    assert gone.status_code == 204
    after = rig.api.get("/api/v1/auth/session", headers=bearer(token))
    assert after.status_code == 401 and after.json()["code"] == "SESSION_REVOKED"
    again = rig.api.post(OPEN, json=DEVICE, headers=bearer(token))
    assert again.status_code == 401 and again.json()["code"] == "SESSION_REVOKED"


def test_a_fresh_real_token_may_sign_out_everywhere(rig: Rig, env: Env, admin: Admin) -> None:
    user = admin.create_user()
    token = access_token(env, user)
    assert rig.api.post(OPEN, json=DEVICE, headers=bearer(token)).status_code == 201
    done = rig.api.post("/api/v1/sessions/revoke-all", headers=bearer(token))
    assert done.status_code == 200 and done.json() == {"revoked": 1}


def test_the_web_clients_access_token_is_not_accepted_as_a_mobile_bearer(
    rig: Rig, env: Env, admin: Admin
) -> None:
    user = admin.create_user()
    token = access_token(env, user, client="at-web")
    refused = rig.api.post(OPEN, json=DEVICE, headers=bearer(token))
    assert refused.status_code == 401 and refused.json()["code"] == "AUTH_TOKEN_INVALID"


def test_the_same_person_on_two_keycloak_sessions_has_two_application_sessions(
    rig: Rig, env: Env, admin: Admin
) -> None:
    user = admin.create_user()
    first, second = access_token(env, user), access_token(env, user)
    a = rig.api.post(OPEN, json=DEVICE, headers=bearer(first))
    b = rig.api.post(OPEN, json=DEVICE, headers=bearer(second))
    assert a.status_code == b.status_code == 201
    assert a.json()["session_id"] != b.json()["session_id"]
    assert len(rig.api.get("/api/v1/sessions", headers=bearer(first)).json()["items"]) == 2
