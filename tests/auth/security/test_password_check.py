"""F-0: the periodic check of pending password resets, run by the 60 s worker. Real PostgreSQL 16
(worker database role) and Redis 7, a fake identity provider."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from app.auth.idp import IdpAdminError, IdpCredential
from app.auth.security import recovery
from app.auth.security.markers import TTL_SECONDS
from app.auth.security.notify import NoticeKind
from app.auth.security.recovery_worker import EmailChangeRecoveryWorker
from tests.auth.fake_idp import NOW
from tests.auth.security.test_security_policies import API, EMAIL, SUB, Rig, anonymous
from tests.auth.sessions.test_sessions_db import factory

pytest_plugins = ["tests.auth.security.test_security_policies"]

CHANGED = NOW + 60  # when the new password was set
OLD_SIGN_IN = int(NOW - 5)
NEW_SIGN_IN = int(CHANGED + 1)


def ask_for_recovery(rig: Rig, address: str = EMAIL) -> None:
    answer = anonymous(rig).post(f"{API}/auth/password-recovery", json={"email": address})
    assert answer.status_code == 202


def change_password(rig: Rig, sub: str = SUB, at: float = CHANGED) -> None:
    rig.admin.credentials[sub] = [IdpCredential("c-pw", "password", int(at * 1000))]


def check(rig: Rig, **kw: Any) -> None:
    recovery.check_pending_password_changes(
        rig.web.runtime, factory(rig.web.env, "worker"), rig.notifier, **kw
    )


def alive(client: Any) -> bool:
    return bool(client.get(f"{API}/auth/session").status_code == 200)


def notices(rig: Rig) -> list[tuple[NoticeKind, str]]:
    return [(n.kind, n.to) for n in rig.notifier.notices]


def pending(rig: Rig) -> list[str]:
    assert rig.web.runtime.markers
    return [subject for subject, _ in rig.web.runtime.markers.pending()]


def changes_audited(rig: Rig) -> list[tuple[Any, ...]]:
    return rig.web.rows(
        "SELECT actor_type, actor_user_id IS NULL, actor_session_id IS NULL FROM audit_events "
        "WHERE action = 'security.password.changed'"
    )


def test_a_reset_ends_every_old_session_without_anybody_signing_in(rig: Rig) -> None:
    web = rig.login(sid="s1")
    other = rig.login(sid="s2")
    token = rig.web.access(sub=SUB, email=EMAIL, sid="phone", auth_time=OLD_SIGN_IN)
    phone = rig.web.bearer(token)
    assert phone.post(f"{API}/auth/mobile/session", json={}).status_code == 201
    ask_for_recovery(rig)
    check(rig)  # nothing changed yet: nobody is signed out
    assert alive(web) and alive(other) and alive(phone) and notices(rig) == []
    change_password(rig)
    check(rig)
    assert not alive(web) and not alive(other) and not alive(phone)
    assert rig.web.rows("SELECT DISTINCT revoked_reason FROM user_sessions") == [
        ("PASSWORD_CHANGED",)
    ]
    assert notices(rig) == [(NoticeKind.PASSWORD_RESET_COMPLETED, EMAIL)]
    assert changes_audited(rig) == [("SYSTEM", True, True)]


def test_a_session_authenticated_with_the_new_password_survives(rig: Rig) -> None:
    old = rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    # the owner's sign-in is stored while the check has not run yet
    markers, rig.web.runtime.markers = rig.web.runtime.markers, None
    new = rig.login(sid="new", auth_time=NEW_SIGN_IN)
    rig.web.runtime.markers = markers
    check(rig)
    assert alive(new) and not alive(old)


def test_repeating_the_check_and_signing_in_afterwards_changes_nothing_more(rig: Rig) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    check(rig)
    check(rig)
    new = rig.login(sid="new", auth_time=NEW_SIGN_IN)
    check(rig)
    assert alive(new) and len(notices(rig)) == 1 and len(changes_audited(rig)) == 1
    stale = rig.web.sign_in(rig.web.client(), sub=SUB, email=EMAIL, sid="old")
    assert "prompt=login" in stale.headers["location"]  # still refused after the check


def test_a_sign_in_that_saw_the_change_first_leaves_the_check_nothing_to_do(rig: Rig) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    new = rig.login(sid="new", auth_time=NEW_SIGN_IN)
    check(rig)
    assert alive(new) and len(notices(rig)) == 1
    assert changes_audited(rig) == [("USER", False, False)]


def test_a_lost_marker_update_never_gives_a_second_record_or_notice(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    assert rig.web.runtime.markers
    monkeypatch.setattr(rig.web.runtime.markers, "record_change", lambda *a: None)
    check(rig)
    check(rig)
    rig.login(sid="new", auth_time=NEW_SIGN_IN)
    assert len(notices(rig)) == 1 and len(changes_audited(rig)) == 1


def test_checks_racing_each_other_give_one_record_and_one_notice(rig: Rig) -> None:
    sessions = [rig.login(sid=f"s{n}") for n in range(3)]
    ask_for_recovery(rig)
    change_password(rig)
    real = rig.admin.list_credentials
    barrier = threading.Barrier(4)

    def together(subject: str) -> list[IdpCredential]:
        found = real(subject)
        barrier.wait(timeout=10)
        return found

    rig.admin.list_credentials = together  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(check, rig) for _ in range(4)]:
            future.result(timeout=30)
    assert not any(alive(client) for client in sessions)
    assert len(notices(rig)) == 1 and len(changes_audited(rig)) == 1


def test_a_second_reset_in_the_window_is_acted_on_again(rig: Rig) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    check(rig)
    owner = rig.login(sid="new", auth_time=NEW_SIGN_IN)
    change_password(rig, at=CHANGED + 600)
    check(rig)
    assert not alive(owner) and len(notices(rig)) == 2 and len(changes_audited(rig)) == 2


def test_an_outage_postpones_and_one_person_never_delays_another(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.login(sid="a")
    rig.admin.add("b@example.test", "sub-b")
    rig.login("sub-b", "b@example.test", sid="b")
    ask_for_recovery(rig)
    ask_for_recovery(rig, "b@example.test")
    change_password(rig)
    change_password(rig, "sub-b")
    real = rig.admin.list_credentials

    def failing(subject: str) -> list[IdpCredential]:
        if subject == SUB:
            raise IdpAdminError("down")
        return real(subject)

    rig.admin.list_credentials = failing  # type: ignore[method-assign]
    rig.web.clock.now = NOW + TTL_SECONDS - 60  # long after the window: still not dropped
    caplog.set_level(logging.WARNING)
    check(rig)
    live = "SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL"
    assert rig.web.rows(live) == [(1,)]
    assert pending(rig) == [SUB]
    assert SUB not in caplog.text and EMAIL not in caplog.text
    rig.admin.list_credentials = real  # type: ignore[method-assign]
    check(rig)
    assert rig.web.rows(live) == [(0,)] and pending(rig) == []


def test_a_person_is_checked_until_the_link_and_its_form_are_dead_then_dropped(rig: Rig) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    settings = rig.web.runtime.settings
    window = settings.recovery_link_minutes * 60 + recovery.PENDING_CHECK_MARGIN_SECONDS
    assert window == 5400
    rig.admin.calls.clear()
    rig.web.clock.now = NOW + window - 1
    check(rig)
    assert pending(rig) == [SUB]
    rig.web.clock.now = NOW + window + 1
    check(rig)  # the last look
    assert pending(rig) == [] and rig.admin.calls.count("credentials") == 2
    check(rig)
    assert rig.admin.calls.count("credentials") == 2
    assert rig.web.runtime.markers and rig.web.runtime.markers.get(SUB)  # sign-ins still check


def test_a_newer_request_is_not_forgotten(rig: Rig) -> None:
    rig.login(sid="old")
    ask_for_recovery(rig)
    markers = rig.web.runtime.markers
    assert markers
    seen = markers.pending()[0][1]
    rig.web.clock.now = NOW + 120
    ask_for_recovery(rig)
    markers.forget_pending(SUB, seen)
    assert pending(rig) == [SUB]
    marker = markers.get(SUB)
    assert marker and marker.requested == NOW  # the earliest request is still the reference
    markers.forget_pending(SUB, NOW + 120)
    assert pending(rig) == []


def test_an_expired_marker_and_a_person_who_never_signed_in_cost_no_provider_call(
    rig: Rig,
) -> None:
    ask_for_recovery(rig)  # a real account that never used the application
    change_password(rig)
    rig.admin.calls.clear()
    check(rig)
    assert "credentials" not in rig.admin.calls and notices(rig) == []
    markers = rig.web.runtime.markers
    assert markers
    markers._client.delete(markers._key(SUB))
    check(rig)
    assert pending(rig) == []


def test_only_recovery_requests_are_checked_and_no_address_is_listed(rig: Rig) -> None:
    rig.login(sid="old")
    markers = rig.web.runtime.markers
    assert markers
    markers.record_change(SUB, CHANGED)  # a password change made inside the application
    assert pending(rig) == []
    ask_for_recovery(rig)
    stored = markers._client.zrange(markers._pending_key(), 0, -1)
    assert [m.decode() if isinstance(m, bytes) else m for m in stored] == [SUB]
    assert 0 < int(markers._client.ttl(markers._pending_key())) <= TTL_SECONDS


def test_a_stop_request_ends_the_check_between_people(rig: Rig) -> None:
    web = rig.login(sid="old")
    ask_for_recovery(rig)
    change_password(rig)
    check(rig, should_stop=lambda: True)
    assert alive(web)


# --- run by the worker ------------------------------------------------------------------------
def wait_for(condition: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.05)


def test_the_worker_runs_the_check_and_either_task_survives_the_others_failure(rig: Rig) -> None:
    runs: list[int] = []
    cycles: list[bool] = []

    def failing_check(should_stop: Callable[[], bool]) -> None:
        runs.append(1)
        raise RuntimeError("redis is away")

    worker = EmailChangeRecoveryWorker(
        factory(rig.web.env, "worker"),
        rig.admin,
        None,
        on_cycle=cycles.append,
        password_check=failing_check,
        interval_seconds=0.05,
    )
    worker.start()
    try:
        wait_for(lambda: len(runs) >= 2 and True in cycles)  # D37 stays healthy
    finally:
        assert worker.stop()
    with rig.web.env.admin_engine().connect() as db:
        db.exec_driver_sql(
            f'REVOKE SELECT ON email_change_operations FROM "{rig.web.env.names.worker}"'
        )
    runs.clear()
    cycles.clear()
    worker.start()
    try:
        wait_for(lambda: len(runs) >= 2 and len(cycles) >= 2)  # the check goes on
        assert not any(cycles)
    finally:
        worker.stop()


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_the_application_wires_the_check_into_its_worker(
    rig: Rig, redis_url: str, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    """The real factory: the first cycle after start-up ends the old session. Production ends
    sessions too but sends no mail (O15)."""
    from app.api.app import create_app_from_settings
    from app.core.config import Settings
    from fastapi.testclient import TestClient

    web = rig.login(sid="old")
    for key, value in {
        "AUTH_OIDC_ISSUER": "https://identity.example.test/realms/test",
        "AUTH_ADMIN_CLIENT_SECRET": "test-admin-secret",
        "AUTH_WEB_CLIENT_SECRET": "test-web-secret",
        "AUTH_SECURITY_HMAC_KEY": "k" * 32,
    }.items():
        monkeypatch.setenv(key, value)
    env = rig.web.env
    url = env.url("app")
    app = create_app_from_settings(
        Settings.model_validate(
            {
                "ENVIRONMENT": environment,
                "POSTGRES_HOST": url.host,
                "POSTGRES_PORT": url.port,
                "POSTGRES_DB": env.database,
                "POSTGRES_USER": env.names.app,
                "POSTGRES_PASSWORD": env.passwords["app"],
                "APP_DB_WORKER_USER": env.names.worker,
                "APP_DB_WORKER_PASSWORD": env.passwords["worker"],
                "REDIS_URL": redis_url,
            }
        )
    )
    runtime = app.state.auth
    markers = rig.web.runtime.markers
    assert markers and runtime.markers
    runtime.markers, runtime.admin, runtime.clock = markers, rig.admin, rig.web.clock
    runtime.notifier = rig.notifier
    ask_for_recovery(rig)
    change_password(rig)
    assert alive(web)
    live = "SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL"
    with TestClient(app):
        wait_for(lambda: rig.web.rows(live) == [(0,)])
    assert not alive(web)
    expected = [] if environment == "prod" else [NoticeKind.PASSWORD_RESET_COMPLETED]
    assert [kind for kind, _ in notices(rig)] == expected


def test_while_the_link_lives_pending_credential_setups_are_withdrawn(rig: Rig) -> None:
    """A set-up that became pending after the e-mail was sent would run for whoever follows it."""
    rig.login(sid="old")
    ask_for_recovery(rig)
    lifetime = rig.web.runtime.settings.recovery_link_minutes * 60
    rig.admin.pending[SUB] = ["CONFIGURE_RECOVERY_AUTHN_CODES", "VERIFY_EMAIL", "CONFIGURE_TOTP"]
    rig.web.clock.now = NOW + lifetime - 1
    check(rig)
    assert rig.admin.pending[SUB] == ["VERIFY_EMAIL"]
    rig.admin.pending[SUB] = ["CONFIGURE_TOTP"]
    rig.web.clock.now = NOW + lifetime + 1  # the link is dead: nothing can run it any more
    check(rig)
    assert rig.admin.pending[SUB] == ["CONFIGURE_TOTP"]
