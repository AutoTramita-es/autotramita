"""The controlled switch-off of the second factor through the application (Keycloak security
provider order, 2026-11-25). The provider does the switch-off itself, in one transaction under its
lock; the application starts it only for a person with a fresh second factor whose factor is not
mandatory, and on the way back trusts the provider's credentials, never the status in the address.
Real PostgreSQL 16 and Redis 7, a fake identity provider."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.auth.idp import IdpCredential
from app.auth.security.notify import NoticeKind
from fastapi.testclient import TestClient
from tests.auth.security.test_account_step_up import enrolled, evidence, post, signed_in
from tests.auth.security.test_security_policies import API, EMAIL, SUB, Rig, problem
from tests.auth.web_harness import SESSION_COOKIE

pytest_plugins = ["tests.auth.security.test_security_policies"]

PATH = "/me/security/mfa-disable-requests"
CONFIRMED = {"confirm": "DISABLE_MFA", "return_to": "/me"}


@pytest.fixture(autouse=True)
def real_clock(rig: Rig) -> None:
    rig.web.clock.now = time.time()


def start(client: TestClient, body: dict[str, Any] | None = None) -> httpx.Response:
    return post(client, PATH, CONFIRMED if body is None else body)


def come_back(
    rig: Rig, client: TestClient, started: httpx.Response, **claims: Any
) -> httpx.Response:
    query = {k: v[0] for k, v in parse_qs(urlparse(started.json()["redirect_url"]).query).items()}
    code = rig.web.code_for(query, sub=SUB, email=EMAIL, sid="s-action", **claims)
    done: httpx.Response = client.get(
        f"{API}/auth/callback",
        params={"code": code, "state": query["state"], "kc_action_status": "success"},
    )
    return done


def nothing_happened(rig: Rig) -> None:
    assert rig.audit("security.mfa.disabled") == []
    assert NoticeKind.MFA_DISABLED not in [n.kind for n in rig.notifier.notices]


def test_the_provider_is_asked_for_its_switch_off_after_a_fresh_factor(rig: Rig) -> None:
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    started = start(client)
    assert started.status_code == 200, started.text
    query = parse_qs(urlparse(started.json()["redirect_url"]).query)
    assert query["kc_action"] == ["at-disable-mfa"] and query["acr_values"] == ["loa2"]


@pytest.mark.parametrize(
    "body",
    [{}, {"confirm": "yes"}, {"confirm": "DISABLE_MFA", "extra": 1}],
    ids=["no_confirmation", "wrong_confirmation", "unknown_field"],
)
def test_without_the_explicit_confirmation_nothing_starts(rig: Rig, body: dict[str, Any]) -> None:
    client = signed_in(rig, factor_age=20)
    enrolled(rig)
    assert start(client, body).status_code == 422


def test_a_password_alone_cannot_start_it(rig: Rig) -> None:
    client = signed_in(rig)  # password only, the account has a factor
    enrolled(rig)
    refused = start(client)
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa2"' in refused.headers["www-authenticate"]


def test_there_is_nothing_to_switch_off_without_a_factor(rig: Rig) -> None:
    client = signed_in(rig)
    problem(start(client), 409, "NO_SECOND_FACTOR")


def test_a_mandatory_second_factor_cannot_be_switched_off(rig: Rig) -> None:
    """The enforcement point T10 needs: today nothing marks a person, so this sets the flag."""
    client = signed_in(rig, factor_age=20)
    enrolled(rig)
    rig.admin.mandatory.add(SUB)
    problem(start(client), 403, "SECOND_FACTOR_MANDATORY")


def test_when_the_provider_cannot_say_whether_it_is_mandatory_nothing_starts(rig: Rig) -> None:
    client = signed_in(rig, factor_age=20)
    enrolled(rig)
    real = rig.admin.is_factor_mandatory

    def unavailable(subject: str) -> bool:
        rig.admin.down = True
        try:
            return real(subject)
        finally:
            rig.admin.down = False

    rig.admin.is_factor_mandatory = unavailable  # type: ignore[method-assign]
    problem(start(client), 503, "IDENTITY_PROVIDER_UNAVAILABLE")


def test_a_switch_off_done_by_the_provider_ends_every_session_audits_and_notifies(
    rig: Rig,
) -> None:
    other = signed_in(rig, factor_age=20, sid="other")
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    started = start(client)
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", 1)]  # what the provider left
    done = come_back(rig, client, started, **evidence(5))
    assert done.status_code == 302
    assert done.headers["location"] == "/me?security_action=success"
    cookie = done.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie and "Max-Age=0" in cookie
    assert rig.live_sessions() == 0
    for browser in (client, other):
        assert browser.get(f"{API}/auth/session").status_code == 401
    assert rig.audit("security.mfa.disabled")[0][0] == "SUCCESS"
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.MFA_DISABLED]
    assert rig.web.rows(
        "SELECT details::text FROM audit_events WHERE action = 'security.mfa.disabled'"
    ) == [("{}",)]


def test_a_status_in_the_address_is_not_believed_while_factors_remain(rig: Rig) -> None:
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    started = start(client)
    done = come_back(rig, client, started, **evidence(5))  # the factor is still there
    assert done.headers["location"] == "/me?security_action=cancelled"
    assert client.get(f"{API}/auth/session").status_code == 200
    nothing_happened(rig)


def test_a_switch_off_that_came_back_without_the_factor_ends_every_session(rig: Rig) -> None:
    client = signed_in(rig, factor_age=20, sid="s-action")
    enrolled(rig)
    started = start(client)
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", 1)]
    done = come_back(rig, client, started, **evidence(None))  # the level request was dropped
    assert done.headers["location"] == "/me?security_action=reauthentication_required"
    assert rig.live_sessions() == 0
    assert rig.audit("security.step_up.failed")[0][0] == "FAILURE"
