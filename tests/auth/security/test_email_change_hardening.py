"""D37 request and confirmation through the API: authentication freshness, session binding,
token substitution and expiry, address syntax, mobile callers, the confirmation page and data
minimisation. Real PostgreSQL 16 and Redis 7, fake identity provider."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from app.auth.security import email_change
from app.auth.security.email_change_worker import run_once
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.auth.fake_idp import NOW
from tests.auth.security.test_email_change_api import VerificationSink, enable
from tests.auth.security.test_security_policies import API, EMAIL, SUB, Rig, secure
from tests.auth.sessions.test_sessions_db import factory
from tests.auth.web_harness import SESSION_COOKIE

pytest_plugins = ["tests.auth.security.test_security_policies"]

REQUEST = f"{API}/me/security/email-change-requests"
CONFIRM = f"{API}/me/security/email-change-confirmations"
NEW = "new@example.test"


def ask(client: TestClient, address: str = NEW) -> Any:
    return client.post(REQUEST, headers=secure(client), json={"new_email": address})


def confirm(client: TestClient, operation: UUID, token: str) -> Any:
    return client.post(
        CONFIRM, headers=secure(client), json={"operation_id": str(operation), "token": token}
    )


def statuses(rig: Rig) -> list[str]:
    rows = rig.web.rows("SELECT status FROM email_change_operations ORDER BY created_at, id")
    return [str(r[0]) for r in rows]


def sweep(rig: Rig) -> None:
    run_once(factory(rig.web.env, "worker"), rig.admin, None)


def local_email(rig: Rig) -> str:
    return str(rig.web.rows("SELECT email FROM users WHERE auth_subject = :s", s=SUB)[0][0])


# --- address syntax ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "address",
    [
        "victim.example<attacker@evil.test>",
        "attacker,victim@example.test",
        "a;b@example.test",
        '"quoted"@example.test',
        "name(comment)@example.test",
        "back\\slash@example.test",
        "a:b@example.test",
        "[x]@example.test",
        "x@example.test\r\nBcc: y@example.test",
        "two@@example.test",
    ],
)
def test_an_address_a_mail_library_could_read_differently_is_refused(
    rig: Rig, address: str
) -> None:
    sink = enable(rig)
    client = rig.login()
    assert ask(client, address).status_code == 422
    assert sink.links == [] and statuses(rig) == []
    with pytest.raises(ValueError):
        email_change.prepare_new_address(address)


@pytest.mark.parametrize(
    "address", ["first.last+tag@example.test", "o'brien@example.test", "ñandú@correo.example"]
)
def test_ordinary_addresses_are_kept_as_typed(address: str) -> None:
    assert email_change.prepare_new_address(f"  {address} ")[0] == address


# --- authentication freshness, CSRF and limits ------------------------------------------------
def test_both_steps_need_a_fresh_authentication(rig: Rig) -> None:
    sink = enable(rig)
    old = int(time.time()) - 3600
    stale = rig.login(sid="old", auth_time=old)
    refused = ask(stale)
    assert refused.status_code == 401 and refused.json()["code"] == "STEP_UP_REQUIRED"
    assert sink.links == []
    fresh = rig.login(sid="new")
    assert ask(fresh).status_code == 202
    _, _, operation, token = sink.links[-1]
    late = confirm(stale, operation, token)
    assert late.status_code == 401 and late.json()["code"] == "STEP_UP_REQUIRED"
    assert statuses(rig) == ["PENDING"]


def test_confirmation_needs_the_csrf_token_and_a_session(rig: Rig) -> None:
    sink = enable(rig)
    client = rig.login()
    ask(client)
    _, _, operation, token = sink.links[-1]
    body = {"operation_id": str(operation), "token": token}
    assert client.post(CONFIRM, json=body).status_code == 403
    assert rig.web.client().post(CONFIRM, json=body).status_code == 401
    assert statuses(rig) == ["PENDING"]


def test_a_fourth_request_in_an_hour_sends_nothing_and_looks_the_same(rig: Rig) -> None:
    sink = enable(rig)
    client = rig.login()
    answers = [ask(client, f"n{i}@example.test") for i in range(4)]
    assert [a.status_code for a in answers] == [202] * 4
    assert len({a.text for a in answers}) == 1
    assert [link[0] for link in sink.links] == [f"n{i}@example.test" for i in range(3)]
    assert statuses(rig) == ["CANCELLED", "CANCELLED", "PENDING"]


def test_confirmation_is_rate_limited(rig: Rig) -> None:
    enable(rig)
    client = rig.login()
    answers = [confirm(client, uuid4(), "A" * 43).status_code for _ in range(11)]
    assert answers == [202] * 10 + [429]


def test_the_old_address_and_login_stay_until_the_change_is_confirmed(rig: Rig) -> None:
    sink = enable(rig)
    client = rig.login()
    ask(client)
    sweep(rig)  # an unconfirmed request is never applied
    assert local_email(rig) == EMAIL and "set_email" not in rig.admin.calls
    assert rig.login(sid="again").get(f"{API}/auth/session").status_code == 200
    _, _, operation, token = sink.links[-1]
    assert confirm(client, operation, token).status_code == 202
    assert local_email(rig) == EMAIL  # confirmation only records the intent
    sweep(rig)
    assert local_email(rig) == NEW and rig.admin.calls.count("set_email") == 1


# --- token substitution, replay and expiry ----------------------------------------------------
def test_a_token_only_confirms_its_own_operation_of_its_own_person(rig: Rig) -> None:
    sink = enable(rig)
    a = rig.login()
    rig.admin.add("b@example.test", "sub-b")
    b = rig.login("sub-b", "b@example.test")
    ask(a, "a-first@example.test")
    ask(a, "a-second@example.test")
    ask(b, "b-new@example.test")
    (_, _, first_id, first), (_, _, second_id, second), (_, _, b_id, b_token) = sink.links
    for client, operation, token in (
        (a, second_id, first),  # a replaced token on the new operation
        (a, first_id, second),  # the new token on the replaced operation
        (a, b_id, b_token),  # somebody else's operation with its genuine token
        (b, second_id, second),  # ... and the other way round
        (a, second_id, b_token),
        (b, b_id, second),
    ):
        assert confirm(client, operation, token).status_code == 202
    assert statuses(rig) == ["CANCELLED", "PENDING", "PENDING"]
    confirm(a, second_id, second)
    confirm(b, b_id, b_token)
    assert statuses(rig) == ["CANCELLED", "CONFIRMED", "CONFIRMED"]


def test_an_expired_token_changes_nothing(rig: Rig) -> None:
    sink = enable(rig)
    client = rig.login()
    ask(client)
    _, _, operation, token = sink.links[-1]
    with rig.web.env.admin_engine().connect() as db:
        db.execute(
            text(
                "UPDATE email_change_operations SET "
                "token_issued_at = now() - interval '31 minutes', "
                "token_expires_at = now() - interval '1 minute'"
            )
        )
    assert confirm(client, operation, token).status_code == 202
    assert statuses(rig) == ["PENDING"]
    sweep(rig)
    assert statuses(rig) == ["EXPIRED"] and local_email(rig) == EMAIL
    assert rig.web.rows("SELECT token_hash, old_email, new_email FROM email_change_operations") == [
        (None, None, None)
    ]


@pytest.mark.parametrize("how", ["revoke_others", "revoke_one"])
def test_a_request_dies_with_the_session_the_person_ended(rig: Rig, how: str) -> None:
    sink = enable(rig)
    intruder = rig.login(sid="intruder")
    ask(intruder)
    _, _, operation, token = sink.links[-1]
    owner = rig.login(sid="owner")
    if how == "revoke_others":
        assert owner.post(f"{API}/sessions/revoke-others", headers=secure(owner)).status_code == 200
    else:
        target = intruder.get(f"{API}/auth/session").json()["session_id"]
        assert owner.delete(f"{API}/sessions/{target}", headers=secure(owner)).status_code == 204
    assert confirm(owner, operation, token).status_code == 202
    assert statuses(rig) == ["PENDING"]
    sweep(rig)
    assert local_email(rig) == EMAIL


def test_an_ordinary_sign_out_does_not_cancel_the_request(rig: Rig) -> None:
    sink = enable(rig)
    first = rig.login(sid="first")
    ask(first)
    _, _, operation, token = sink.links[-1]
    assert first.post(f"{API}/auth/logout", headers=secure(first)).status_code == 200
    second = rig.login(sid="second")
    confirm(second, operation, token)
    assert statuses(rig) == ["CONFIRMED"]


# --- sign-ins after a completed change --------------------------------------------------------
def complete(rig: Rig) -> tuple[TestClient, TestClient]:
    sink = enable(rig)
    owner = rig.login(sid="owner")
    other = rig.login(sid="other")
    ask(owner)
    _, _, operation, token = sink.links[-1]
    confirm(owner, operation, token)
    sweep(rig)
    assert statuses(rig) == ["COMPLETED"]
    return owner, other


def test_a_surviving_sign_on_session_cannot_reopen_a_revoked_session(rig: Rig) -> None:
    owner, other = complete(rig)
    assert owner.get(f"{API}/auth/session").status_code == 200
    assert other.get(f"{API}/auth/session").status_code == 401
    earlier = int(time.time()) - 3600
    again = rig.web.client()
    refused = rig.web.sign_in(again, sub=SUB, email=NEW, sid="other", auth_time=earlier)
    assert refused.status_code == 302 and SESSION_COOKIE not in again.cookies
    query = {k: v[0] for k, v in parse_qs(urlparse(refused.headers["location"]).query).items()}
    assert query["prompt"] == "login" and query["max_age"] == "0"
    assert rig.live_sessions() == 1
    # after typing the password again the same device is welcome
    code = rig.web.code_for(query, sub=SUB, email=NEW, sid="other", auth_time=int(time.time()) + 90)
    done = again.get(f"{API}/auth/callback", params={"code": code, "state": query["state"]})
    assert done.status_code == 302 and SESSION_COOKIE in again.cookies
    assert rig.live_sessions() == 2


def test_the_session_that_asked_for_the_change_may_sign_in_again(rig: Rig) -> None:
    complete(rig)
    same = rig.web.client()
    done = rig.web.sign_in(same, sub=SUB, email=NEW, sid="owner", auth_time=int(time.time()) - 3600)
    assert done.status_code == 302 and done.headers["location"] == "/"
    assert SESSION_COOKIE in same.cookies


def test_a_mobile_app_with_an_older_sign_in_must_authenticate_again(rig: Rig) -> None:
    complete(rig)
    old = rig.web.access(sub=SUB, email=NEW, sid="phone", auth_time=int(time.time()) - 3600)
    refused = rig.web.bearer(old).post(f"{API}/auth/mobile/session", json={})
    assert refused.status_code == 401 and refused.json()["code"] == "SESSION_REVOKED"
    fresh = rig.web.access(sub=SUB, email=NEW, sid="phone", auth_time=int(time.time()) + 90)
    assert rig.web.bearer(fresh).post(f"{API}/auth/mobile/session", json={}).status_code == 201


# --- mobile callers ---------------------------------------------------------------------------
def test_a_mobile_caller_gets_a_link_to_the_web_origin(rig: Rig) -> None:
    sink = enable(rig)
    token = rig.web.access(sub=SUB, email=EMAIL, sid="phone", auth_time=int(NOW) - 5)
    phone = rig.web.client(
        host="api.autotramita.example", headers={"authorization": f"Bearer {token}"}
    )
    assert phone.post(f"{API}/auth/mobile/session", json={}).status_code == 201
    assert phone.post(REQUEST, json={"new_email": NEW}).status_code == 202
    assert [(link[0], link[1]) for link in sink.links] == [(NEW, "https://autotramita.example")]


# --- the confirmation page --------------------------------------------------------------------
def page_script(rig: Rig) -> tuple[str, str]:
    response = rig.web.client().get(f"{API}/auth/email-change-verification")
    found = re.search(r"<script>(.*?)</script>", response.text, re.S)
    assert found
    return found.group(1), response.headers["content-security-policy"]


def test_the_content_security_policy_hash_is_the_hash_of_the_served_script(rig: Rig) -> None:
    script, policy = page_script(rig)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in policy
    assert "default-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert "unsafe" not in policy


HARNESS = """
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const calls = [], history = [];
let click;
const elements = {
  confirm: { disabled: false, addEventListener: (_, f) => { click = f; } },
  status: { textContent: '' },
};
const context = {
  document: { getElementById: (id) => elements[id] },
  location: { hash: input.hash, pathname: '/api/v1/auth/email-change-verification' },
  history: { replaceState: (_a, _b, path) => history.push(path) },
  URLSearchParams,
  fetch: async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/auth/session')) {
      return { ok: input.session, json: async () => ({ csrf_token: 'csrf-value' }) };
    }
    return { ok: input.confirm };
  },
};
vm.runInNewContext(input.script, context);
click().then(() => process.stdout.write(JSON.stringify(
  { calls, history, status: elements.status.textContent, disabled: elements.confirm.disabled })));
"""


def run_page(script: str, hash_: str, *, session: bool = True, ok: bool = True) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "Node.js is required to execute the confirmation page script"
    done = subprocess.run(  # noqa: S603 - fixed program, test input on stdin
        [node, "-e", HARNESS],
        input=json.dumps({"script": script, "hash": hash_, "session": session, "confirm": ok}),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_the_confirmation_script_posts_the_fragment_with_the_csrf_token(rig: Rig) -> None:
    script, _ = page_script(rig)
    operation, token = str(uuid4()), "t" * 43
    out = run_page(script, f"#id={operation}&token={token}")
    assert [c["url"] for c in out["calls"]] == ["/api/v1/auth/session", CONFIRM]
    post = out["calls"][1]["options"]
    assert post["method"] == "POST" and post["headers"]["X-CSRF-Token"] == "csrf-value"
    assert json.loads(post["body"]) == {"operation_id": operation, "token": token}
    assert all(token not in c["url"] for c in out["calls"])  # never in a URL
    assert out["history"] == ["/api/v1/auth/email-change-verification"]  # fragment removed
    assert out["disabled"] is False and "Solicitud recibida" in out["status"]


def test_the_confirmation_script_sends_nothing_without_a_link_or_a_session(rig: Rig) -> None:
    script, _ = page_script(rig)
    good = f"#id={uuid4()}&token={'t' * 43}"
    for bad in ("", "#id=x&token=y", f"#id={uuid4()}"):
        assert run_page(script, bad)["calls"] == []
    signed_out = run_page(script, good, session=False)
    assert len(signed_out["calls"]) == 1 and signed_out["history"] == []
    stale = run_page(script, good, ok=False)
    assert stale["history"] == [] and "autenticarte" in stale["status"]


# --- minimisation -----------------------------------------------------------------------------
def test_no_address_token_or_link_reaches_logs_or_audit(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sink = enable(rig)
    client = rig.login()
    ask(client)
    _, _, operation, token = sink.links[-1]
    confirm(client, operation, token)
    rig.admin.down = True
    sweep(rig)  # a failed attempt is logged
    rig.admin.down = False
    with rig.web.env.admin_engine().connect() as db:
        db.execute(text("UPDATE email_change_operations SET next_attempt_at = now()"))
    sweep(rig)
    assert statuses(rig) == ["COMPLETED"]
    records = caplog.text + json.dumps(
        [getattr(r, "fields", None) for r in caplog.records], default=str
    )
    audit = json.dumps(rig.web.rows("SELECT row_to_json(a)::text FROM audit_events a"))
    for secret in (token, NEW, EMAIL, client.cookies[SESSION_COOKIE]):
        assert secret not in records and secret not in audit
    assert "email change reconciliation deferred" in caplog.text
    changed = rig.web.rows(
        "SELECT actor_type, actor_user_id, details::text FROM audit_events "
        "WHERE action = 'identity.email.changed'"
    )
    assert changed == [("SYSTEM", None, "{}")]


def test_only_the_sha256_of_the_verification_token_is_stored(rig: Rig) -> None:
    sink: VerificationSink = enable(rig)
    client = rig.login()
    ask(client)
    token = sink.links[-1][3]
    dump = json.dumps(rig.web.rows("SELECT row_to_json(o)::text FROM email_change_operations o"))
    assert token not in dump
    stored = rig.web.rows("SELECT token_hash FROM email_change_operations")[0][0]
    assert bytes(stored) == hashlib.sha256(token.encode()).digest()
