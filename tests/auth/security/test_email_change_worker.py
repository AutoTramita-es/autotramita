"""D37 recovery worker on real PostgreSQL 16: concurrency, leases and fencing, interruptions,
restart, conflicts, manual review, independent notices and retention. A stateful fake identity
provider injects the external faults."""

from __future__ import annotations

import smtplib
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from app.auth.idp import IdpAdminError, IdpConflict, IdpEmailState
from app.auth.security import email_change, email_change_worker
from app.auth.security.email_change import claim_recovery, confirm_request, create_request
from app.auth.security.email_change_worker import (
    StaleLease,
    apply_claim,
    claim_notification,
    cleanup,
    deliver_notification,
    process_claim,
    run_once,
)
from app.auth.security.notify import Notice, SmtpNotifier
from app.auth.security.recovery_worker import INTERVAL_SECONDS, EmailChangeRecoveryWorker
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.auth.fake_admin import FakeAdmin
from tests.auth.security.test_security_units import settings
from tests.auth.sessions.test_sessions_db import factory, make_user, open_session, rows
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def confirmed(env: RoleEnv, admin: FakeAdmin, new: str = "new@example.test") -> UUID:
    """A person with two sessions and a confirmed request, ready for the worker."""
    user, subject = make_user(env)
    first = open_session(env, user)
    open_session(env, user)
    admin.add(f"{subject}@example.test", subject)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=first.session.id, new_email=new
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token)
    return operation


def claim(env: RoleEnv, **kw: Any) -> tuple[UUID, UUID] | None:
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        return claim_recovery(db, **kw)


def sql(env: RoleEnv, statement: str, **params: Any) -> None:
    with env.admin_engine().connect() as db:
        db.execute(text(statement), params)


def state(env: RoleEnv, operation: UUID) -> tuple[str, int]:
    found = rows(
        env, "SELECT status, attempts FROM email_change_operations WHERE id=:i", i=operation
    )
    return str(found[0][0]), int(found[0][1])


def jobs(env: RoleEnv) -> list[tuple[Any, ...]]:
    return rows(
        env,
        "SELECT recipient_kind, status, attempts, recipient FROM email_change_notifications "
        "ORDER BY recipient_kind",
    )


def due(env: RoleEnv) -> None:
    sql(env, "UPDATE email_change_operations SET next_attempt_at=now()")


class Gate(FakeAdmin):
    """The external write blocks until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def set_verified_email(self, subject: str, email: str) -> None:
        self.entered.set()
        assert self.release.wait(20)
        super().set_verified_email(subject, email)


class Sender(SmtpNotifier):
    def __init__(self, fail: Callable[[Notice], bool] = lambda notice: False) -> None:
        super().__init__(
            settings(
                AUTH_NOTIFY_MODE="smtp",
                AUTH_SMTP_HOST="localhost",
                AUTH_SMTP_FROM="security@example.test",
            )
        )
        self.fail = fail
        self.sent: list[tuple[str, UUID]] = []

    def send_durable(self, notice: Notice, job_id: UUID) -> None:
        if self.fail(notice):
            raise smtplib.SMTPException("unavailable")
        self.sent.append((notice.to, job_id))


# --- concurrency and fencing ------------------------------------------------------------------
def test_two_sweeps_at_once_apply_a_change_exactly_once(env: RoleEnv) -> None:
    admin = Gate()
    operation = confirmed(env, admin)
    sender = Sender()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_once, factory(env, "worker"), admin, sender)
        assert admin.entered.wait(10)
        second = pool.submit(run_once, factory(env, "worker"), admin, sender)
        second.result(timeout=15)  # finds the claim taken and returns without waiting
        admin.release.set()
        first.result(timeout=15)
    assert admin.calls.count("set_email") == 1
    assert state(env, operation) == ("COMPLETED", 1)
    assert [(j[0], j[1]) for j in jobs(env)] == [("NEW", "SENT"), ("OLD", "SENT")]
    assert len(sender.sent) == 2
    assert rows(env, "SELECT count(*) FROM audit_events WHERE action='identity.email.changed'") == [
        (1,)
    ]


def test_a_stale_lease_never_reaches_the_identity_provider(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    first = claim(env)
    second = claim(env, now=datetime.now(UTC) + timedelta(minutes=3))
    assert first and second and first[1] != second[1]
    with pytest.raises(StaleLease), session_scope(factory(env, "worker"), RequestContext()) as db:
        apply_claim(db, admin, *first)
    assert not process_claim(factory(env, "worker"), admin, *first)
    assert admin.calls == [] and state(env, operation)[0] == "APPLYING"
    assert process_claim(factory(env, "worker"), admin, *second)


def test_the_external_write_is_not_started_on_a_lease_about_to_end(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    sql(env, "UPDATE email_change_operations SET confirmed_at=now()-interval '5 minutes', "
             "next_attempt_at=now()-interval '5 minutes'")  # fmt: skip
    # thirty seconds of the lease remain: enough to read, not enough to write
    almost = datetime.now(UTC) - email_change.LEASE + timedelta(seconds=30)
    old = claim(env, now=almost)
    assert old is not None
    assert not process_claim(factory(env, "worker"), admin, *old)
    assert "email_state" in admin.calls and "set_email" not in admin.calls
    assert state(env, operation)[0] == "APPLYING"


def test_nobody_takes_over_while_the_external_call_is_in_flight(env: RoleEnv) -> None:
    admin = Gate()
    operation = confirmed(env, admin)
    first = claim(env)
    assert first is not None
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(process_claim, factory(env, "worker"), admin, *first)
        assert admin.entered.wait(10)
        # even a worker whose clock says the lease is long over skips the locked row
        assert claim(env, now=datetime.now(UTC) + timedelta(hours=1)) is None
        admin.release.set()
        assert running.result(timeout=15)
    assert state(env, operation) == ("COMPLETED", 1)


def test_a_lease_that_ends_during_the_call_forbids_the_local_commit(
    env: RoleEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(email_change, "LEASE", timedelta(seconds=2))
    monkeypatch.setattr(email_change_worker, "WRITE_MARGIN", timedelta(seconds=0))

    class Slow(FakeAdmin):
        def set_verified_email(self, subject: str, email: str) -> None:
            super().set_verified_email(subject, email)
            time.sleep(2.5)

    admin = Slow()
    operation = confirmed(env, admin)
    first = claim(env)
    assert first is not None
    assert not process_claim(factory(env, "worker"), admin, *first)
    assert state(env, operation)[0] == "APPLYING" and jobs(env) == []
    assert rows(env, "SELECT count(*) FROM audit_events WHERE action='identity.email.changed'") == [
        (0,)
    ]
    second = claim(env)
    assert second is not None and process_claim(factory(env, "worker"), admin, *second)
    assert admin.calls.count("set_email") == 1  # the retry read the provider and only finalised


# --- interruptions ----------------------------------------------------------------------------
def test_a_lost_database_connection_after_the_external_change_is_recovered(env: RoleEnv) -> None:
    class Killer(FakeAdmin):
        def set_verified_email(self, subject: str, email: str) -> None:
            super().set_verified_email(subject, email)
            sql(
                env,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND usename = :w",
                w=env.names.worker,
            )

    admin = Killer()
    operation = confirmed(env, admin)
    first = claim(env)
    assert first is not None
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        apply_claim(db, admin, *first)
    assert state(env, operation)[0] == "APPLYING" and jobs(env) == []
    second = claim(env, now=datetime.now(UTC) + timedelta(minutes=3))
    assert second is not None and process_claim(factory(env, "worker"), admin, *second)
    assert admin.calls.count("set_email") == 1 and state(env, operation)[0] == "COMPLETED"


def test_a_failure_before_the_external_change_is_retried_and_applied_once(env: RoleEnv) -> None:
    class Down(FakeAdmin):
        broken = True

        def get_email_state(self, subject: str) -> IdpEmailState:
            if self.broken:
                raise IdpAdminError("down")
            return super().get_email_state(subject)

    admin = Down()
    operation = confirmed(env, admin)
    run_once(factory(env, "worker"), admin, None)
    assert state(env, operation) == ("APPLYING", 1) and "set_email" not in admin.calls
    assert rows(
        env,
        "SELECT lease_id, next_attempt_at > now() + interval '20 seconds' "
        "FROM email_change_operations",
    ) == [(None, True)]  # released, with backoff
    admin.broken = False
    run_once(factory(env, "worker"), admin, None)  # not due yet
    assert state(env, operation) == ("APPLYING", 1)
    due(env)
    run_once(factory(env, "worker"), admin, None)
    assert state(env, operation) == ("COMPLETED", 2) and admin.calls.count("set_email") == 1


def test_one_failing_record_does_not_hold_back_the_others(env: RoleEnv) -> None:
    class Poison(FakeAdmin):
        bad: str = ""

        def get_email_state(self, subject: str) -> IdpEmailState:
            if subject == self.bad:
                raise RuntimeError("defect with somebody@example.test in its text")
            return super().get_email_state(subject)

    admin = Poison()
    bad = confirmed(env, admin, "bad@example.test")
    good = confirmed(env, admin, "good@example.test")
    admin.bad = str(
        rows(
            env,
            "SELECT u.auth_subject FROM users u JOIN email_change_operations o ON o.user_id=u.id "
            "WHERE o.id=:i",
            i=bad,
        )[0][0]
    )
    run_once(factory(env, "worker"), admin, None)
    assert state(env, good)[0] == "COMPLETED"
    assert state(env, bad) == ("APPLYING", 1)


def test_an_exhausted_record_does_not_end_the_sweep(env: RoleEnv) -> None:
    admin = FakeAdmin()
    exhausted = confirmed(env, admin, "old-one@example.test")
    waiting = confirmed(env, admin, "next-one@example.test")
    sql(
        env,
        "UPDATE email_change_operations SET status='APPLYING', attempts=10, "
        "next_attempt_at=now()-interval '1 hour' WHERE id=:i",
        i=exhausted,
    )
    sender = Sender()
    run_once(factory(env, "worker"), admin, sender)
    assert state(env, exhausted) == ("MANUAL_REVIEW", 10)
    assert state(env, waiting)[0] == "COMPLETED" and len(sender.sent) == 2


# --- conflicts and divergence end in manual review --------------------------------------------
def subject_of(env: RoleEnv, operation: UUID) -> str:
    return str(
        rows(
            env,
            "SELECT u.auth_subject FROM users u JOIN email_change_operations o ON o.user_id=u.id "
            "WHERE o.id=:i",
            i=operation,
        )[0][0]
    )


def assert_held(env: RoleEnv, admin: FakeAdmin, operation: UUID, *, writes: int = 0) -> None:
    run_once(factory(env, "worker"), admin, Sender())
    assert state(env, operation)[0] == "MANUAL_REVIEW"
    assert admin.calls.count("set_email") == writes and jobs(env) == []
    assert rows(env, "SELECT count(*) FROM users WHERE email_normalized='new@example.test'") == [
        (0,)
    ]
    assert rows(env, "SELECT count(*) FROM user_sessions WHERE revoked_at IS NOT NULL") == [(0,)]
    # unresolved: the addresses are kept, and the person cannot start a second change
    assert rows(env, "SELECT new_email IS NOT NULL FROM email_change_operations") == [(True,)]


def test_an_address_held_by_another_provider_account_is_never_taken(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    admin.add("new@example.test", "somebody-else")
    assert_held(env, admin, operation)


def test_a_conflict_reported_by_the_provider_is_held(env: RoleEnv) -> None:
    class Refusing(FakeAdmin):
        def set_verified_email(self, subject: str, email: str) -> None:
            self.calls.append("set_email")
            raise IdpConflict("conflict")

    admin = Refusing()
    operation = confirmed(env, admin)
    assert_held(env, admin, operation, writes=1)


def test_a_provider_address_that_is_neither_old_nor_new_is_held(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    subject = subject_of(env, operation)
    admin.users.clear()
    admin.add("changed-elsewhere@example.test", subject)
    assert_held(env, admin, operation)


def test_a_deactivated_person_is_held_before_the_provider_is_touched(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    sql(env, "UPDATE users SET status='DEACTIVATED'")
    run_once(factory(env, "worker"), admin, None)
    assert state(env, operation)[0] == "MANUAL_REVIEW" and admin.calls == []


def test_ten_failed_attempts_end_in_manual_review(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin)
    admin.down = True
    for _ in range(12):
        due(env)
        run_once(factory(env, "worker"), admin, None)
    assert state(env, operation) == ("MANUAL_REVIEW", 10)
    assert admin.calls.count("email_state") == 10


def test_backoff_doubles_up_to_an_hour_and_keeps_jitter() -> None:
    for attempts, ceiling in ((1, 60), (2, 120), (3, 240), (6, 1920), (7, 3600), (50, 3600)):
        seen = {email_change.retry_delay(attempts).total_seconds() for _ in range(200)}
        assert min(seen) >= ceiling // 2 and max(seen) <= ceiling
        assert len(seen) > 5


# --- the two durable notices ------------------------------------------------------------------
def test_each_notice_is_delivered_independently_and_survives_a_restart(env: RoleEnv) -> None:
    admin = FakeAdmin()
    confirmed(env, admin)
    first = Sender(fail=lambda notice: notice.to != "new@example.test")  # the old one fails
    run_once(factory(env, "worker"), admin, first)
    states = {j[0]: j[1:] for j in jobs(env)}
    assert states["NEW"] == ("SENT", 1, None)
    assert states["OLD"][:2] == ("PENDING", 1) and states["OLD"][2] is not None
    assert [to for to, _ in first.sent] == ["new@example.test"]
    sql(env, "UPDATE email_change_notifications SET next_attempt_at=now() WHERE status='PENDING'")
    restarted = Sender()  # a new process
    run_once(factory(env, "worker"), admin, restarted)
    assert {j[0]: j[1:] for j in jobs(env)}["OLD"] == ("SENT", 2, None)
    assert len(restarted.sent) == 1 and restarted.sent[0][0] != "new@example.test"


def test_a_crashed_delivery_is_claimed_again_after_its_lease(env: RoleEnv) -> None:
    admin = FakeAdmin()
    confirmed(env, admin)
    run_once(factory(env, "worker"), admin, None)
    sql(
        env,
        "UPDATE email_change_notifications SET next_attempt_at=now()+interval '1 day' "
        "WHERE recipient_kind='NEW'",
    )

    def claim_at(**kw: Any) -> tuple[UUID, UUID] | None:
        with session_scope(factory(env, "worker"), RequestContext()) as db:
            return claim_notification(db, **kw)

    lost = claim_at()  # the process dies holding it
    assert lost is not None and claim_at() is None
    again = claim_at(now=datetime.now(UTC) + timedelta(minutes=3))
    assert again is not None and again[0] == lost[0] and again[1] != lost[1]
    sender = Sender()
    assert not deliver_notification(factory(env, "worker"), sender, *lost)
    assert sender.sent == []  # the stale holder sends nothing
    assert deliver_notification(factory(env, "worker"), sender, *again)
    assert [job for _, job in sender.sent] == [lost[0]]


@pytest.mark.parametrize("limit", ["attempts", "age"])
def test_an_undeliverable_notice_ends_in_manual_review_and_keeps_its_recipient(
    env: RoleEnv, limit: str
) -> None:
    admin = FakeAdmin()
    confirmed(env, admin)
    broken = Sender(fail=lambda notice: True)
    run_once(factory(env, "worker"), admin, None)
    if limit == "age":
        sql(env, "UPDATE email_change_notifications SET created_at=now()-interval '24 hours'")
    for _ in range(12):
        sql(env, "UPDATE email_change_notifications SET next_attempt_at=now()")
        run_once(factory(env, "worker"), admin, broken)
    found = jobs(env)
    assert [j[1] for j in found] == ["MANUAL_REVIEW"] * 2
    assert [j[2] for j in found] == ([10, 10] if limit == "attempts" else [0, 0])
    assert all(j[3] for j in found)


def test_an_unexpected_delivery_error_keeps_the_job(env: RoleEnv) -> None:
    class Defective(Sender):
        def send_durable(self, notice: Notice, job_id: UUID) -> None:
            raise ValueError("defect")

    admin = FakeAdmin()
    confirmed(env, admin)
    run_once(factory(env, "worker"), admin, Defective())
    assert [j[1:3] for j in jobs(env)] == [("PENDING", 1)] * 2


# --- the periodic worker ----------------------------------------------------------------------
def wait_for(condition: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.05)


def test_the_periodic_worker_recovers_on_its_own_and_after_a_restart(env: RoleEnv) -> None:
    assert INTERVAL_SECONDS == 60
    admin = FakeAdmin()
    admin.down = True
    operation = confirmed(env, admin)
    cycles: list[bool] = []

    def build() -> EmailChangeRecoveryWorker:
        return EmailChangeRecoveryWorker(
            factory(env, "worker"), admin, Sender(), on_cycle=cycles.append, interval_seconds=0.1
        )

    worker = build()
    assert worker.interval_seconds == 0.1
    worker.start()
    try:
        wait_for(lambda: state(env, operation)[1] == 1)
        admin.down = False
        due(env)  # the backoff has passed; nothing calls the worker
        wait_for(lambda: state(env, operation)[0] == "COMPLETED")
        wait_for(lambda: [j[1] for j in jobs(env)] == ["SENT", "SENT"])
    finally:
        assert worker.stop()
    assert cycles[-1] is False and True in cycles  # closed again once stopped
    later = confirmed(env, admin, "after-restart@example.test")
    time.sleep(0.4)
    assert state(env, later)[0] == "CONFIRMED"  # a stopped worker does nothing
    restarted = build()
    restarted.start()
    try:
        wait_for(lambda: state(env, later)[0] == "COMPLETED")
    finally:
        assert restarted.stop()


def test_a_cycle_that_cannot_run_reports_not_ready_and_the_worker_goes_on(env: RoleEnv) -> None:
    cycles: list[bool] = []
    sql(env, f'REVOKE SELECT ON email_change_operations FROM "{env.names.worker}"')
    worker = EmailChangeRecoveryWorker(
        factory(env, "worker"), FakeAdmin(), None, on_cycle=cycles.append, interval_seconds=0.05
    )
    worker.start()
    try:
        wait_for(lambda: len(cycles) >= 3)
        assert not any(cycles)
        sql(env, f'GRANT SELECT ON email_change_operations TO "{env.names.worker}"')
        wait_for(lambda: True in cycles)
    finally:
        worker.stop()


# --- retention and minimisation ---------------------------------------------------------------
def age(env: RoleEnv, days: int) -> None:
    sql(env, "ALTER TABLE email_change_operations DISABLE TRIGGER email_change_guard")
    sql(
        env,
        "UPDATE email_change_operations SET updated_at = now() - make_interval(days => :d)",
        d=days,
    )
    sql(env, "ALTER TABLE email_change_operations ENABLE TRIGGER email_change_guard")
    sql(
        env,
        "UPDATE email_change_notifications SET sent_at = now() - make_interval(days => :d) "
        "WHERE status = 'SENT'",
        d=days,
    )


def sweep_cleanup(env: RoleEnv) -> None:
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        cleanup(db)


@pytest.mark.parametrize(("days", "kept"), [(29, True), (31, False)])
def test_resolved_records_are_removed_after_thirty_days(
    env: RoleEnv, days: int, kept: bool
) -> None:
    admin = FakeAdmin()
    confirmed(env, admin)
    run_once(factory(env, "worker"), admin, Sender())
    age(env, days)
    sweep_cleanup(env)
    expected = [(1,)] if kept else [(0,)]
    assert rows(env, "SELECT count(*) FROM email_change_operations") == expected
    assert rows(env, "SELECT count(*) FROM email_change_notifications") == (
        [(2,)] if kept else [(0,)]
    )


def test_unresolved_records_are_kept_however_old(env: RoleEnv) -> None:
    admin = FakeAdmin()
    held = confirmed(env, admin, "held@example.test")
    sql(env, "UPDATE email_change_operations SET status='MANUAL_REVIEW' WHERE id=:i", i=held)
    done = confirmed(env, admin, "done@example.test")
    run_once(factory(env, "worker"), admin, Sender(fail=lambda n: n.to != "done@example.test"))
    sql(env, "UPDATE email_change_notifications SET status='MANUAL_REVIEW' WHERE status='PENDING'")
    age(env, 400)
    sweep_cleanup(env)
    assert state(env, held)[0] == "MANUAL_REVIEW" and state(env, done)[0] == "COMPLETED"
    assert [j[:2] for j in jobs(env)] == [("OLD", "MANUAL_REVIEW")]


def test_addresses_of_a_replaced_request_are_dropped(env: RoleEnv) -> None:
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    for address in ("one@example.test", "two@example.test"):
        with session_scope(factory(env), RequestContext(user_id=user)) as db:
            create_request(db, user_id=user, session_id=session, new_email=address)
    sweep_cleanup(env)
    found = rows(
        env,
        "SELECT status, old_email IS NULL, new_email IS NULL, new_email_normalized "
        "FROM email_change_operations ORDER BY status",
    )
    assert found == [
        ("CANCELLED", True, True, None),
        ("PENDING", False, False, "two@example.test"),
    ]


# --- database privileges ----------------------------------------------------------------------
def test_parallel_requests_of_one_person_leave_one_active_request(env: RoleEnv) -> None:
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    barrier = threading.Barrier(4)

    def attempt(number: int) -> None:
        barrier.wait(timeout=10)
        with session_scope(factory(env), RequestContext(user_id=user)) as db:
            create_request(
                db, user_id=user, session_id=session, new_email=f"n{number}@example.test"
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(attempt, n) for n in range(4)]:
            future.result(timeout=20)
    assert rows(
        env, "SELECT status, count(*) FROM email_change_operations GROUP BY 1 ORDER BY 1"
    ) == [("CANCELLED", 3), ("PENDING", 1)]


def test_the_worker_cannot_confirm_or_reopen_a_request(env: RoleEnv) -> None:
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        create_request(db, user_id=user, session_id=session, new_email="x@example.test")
    forged = text(
        "UPDATE email_change_operations SET status='CONFIRMED', confirmed_at=now(), "
        "token_hash=NULL, token_issued_at=NULL, token_expires_at=NULL"
    )
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(forged)
    assert rows(env, "SELECT status FROM email_change_operations") == [("PENDING",)]


TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def table_privileges(env: RoleEnv, role: str, table: str) -> set[str]:
    query = "SELECT has_table_privilege(:r, :t, :p)"
    return {p for p in TABLE_PRIVILEGES if rows(env, query, r=role, t=table, p=p)[0][0]}


def column_privileges(env: RoleEnv, role: str, table: str, privilege: str) -> set[str]:
    query = (
        "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) AND attnum > 0 "
        "AND NOT attisdropped AND has_column_privilege(:r, attrelid, attnum, :p)"
    )
    return {str(r[0]) for r in rows(env, query, r=role, t=table, p=privilege)}


def test_effective_privileges_on_both_tables_are_exactly_these(env: RoleEnv) -> None:
    ops, notes = "email_change_operations", "email_change_notifications"
    app, worker, platform = env.names.app, env.names.worker, env.names.platform
    assert table_privileges(env, app, ops) == {"SELECT"}
    assert table_privileges(env, app, notes) == set()
    assert table_privileges(env, worker, ops) == {"SELECT", "DELETE"}
    assert table_privileges(env, worker, notes) == {"SELECT", "DELETE"}
    for name in (ops, notes):
        assert table_privileges(env, platform, name) == set()
        for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
            assert column_privileges(env, platform, name, privilege) == set()
        assert rows(
            env,
            "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
            "WHERE c.relname = :t AND a.grantee = 0",
            t=name,
        ) == [(0,)]
        assert rows(
            env,
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname = :t",
            t=name,
        ) == [(True,)]
    created = {"user_id", "session_id", "old_email", "new_email", "new_email_normalized"}
    token = {"token_hash", "token_issued_at", "token_expires_at"}
    assert column_privileges(env, app, ops, "INSERT") == created | token
    assert column_privileges(env, app, ops, "UPDATE") == token | {
        "status",
        "confirmed_at",
        "next_attempt_at",
    }
    assert column_privileges(env, app, notes, "INSERT") == set()
    assert column_privileges(env, app, notes, "UPDATE") == set()
    assert column_privileges(env, worker, ops, "INSERT") == set()
    immutable = {"id", "user_id", "session_id", "created_at"}
    assert not column_privileges(env, worker, ops, "UPDATE") & immutable
    assert column_privileges(env, worker, notes, "INSERT") == {
        "operation_id",
        "recipient_kind",
        "recipient",
    }
    # besides the status columns the worker may change only the e-mail columns of a person
    of_person = column_privileges(env, worker, "users", "UPDATE")
    assert {"email", "email_normalized", "email_verified_at"} <= of_person
    assert not of_person & {"auth_subject", "display_name", "id", "preferred_language"}
