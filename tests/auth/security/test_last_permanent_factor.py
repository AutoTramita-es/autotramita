"""F2-T09-REC final MFA decision: recovery codes are the backup of a permanent factor, so the
last permanent factor stays while codes remain, and an account that must keep a second factor
keeps one. Real PostgreSQL 16 and Redis 7, a fake identity provider."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from app.auth.idp import PERMANENT_FACTOR_TYPES, IdpAdminError, IdpCredential
from app.auth.security.notify import NoticeKind
from fastapi.testclient import TestClient
from tests.auth.security.test_account_step_up import evidence, signed_in
from tests.auth.security.test_security_policies import API, SUB, Rig, problem, secure

pytest_plugins = ["tests.auth.security.test_security_policies"]

PERMANENT = sorted(PERMANENT_FACTOR_TYPES)
CODES = "recovery-authn-codes"


@pytest.fixture(autouse=True)
def real_clock(rig: Rig) -> None:
    rig.web.clock.now = time.time()


def holding(rig: Rig, *kinds: str, obliged: bool = False) -> TestClient:
    client = signed_in(rig, factor_age=10)
    rig.admin.credentials[SUB] = [IdpCredential("c-pw", "password", 1)] + [
        IdpCredential(f"c-{kind}", kind, 2) for kind in kinds
    ]
    if obliged:
        rig.admin.obliged.add(SUB)
    return client


def remove(client: TestClient, kind: str) -> httpx.Response:
    response: httpx.Response = client.delete(
        f"{API}/me/security/second-factors/c-{kind}", headers=secure(client)
    )
    return response


def refused(rig: Rig, response: httpx.Response) -> None:
    problem(response, 409, "LAST_PERMANENT_FACTOR")
    assert rig.admin.deleted == [] and rig.notifier.notices == []
    assert rig.audit("security.mfa.removed") == []


@pytest.mark.parametrize("kind", PERMANENT)
def test_the_last_permanent_factor_stays_while_recovery_codes_remain(rig: Rig, kind: str) -> None:
    client = holding(rig, kind, CODES)
    refused(rig, remove(client, kind))


@pytest.mark.parametrize("kind", PERMANENT)
def test_without_recovery_codes_a_person_may_switch_the_second_factor_off(
    rig: Rig, kind: str
) -> None:
    client = holding(rig, kind)
    assert remove(client, kind).status_code == 204
    assert [n.kind for n in rig.notifier.notices] == [NoticeKind.MFA_REMOVED]


def test_one_of_two_permanent_factors_may_go_and_the_last_one_stays(rig: Rig) -> None:
    client = holding(rig, "otp", "webauthn", CODES)
    assert remove(client, "otp").status_code == 204
    problem(remove(client, "webauthn"), 409, "LAST_PERMANENT_FACTOR")
    assert remove(client, CODES).status_code == 204  # the backup first,
    assert remove(client, "webauthn").status_code == 204  # then the factor itself


@pytest.mark.parametrize(
    ("kinds", "target"),
    [(("otp",), "otp"), ((CODES,), CODES), (("otp", CODES), "otp")],
    ids=["only_factor", "codes_only", "factor_with_codes"],
)
def test_an_account_that_must_keep_a_factor_never_ends_without_a_permanent_one(
    rig: Rig, kinds: tuple[str, ...], target: str
) -> None:
    client = holding(rig, *kinds, obliged=True)
    refused(rig, remove(client, target))


def test_an_obliged_account_may_remove_what_leaves_a_permanent_factor(rig: Rig) -> None:
    client = holding(rig, "otp", "webauthn", CODES, obliged=True)
    assert remove(client, CODES).status_code == 204
    assert remove(client, "otp").status_code == 204
    problem(remove(client, "webauthn"), 409, "LAST_PERMANENT_FACTOR")


def test_when_the_obligation_cannot_be_read_nothing_is_removed(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = holding(rig, "otp")

    def unavailable(subject: str) -> bool:
        raise IdpAdminError("down")

    monkeypatch.setattr(rig.admin, "has_factor_obligation", unavailable)
    problem(remove(client, "otp"), 503, "IDENTITY_PROVIDER_UNAVAILABLE")
    assert rig.admin.deleted == []


def test_two_removals_at_once_cannot_both_take_a_permanent_factor(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each alone is allowed; together they would leave recovery codes only."""
    first = holding(rig, "otp", "webauthn", CODES)
    second = rig.login(sid="second", **evidence(10))
    real = rig.admin.delete_credential
    inside = threading.Event()

    def slow_delete(subject: str, credential_id: str) -> None:
        inside.set()
        time.sleep(0.5)  # the other request arrives while nothing is deleted yet
        real(subject, credential_id)

    monkeypatch.setattr(rig.admin, "delete_credential", slow_delete)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(remove, first, "otp")
        assert inside.wait(timeout=10)
        two = pool.submit(remove, second, "webauthn")
        results = [one.result(timeout=30), two.result(timeout=30)]
    assert [r.status_code for r in results] == [204, 409], [r.text for r in results]
    assert rig.admin.deleted == [(SUB, "c-otp")]
