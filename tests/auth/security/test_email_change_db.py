"""D37 foundation: exercise real PostgreSQL constraints and role isolation."""

import uuid

import pytest
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.auth.sessions.test_sessions_db import factory, make_user, open_session
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def insert_change(env: RoleEnv, user: uuid.UUID, session: uuid.UUID, address: str) -> uuid.UUID:
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        value = db.execute(
            text("""
                INSERT INTO email_change_operations
                  (user_id, session_id, old_email, new_email, new_email_normalized,
                   token_hash, token_issued_at, token_expires_at)
                VALUES (:u, :s, 'old@example.test', :e, :e, :h, now(),
                        now() + interval '30 minutes') RETURNING id
            """),
            {"u": user, "s": session, "e": address, "h": bytes(32)},
        ).scalar_one()
        return uuid.UUID(str(value))


def test_one_active_operation_and_reserved_address(env: RoleEnv) -> None:
    a, _ = make_user(env)
    b, _ = make_user(env)
    sa, sb = open_session(env, a).session.id, open_session(env, b).session.id
    operation = insert_change(env, a, sa, "new@example.test")
    with pytest.raises(IntegrityError):
        insert_change(env, a, sa, "different@example.test")
    with pytest.raises(IntegrityError):
        insert_change(env, b, sb, "new@example.test")
    with session_scope(factory(env), RequestContext(user_id=a)) as db:
        db.execute(
            text("""
            UPDATE email_change_operations SET status = 'CANCELLED', token_hash = NULL,
                token_issued_at = NULL, token_expires_at = NULL WHERE id = :id
        """),
            {"id": operation},
        )
    insert_change(env, b, sb, "new@example.test")


def test_ownership_state_and_token_constraints(env: RoleEnv) -> None:
    a, _ = make_user(env)
    b, _ = make_user(env)
    sa, sb = open_session(env, a).session.id, open_session(env, b).session.id
    operation = insert_change(env, a, sa, "a-new@example.test")
    with session_scope(factory(env), RequestContext(user_id=b)) as db:
        assert db.execute(text("SELECT id FROM email_change_operations")).all() == []
        updated = db.execute(text("UPDATE email_change_operations SET status = 'PENDING'"))
        assert updated.rowcount == 0  # type: ignore[attr-defined]
    with pytest.raises(DBAPIError):
        insert_change(env, b, sa, "forged@example.test")
    with pytest.raises(DBAPIError), session_scope(factory(env), RequestContext(user_id=a)) as db:
        db.execute(
            text("UPDATE email_change_operations SET status = 'COMPLETED' WHERE id = :id"),
            {"id": operation},
        )
    with pytest.raises(DBAPIError), session_scope(factory(env), RequestContext(user_id=a)) as db:
        db.execute(
            text("UPDATE email_change_operations SET token_expires_at = now() WHERE id = :id"),
            {"id": operation},
        )
    insert_change(env, b, sb, "b-new@example.test")


def test_worker_and_platform_privileges(env: RoleEnv) -> None:
    user, _ = make_user(env)
    operation = insert_change(env, user, open_session(env, user).session.id, "x@example.test")
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert db.execute(text("SELECT id FROM email_change_operations")).scalar_one() == operation
        assert db.execute(text("DELETE FROM email_change_operations")).rowcount == 0  # type: ignore[attr-defined]
    for kind, table in (
        ("platform", "email_change_operations"),
        ("app", "email_change_notifications"),
    ):
        with pytest.raises(DBAPIError), session_scope(factory(env, kind), RequestContext()) as db:
            db.execute(text(f"SELECT * FROM {table}"))


def test_confirmation_consumes_token_and_addresses_are_immutable(env: RoleEnv) -> None:
    user, _ = make_user(env)
    operation = insert_change(env, user, open_session(env, user).session.id, "new@example.test")
    with pytest.raises(DBAPIError), session_scope(factory(env), RequestContext(user_id=user)) as db:
        db.execute(
            text("""
            UPDATE email_change_operations SET status='CONFIRMED', confirmed_at=now()
            WHERE id=:id
        """),
            {"id": operation},
        )  # token must be removed when confirming
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        db.execute(
            text("""
            UPDATE email_change_operations SET status='CONFIRMED', confirmed_at=now(),
                token_hash=NULL, token_issued_at=NULL, token_expires_at=NULL WHERE id=:id
        """),
            {"id": operation},
        )
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(
            text("""
            UPDATE email_change_operations SET new_email='attacker@example.test' WHERE id=:id
        """),
            {"id": operation},
        )


def test_notification_jobs_are_independent_and_unique(env: RoleEnv) -> None:
    user, _ = make_user(env)
    operation = insert_change(env, user, open_session(env, user).session.id, "new@example.test")
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        db.execute(
            text("""
            UPDATE email_change_operations SET status='CONFIRMED', confirmed_at=now(),
                token_hash=NULL, token_issued_at=NULL, token_expires_at=NULL WHERE id=:id
        """),
            {"id": operation},
        )
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(
            text("UPDATE email_change_operations SET status='APPLYING' WHERE id=:id"),
            {"id": operation},
        )
        db.execute(
            text("""UPDATE email_change_operations SET status='COMPLETED',
            completed_at=now() WHERE id=:id"""),
            {"id": operation},
        )
        for kind in ("OLD", "NEW"):
            db.execute(
                text("""
                INSERT INTO email_change_notifications (operation_id, recipient_kind, recipient)
                VALUES (:id, :kind, 'recipient@example.test')
            """),
                {"id": operation, "kind": kind},
            )
    with (
        pytest.raises(IntegrityError),
        session_scope(factory(env, "worker"), RequestContext()) as db,
    ):
        db.execute(
            text("""
            INSERT INTO email_change_notifications (operation_id, recipient_kind, recipient)
            VALUES (:id, 'OLD', 'recipient@example.test')
        """),
            {"id": operation},
        )


def test_concurrent_requests_reserve_the_address_once(env: RoleEnv) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    a, _ = make_user(env)
    b, _ = make_user(env)
    sa, sb = open_session(env, a).session.id, open_session(env, b).session.id
    barrier = Barrier(2)

    def attempt(user: uuid.UUID, session: uuid.UUID) -> str:
        barrier.wait(timeout=10)
        try:
            insert_change(env, user, session, "shared@example.test")
        except IntegrityError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(attempt, a, sa), pool.submit(attempt, b, sb))
        assert sorted(future.result(timeout=15) for future in futures) == ["conflict", "created"]


def test_request_reissue_expiry_replay_and_user_binding(env: RoleEnv) -> None:
    from datetime import UTC, datetime, timedelta

    from app.auth.security.email_change import confirm_request, create_request

    now = datetime.now(UTC)
    a, _ = make_user(env)
    b, _ = make_user(env)
    sa = open_session(env, a).session.id
    with session_scope(factory(env), RequestContext(user_id=a)) as db:
        old_id, old_token = create_request(
            db, user_id=a, session_id=sa, new_email="one@example.test", now=now
        )
    with session_scope(factory(env), RequestContext(user_id=a)) as db:
        new_id, token = create_request(
            db, user_id=a, session_id=sa, new_email="two@example.test", now=now
        )
    assert new_id != old_id and token != old_token
    with session_scope(factory(env), RequestContext(user_id=a)) as db:
        assert not confirm_request(db, user_id=a, operation_id=old_id, token=old_token, now=now)
        assert not confirm_request(
            db, user_id=a, operation_id=new_id, token=token, now=now + timedelta(minutes=30)
        )
    with session_scope(factory(env), RequestContext(user_id=b)) as db:
        assert not confirm_request(db, user_id=b, operation_id=new_id, token=token, now=now)
    with session_scope(factory(env), RequestContext(user_id=a)) as db:
        assert confirm_request(db, user_id=a, operation_id=new_id, token=token, now=now)
        assert not confirm_request(db, user_id=a, operation_id=new_id, token=token, now=now)
    with env.admin_engine().connect() as c:
        row = c.execute(
            text("SELECT status, token_hash FROM email_change_operations WHERE id=:id"),
            {"id": new_id},
        ).one()
        assert row.status == "CONFIRMED" and row.token_hash is None


def test_concurrent_confirmation_consumes_token_once(env: RoleEnv) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.auth.security.email_change import confirm_request, create_request

    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test"
        )
    barrier = Barrier(2)

    def attempt() -> bool:
        barrier.wait(timeout=10)
        with session_scope(factory(env), RequestContext(user_id=user)) as db:
            return confirm_request(db, user_id=user, operation_id=operation, token=token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(attempt), pool.submit(attempt))
        assert sorted(future.result(timeout=15) for future in futures) == [False, True]


def test_recovery_lease_expiry_fences_the_old_worker(env: RoleEnv) -> None:
    from datetime import UTC, datetime, timedelta

    from app.auth.security.email_change import (
        claim_recovery,
        confirm_request,
        create_request,
        release_recovery,
    )

    now = datetime.now(UTC)
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test", now=now
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token, now=now)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        first = claim_recovery(db, now=now)
    assert first is not None and first[0] == operation
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert claim_recovery(db, now=now) is None
    later = now + timedelta(minutes=2, seconds=1)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        second = claim_recovery(db, now=later)
    assert second is not None and second[1] != first[1]
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert not release_recovery(
            db, operation_id=operation, lease_id=first[1], retry_at=later, now=later
        )
        assert release_recovery(
            db,
            operation_id=operation,
            lease_id=second[1],
            retry_at=later + timedelta(minutes=1),
            now=later,
        )


def test_recovery_retries_end_in_manual_review(env: RoleEnv) -> None:
    from datetime import UTC, datetime, timedelta

    from app.auth.security.email_change import (
        claim_recovery,
        confirm_request,
        create_request,
        release_recovery,
    )

    now = datetime.now(UTC)
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test", now=now
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token, now=now)
    for attempt in range(10):
        moment = now + timedelta(minutes=attempt)
        with session_scope(factory(env, "worker"), RequestContext()) as db:
            claim = claim_recovery(db, now=moment)
        assert claim is not None and claim[0] == operation
        with session_scope(factory(env, "worker"), RequestContext()) as db:
            assert release_recovery(
                db,
                operation_id=operation,
                lease_id=claim[1],
                retry_at=moment + timedelta(seconds=1),
                now=moment,
            )
    with env.admin_engine().connect() as c:
        status, attempts = c.execute(
            text("SELECT status, attempts FROM email_change_operations WHERE id=:id"),
            {"id": operation},
        ).one()
    assert (status, attempts) == ("MANUAL_REVIEW", 10)


def test_competing_recovery_workers_only_one_claims(env: RoleEnv) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.auth.security.email_change import claim_recovery, confirm_request, create_request

    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test"
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token)
    barrier = Barrier(2)

    def attempt() -> tuple[uuid.UUID, uuid.UUID] | None:
        barrier.wait(timeout=10)
        with session_scope(factory(env, "worker"), RequestContext()) as db:
            return claim_recovery(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(attempt), pool.submit(attempt))
        claims = [future.result(timeout=15) for future in futures]
    assert sum(claim is not None for claim in claims) == 1


def test_recovery_after_24_hours_moves_to_manual_review(env: RoleEnv) -> None:
    from datetime import UTC, datetime, timedelta

    from app.auth.security.email_change import claim_recovery, confirm_request, create_request

    now = datetime.now(UTC)
    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test", now=now
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token, now=now)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert claim_recovery(db, now=now + timedelta(hours=24)) is None
    with env.admin_engine().connect() as db:
        assert (
            db.execute(
                text("SELECT status FROM email_change_operations WHERE id=:id"), {"id": operation}
            ).scalar_one()
            == "MANUAL_REVIEW"
        )


def test_sign_in_does_not_bypass_pending_email_recovery(env: RoleEnv) -> None:
    from app.auth.errors import IdentityProviderUnavailable
    from app.auth.users.service import provision_or_link

    user, subject = make_user(env)
    session = open_session(env, user).session.id
    insert_change(env, user, session, "new@example.test")
    with (
        pytest.raises(IdentityProviderUnavailable),
        session_scope(factory(env), RequestContext(auth_subject=subject)) as db,
    ):
        provision_or_link(db, subject=subject, email="new@example.test", email_verified=True)
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            != "new@example.test"
        )


def test_worker_email_update_requires_matching_unexpired_lease(env: RoleEnv) -> None:
    from app.auth.security.email_change import claim_recovery, confirm_request, create_request

    user, _ = make_user(env)
    session = open_session(env, user).session.id
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        operation, token = create_request(
            db, user_id=user, session_id=session, new_email="new@example.test"
        )
        assert confirm_request(db, user_id=user, operation_id=operation, token=token)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        claim = claim_recovery(db)
    assert claim is not None
    update = text("""
        UPDATE users SET email='new@example.test', email_normalized='new@example.test',
            email_verified_at=now() WHERE id=:id
    """)
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(update, {"id": user})
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(
            text("SELECT set_config('app.email_change_lease', :lease, true)"),
            {"lease": str(claim[1])},
        )
        db.execute(update, {"id": user})
    with env.admin_engine().connect() as db:
        assert (
            db.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user}).scalar_one()
            == "new@example.test"
        )
