"""D37 endpoints against disposable PostgreSQL/Redis; worker remains disabled by default."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.auth.fake_admin import RecordingNotifier
from tests.auth.security.test_security_policies import API, Rig, secure

pytest_plugins = ["tests.auth.security.test_security_policies"]


class VerificationSink(RecordingNotifier):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, UUID, str]] = []

    def send_email_change_verification(
        self, *, to: str, origin: str, operation_id: UUID, token: str
    ) -> None:
        self.links.append((to, origin, operation_id, token))


def enable(rig: Rig) -> VerificationSink:
    sink = VerificationSink()
    rig.web.runtime.notifier = sink
    rig.web.runtime.email_change_ready = True
    return sink


def post(client: TestClient, path: str, body: dict[str, str]) -> object:
    return client.post(f"{API}{path}", headers=secure(client), json=body)


def test_email_change_is_closed_until_worker_is_wired(rig: Rig) -> None:
    client = rig.login()
    response = client.post(
        f"{API}/me/security/email-change-requests",
        headers=secure(client),
        json={"new_email": "new@example.test"},
    )
    assert response.status_code == 503


def test_request_reissue_confirmation_csrf_and_no_token_storage(rig: Rig) -> None:
    sink = enable(rig)
    client = rig.login()
    path = f"{API}/me/security/email-change-requests"
    body = {"new_email": "new@example.test"}
    assert client.post(path, json=body).status_code == 403
    first = client.post(path, headers=secure(client), json=body)
    assert first.status_code == 202 and first.json() == {"status": "accepted"}
    assert len(sink.links) == 1
    _, _, old_id, old_token = sink.links[0]
    second = client.post(path, headers=secure(client), json=body)
    assert second.status_code == 202 and len(sink.links) == 2
    _, _, new_id, token = sink.links[-1]
    assert new_id != old_id and token != old_token
    snapshot = repr(rig.web.rows("SELECT row_to_json(o)::text FROM email_change_operations o"))
    assert token not in snapshot and old_token not in snapshot
    confirm = f"{API}/me/security/email-change-confirmations"
    assert (
        client.post(
            confirm, headers=secure(client), json={"operation_id": str(new_id), "token": token}
        ).status_code
        == 202
    )
    assert (
        client.post(
            confirm, headers=secure(client), json={"operation_id": str(new_id), "token": token}
        ).status_code
        == 202
    )
    rows = rig.web.rows(
        "SELECT status, token_hash FROM email_change_operations ORDER BY created_at"
    )
    assert rows == [("CANCELLED", None), ("CONFIRMED", None)]


def test_other_user_cannot_confirm_and_duplicate_response_is_generic(rig: Rig) -> None:
    sink = enable(rig)
    a = rig.login()
    rig.admin.add("used@example.test", "sub-other")
    b = rig.login("sub-other", "used@example.test")
    request = f"{API}/me/security/email-change-requests"
    duplicate = a.post(request, headers=secure(a), json={"new_email": "used@example.test"})
    free = a.post(request, headers=secure(a), json={"new_email": "free@example.test"})
    assert (duplicate.status_code, duplicate.json()) == (free.status_code, free.json())
    assert len(sink.links) == 1
    _, _, operation, token = sink.links[0]
    confirm = f"{API}/me/security/email-change-confirmations"
    attempted = b.post(
        confirm,
        headers=secure(b),
        json={
            "operation_id": str(operation),
            "token": token,
        },
    )
    assert attempted.status_code == 202
    assert rig.web.rows("SELECT status FROM email_change_operations") == [("PENDING",)]


def test_verification_page_has_strict_csp_and_does_not_send_fragment(rig: Rig) -> None:
    client = rig.web.client()
    response = client.get(f"{API}/auth/email-change-verification")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "script-src 'sha256-" in response.headers["content-security-policy"]
    assert "location.hash" in response.text and "email-change-confirmations" in response.text


def test_account_lookup_and_delivery_are_deferred_after_generic_response(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import me

    enable(rig)
    user = rig.login()
    deferred: list[str] = []
    monkeypatch.setattr(
        me,
        "_process_email_change_request",
        lambda request, principal, runtime, address, origin: deferred.append(address),
    )
    rig.admin.calls.clear()
    response = user.post(
        f"{API}/me/security/email-change-requests",
        headers=secure(user),
        json={"new_email": "new@example.test"},
    )
    assert response.status_code == 202
    # Before the answer only the caller's own second factors are read (F-3 step-up); nothing
    # about the requested address is looked up or mailed until afterwards.
    assert rig.admin.calls == ["credentials"] and deferred == ["new@example.test"]
