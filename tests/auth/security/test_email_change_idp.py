"""D37 provider operations identify accounts only by immutable subject."""

import json

import httpx
import pytest
from app.auth.idp import IdpAdminError, IdpConflict
from app.auth.idp_admin import KeycloakAdmin
from tests.auth.security.test_security_units import settings


def test_read_and_update_use_subject_and_never_log_identity_data() -> None:
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "example", "expires_in": 60})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "user-1",
                    "email": "old@example.test",
                    "username": "old@example.test",
                    "emailVerified": True,
                },
            )
        return httpx.Response(204)

    admin = KeycloakAdmin(settings(), client=httpx.Client(transport=httpx.MockTransport(provider)))
    state = admin.get_email_state("user-1")
    assert state.subject == "user-1" and state.email == "old@example.test"
    assert state.email_verified and "old@example.test" not in repr(state)
    admin.set_verified_email("user-1", "new@example.test")
    assert requests[-1].url.path.endswith("/users/user-1")
    assert json.loads(requests[-1].content) == {
        "email": "new@example.test",
        "username": "new@example.test",
        "emailVerified": True,
    }


def test_wrong_subject_and_conflict_fail_closed() -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "example", "expires_in": 60})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "other",
                    "email": "a@example.test",
                    "username": "a@example.test",
                    "emailVerified": True,
                },
            )
        return httpx.Response(409, json={"errorMessage": "secret@example.test"})

    admin = KeycloakAdmin(settings(), client=httpx.Client(transport=httpx.MockTransport(provider)))
    with pytest.raises(IdpAdminError):
        admin.get_email_state("user-1")
    with pytest.raises(IdpConflict) as caught:
        admin.set_verified_email("user-1", "b@example.test")
    assert "@" not in str(caught.value)
