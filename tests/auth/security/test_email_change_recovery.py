"""D37 recovery against real PostgreSQL; a stateful IdP simulates external faults."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.auth.idp import IdpAdminError
from app.auth.security.email_change import claim_recovery, confirm_request, create_request
from app.auth.security.email_change_worker import process_claim
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from tests.auth.fake_admin import FakeAdmin
from tests.auth.sessions.test_sessions_db import factory, make_user, open_session
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def prepare(env: RoleEnv, admin: FakeAdmin) -> tuple[UUID, tuple[UUID, UUID]]:
    user, subject = make_user(env)
    first = open_session(env, user)
    open_session(env, user)
    with env.admin_engine().connect() as db:
        old = db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
    admin.add(old, subject)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=first.session.id, new_email="new@example.test"
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        claim = claim_recovery(db)
    assert claim is not None
    return user, claim


def test_recovery_atomically_updates_user_sessions_audit_and_two_jobs(env: RoleEnv) -> None:
    admin = FakeAdmin()
    user, claim = prepare(env, admin)
    operation, lease = claim
    assert process_claim(factory(env, "worker"), admin, operation, lease)
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            == "new@example.test"
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM user_sessions WHERE user_id=:id AND revoked_at IS NOT NULL"
                ),
                {"id": user},
            ).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text("SELECT status FROM email_change_operations WHERE id=:id"), {"id": operation}
            ).scalar_one()
            == "COMPLETED"
        )
        assert db.execute(
            text("SELECT recipient_kind FROM email_change_notifications ORDER BY recipient_kind")
        ).scalars().all() == ["NEW", "OLD"]
        audit = db.execute(
            text("SELECT details::text FROM audit_events WHERE action='identity.email.changed'")
        ).scalar_one()
        assert "@" not in audit


def test_timeout_after_idp_update_recovers_without_repeating_update(env: RoleEnv) -> None:
    class TimeoutAfterUpdate(FakeAdmin):
        def set_verified_email(self, subject: str, email: str) -> None:
            super().set_verified_email(subject, email)
            raise IdpAdminError("timeout")

    admin = TimeoutAfterUpdate()
    user, claim = prepare(env, admin)
    operation, lease = claim
    assert not process_claim(factory(env, "worker"), admin, operation, lease)
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            != "new@example.test"
        )
        assert db.execute(text("SELECT count(*) FROM email_change_notifications")).scalar_one() == 0
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        second = claim_recovery(session, now=datetime.now(UTC) + timedelta(hours=2))
    assert second is not None
    assert process_claim(factory(env, "worker"), admin, *second)
    assert admin.calls.count("set_email") == 1


def test_notification_failure_is_durable_and_retried_with_same_id(env: RoleEnv) -> None:
    import smtplib

    from app.auth.security.email_change_worker import claim_notification, deliver_notification
    from app.auth.security.notify import Notice, SmtpNotifier
    from tests.auth.security.test_security_units import settings

    class Sender(SmtpNotifier):
        def __init__(self) -> None:
            super().__init__(
                settings(
                    AUTH_NOTIFY_MODE="smtp",
                    AUTH_SMTP_HOST="localhost",
                    AUTH_SMTP_FROM="security@example.test",
                )
            )
            self.ids: list[UUID] = []

        def send_durable(self, notice: Notice, job_id: UUID) -> None:
            self.ids.append(job_id)
            if len(self.ids) == 1:
                raise smtplib.SMTPException("down")

    admin = FakeAdmin()
    _, claim = prepare(env, admin)
    assert process_claim(factory(env, "worker"), admin, *claim)
    sender = Sender()
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        job = claim_notification(session)
    assert job is not None
    assert not deliver_notification(factory(env, "worker"), sender, *job)
    with env.admin_engine().connect() as db:
        assert (
            db.execute(
                text("SELECT status FROM email_change_notifications WHERE id=:id"), {"id": job[0]}
            ).scalar_one()
            == "PENDING"
        )
    # No other job may mask the retry in this test: defer its next attempt.
    with env.admin_engine().connect() as db:
        db.execute(
            text(
                "UPDATE email_change_notifications SET next_attempt_at=now()+interval '1 day' WHERE id<>:id"
            ),
            {"id": job[0]},
        )
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        retry = claim_notification(session, now=datetime.now(UTC) + timedelta(hours=2))
    assert retry is not None and retry[0] == job[0]
    assert deliver_notification(factory(env, "worker"), sender, *retry)
    assert sender.ids == [job[0], job[0]]
    with env.admin_engine().connect() as db:
        row = db.execute(
            text("SELECT status, recipient FROM email_change_notifications WHERE id=:id"),
            {"id": job[0]},
        ).one()
        assert tuple(row) == ("SENT", None)


def test_crash_before_local_commit_recovers_from_actual_idp_state(env: RoleEnv) -> None:
    from app.auth.security.email_change_worker import apply_claim

    admin = FakeAdmin()
    user, claim = prepare(env, admin)
    with pytest.raises(RuntimeError), session_scope(factory(env, "worker"), RequestContext()) as db:
        apply_claim(db, admin, *claim)
        raise RuntimeError("simulated process loss before commit")
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            != "new@example.test"
        )
        assert db.execute(text("SELECT count(*) FROM email_change_notifications")).scalar_one() == 0
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        replacement = claim_recovery(session, now=datetime.now(UTC) + timedelta(minutes=3))
    assert replacement is not None
    assert process_claim(factory(env, "worker"), admin, *replacement)
    assert admin.calls.count("set_email") == 1


def test_old_verified_token_cannot_restore_previous_email(env: RoleEnv) -> None:
    from app.auth.errors import IdentityProviderUnavailable
    from app.auth.users.service import provision_or_link

    admin = FakeAdmin()
    user, claim = prepare(env, admin)
    with env.admin_engine().connect() as db:
        old, subject = db.execute(
            text("SELECT email, auth_subject FROM users WHERE id=:id"), {"id": user}
        ).one()
    old_issued_at = int(datetime.now(UTC).timestamp())
    assert process_claim(factory(env, "worker"), admin, *claim)
    with (
        pytest.raises(IdentityProviderUnavailable),
        session_scope(factory(env), RequestContext(auth_subject=subject)) as session,
    ):
        provision_or_link(
            session, subject=subject, email=old, email_verified=True, token_issued_at=old_issued_at
        )
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            == "new@example.test"
        )


def test_disabled_mail_retains_both_jobs_without_consuming_attempts(env: RoleEnv) -> None:
    from app.auth.security.email_change_worker import run_once

    admin = FakeAdmin()
    _, claim = prepare(env, admin)
    assert process_claim(factory(env, "worker"), admin, *claim)
    run_once(factory(env, "worker"), admin, None)
    with env.admin_engine().connect() as db:
        rows = db.execute(text("SELECT status, attempts FROM email_change_notifications")).all()
    assert rows == [("PENDING", 0), ("PENDING", 0)]


def test_cleanup_expires_pending_tokens_and_purges_resolved_records(env: RoleEnv) -> None:
    from app.auth.security.email_change_worker import cleanup

    admin = FakeAdmin()
    _, claim = prepare(env, admin)
    assert process_claim(factory(env, "worker"), admin, *claim)
    user, _ = make_user(env)
    session_id = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as session:
        expired, _ = create_request(
            session,
            user_id=user,
            session_id=session_id,
            new_email="expired@example.test",
            now=datetime.now(UTC) - timedelta(minutes=31),
        )
    with env.admin_engine().connect() as db:
        db.execute(
            text("""UPDATE email_change_notifications SET status='SENT', recipient=NULL,
                         sent_at=now()-interval '31 days'""")
        )
        db.execute(text("ALTER TABLE email_change_operations DISABLE TRIGGER email_change_guard"))
        try:
            db.execute(
                text("""UPDATE email_change_operations SET updated_at=now()-interval '31 days'
                             WHERE status='COMPLETED'""")
            )
        finally:
            db.execute(
                text("ALTER TABLE email_change_operations ENABLE TRIGGER email_change_guard")
            )
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        cleanup(session)
    with env.admin_engine().connect() as db:
        row = db.execute(
            text("""SELECT status, token_hash, old_email, new_email FROM
                              email_change_operations WHERE id=:id"""),
            {"id": expired},
        ).one()
        assert tuple(row) == ("EXPIRED", None, None, None)
        assert db.execute(text("SELECT count(*) FROM email_change_notifications")).scalar_one() == 0
        assert (
            db.execute(
                text("SELECT count(*) FROM email_change_operations WHERE status='COMPLETED'")
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_periodic_worker_starts_fail_closed_in_production(
    env: RoleEnv, redis_url: str, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    import time

    from app.api.app import create_app_from_settings
    from app.core.config import Settings
    from fastapi.testclient import TestClient

    for key, value in {
        "AUTH_OIDC_ISSUER": "https://identity.example.test/realms/test",
        "AUTH_ADMIN_CLIENT_SECRET": "test-admin-secret",
        "AUTH_WEB_CLIENT_SECRET": "test-web-secret",
        "AUTH_SECURITY_HMAC_KEY": "x" * 32,
        "AUTH_WEB_ORIGIN": "https://app.example.test",
        "AUTH_NOTIFY_MODE": "smtp",
        "AUTH_SMTP_HOST": "127.0.0.1",
        "AUTH_SMTP_FROM": "security@example.test",
    }.items():
        monkeypatch.setenv(key, value)
    url = env.url("app")
    settings = Settings.model_validate(
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
    app = create_app_from_settings(settings)
    with TestClient(app):
        deadline = time.monotonic() + 5
        while (
            environment == "test"
            and not app.state.auth.email_change_ready
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert app.state.auth.email_change_ready is (environment == "test")


def test_real_smtp_sink_recovers_after_outage(env: RoleEnv) -> None:
    import socket
    import threading

    from app.auth.security.email_change_worker import claim_notification, deliver_notification
    from app.auth.security.notify import SmtpNotifier
    from tests.auth.security.test_security_units import settings
    from tests.identity.kc import SmtpSink, _SmtpHandler, _ThreadedTcp

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    admin = FakeAdmin()
    _, operation = prepare(env, admin)
    assert process_claim(factory(env, "worker"), admin, *operation)
    notifier = SmtpNotifier(
        settings(
            AUTH_NOTIFY_MODE="smtp",
            AUTH_SMTP_HOST="127.0.0.1",
            AUTH_SMTP_PORT=port,
            AUTH_SMTP_FROM="security@example.test",
        )
    )
    with session_scope(factory(env, "worker"), RequestContext()) as session:
        claim = claim_notification(session)
    assert claim is not None and not deliver_notification(factory(env, "worker"), notifier, *claim)
    with env.admin_engine().connect() as db:
        recipient = db.execute(
            text("SELECT recipient FROM email_change_notifications WHERE id=:id"), {"id": claim[0]}
        ).scalar_one()
        db.execute(
            text(
                "UPDATE email_change_notifications SET next_attempt_at=now()+interval '1 day' WHERE id<>:id"
            ),
            {"id": claim[0]},
        )
    sink = SmtpSink()
    server = _ThreadedTcp(("127.0.0.1", port), _SmtpHandler)
    server.sink = sink  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with session_scope(factory(env, "worker"), RequestContext()) as session:
            retry = claim_notification(session, now=datetime.now(UTC) + timedelta(hours=2))
        assert retry is not None and retry[0] == claim[0]
        assert deliver_notification(factory(env, "worker"), notifier, *retry)
        assert sink.for_recipient(recipient, wait=2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
