"""F2-T04 / AC-USR-01..08: users on a real PostgreSQL 16 (disposable ``role_env`` database)."""

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from app.auth.errors import AccountConflict, InvalidStatusTransition
from app.auth.users.models import ALLOWED_TRANSITIONS, UserStatus
from app.auth.users.service import (
    Provisioned,
    change_status,
    provision_or_link,
    record_login,
)
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

S = UserStatus
SUB_A, SUB_B = "7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11", "0a1b2c3d-1111-4222-8333-444455556666"


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


class Revoker:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[uuid.UUID, str]] = []
        self.fail = fail

    def revoke_all(self, session: Session, user_id: uuid.UUID, *, reason: str) -> int:
        if self.fail:
            raise RuntimeError("session service down")
        self.calls.append((user_id, reason))
        return 1


def first_login(
    env: RoleEnv, subject: str = SUB_A, email: str = "Person@Example.test", verified: bool = True
) -> Provisioned:
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(auth_subject=subject)) as s:
        return provision_or_link(
            s, subject=subject, email=email, email_verified=verified, audit_factory=factory
        )


def admin_rows(env: RoleEnv, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    with env.admin_engine().connect() as c:
        return [tuple(r) for r in c.execute(text(sql), params)]


def raw_user(env: RoleEnv, status: S, subject: str | None = None) -> uuid.UUID:
    verified = "NULL" if status is S.PENDING_VERIFICATION else "now()"
    sub = subject or uuid.uuid4().hex
    with env.admin_engine().connect() as c:
        return uuid.UUID(
            str(
                c.execute(
                    text(
                        "INSERT INTO users (auth_subject, email, email_normalized, status, "
                        f"email_verified_at) VALUES (:s, :e, :e, :st, {verified}) RETURNING id"
                    ),
                    {"s": sub, "e": f"{sub}@example.test", "st": status.value},
                ).scalar_one()
            )
        )


def status_change(
    env: RoleEnv, user_id: uuid.UUID, new: S, revoker: Revoker, *, reason: str = "X", **kw: Any
) -> Any:
    return as_worker(
        env,
        lambda s: change_status(
            s, user_id=user_id, new_status=new, reason_code=reason, revoker=revoker, **kw
        ),
    )


def as_worker(env: RoleEnv, fn: Callable[[Session], Any]) -> Any:
    with session_scope(create_session_factory(env.engine("worker")), RequestContext()) as s:
        return fn(s)


# --- AC-USR-01 provisioning ---------------------------------------------------------------------
def test_first_login_creates_an_active_user_for_a_verified_email(env: RoleEnv) -> None:
    result = first_login(env)
    user = result.user
    assert result.created and user.status is S.ACTIVE and user.email_verified_at is not None
    assert (user.auth_subject, user.email, user.email_normalized) == (
        SUB_A, "Person@Example.test", "person@example.test")  # fmt: skip
    assert (user.preferred_language, user.version) == ("es", 1)
    events = admin_rows(env, "SELECT action, actor_user_id, subject_user_id FROM audit_events")
    assert events == [("identity.user.provisioned", user.id, user.id)]


def test_unverified_email_starts_pending_and_verification_activates_it(env: RoleEnv) -> None:
    pending = first_login(env, verified=False).user
    assert pending.status is S.PENDING_VERIFICATION and pending.email_verified_at is None
    again = first_login(env, verified=False)
    assert not again.created and again.user.status is S.PENDING_VERIFICATION
    verified = first_login(env, verified=True)
    assert not verified.created and verified.user.id == pending.id
    assert verified.user.status is S.ACTIVE and verified.user.email_verified_at is not None
    actions = [
        r[0] for r in admin_rows(env, "SELECT action FROM audit_events ORDER BY occurred_at")
    ]
    assert actions == ["identity.user.provisioned", "identity.email.verified"]


def test_returning_login_finds_the_same_user_and_records_the_time(env: RoleEnv) -> None:
    first = first_login(env).user
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(auth_subject=SUB_A)) as s:
        second = provision_or_link(
            s, subject=SUB_A, email="person@example.test", email_verified=True
        )
        record_login(s, second.user)
    assert not second.created and second.user.id == first.id
    assert admin_rows(env, "SELECT last_login_at IS NOT NULL, version FROM users") == [(True, 2)]


def test_verified_email_change_from_the_provider_is_applied_unverified_is_ignored(
    env: RoleEnv,
) -> None:
    user = first_login(env).user
    ignored = first_login(env, email="new@example.test", verified=False).user
    assert ignored.email_normalized == "person@example.test" and ignored.id == user.id
    changed = first_login(env, email="New@Example.test", verified=True).user
    assert changed.email == "New@Example.test" and changed.email_normalized == "new@example.test"
    email_events = admin_rows(
        env, "SELECT action FROM audit_events WHERE action LIKE 'identity.email%'"
    )
    assert email_events == [("identity.email.changed",)]


# --- AC-USR-02 concurrency ----------------------------------------------------------------------
def test_parallel_first_logins_of_one_subject_create_exactly_one_user(env: RoleEnv) -> None:
    workers, barrier = 6, threading.Barrier(6)
    results: list[Provisioned] = []
    errors: list[BaseException] = []

    def login() -> None:
        try:
            barrier.wait()
            results.append(first_login(env))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=login) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sum(r.created for r in results) == 1
    assert len({r.user.id for r in results}) == 1
    assert admin_rows(env, "SELECT count(*) FROM users") == [(1,)]
    provisioned = admin_rows(env, "SELECT count(*) FROM audit_events WHERE action = "
                                  "'identity.user.provisioned'")  # fmt: skip
    assert provisioned == [(1,)]


# --- AC-USR-03 e-mail conflict ------------------------------------------------------------------
def test_same_email_under_another_subject_is_a_conflict_never_a_merge(env: RoleEnv) -> None:
    first = first_login(env).user
    with pytest.raises(AccountConflict) as caught:
        first_login(env, subject=SUB_B, email="PERSON@example.TEST")
    assert (caught.value.status, caught.value.code) == (409, "ACCOUNT_CONFLICT")
    assert admin_rows(env, "SELECT id, auth_subject FROM users") == [(first.id, SUB_A)]
    attempts = admin_rows(env, "SELECT action, outcome, details::text, subject_user_id FROM "
                               "audit_events WHERE action = 'identity.link.conflict'")  # fmt: skip
    assert attempts == [("identity.link.conflict", "DENIED", "{}", None)]  # kept; no e-mail in it


def test_a_provider_side_email_change_onto_somebody_elses_address_is_a_conflict(
    env: RoleEnv,
) -> None:
    first_login(env, subject=SUB_A, email="a@example.test")
    second = first_login(env, subject=SUB_B, email="b@example.test").user
    with pytest.raises(AccountConflict):
        first_login(env, subject=SUB_B, email="a@example.test", verified=True)
    assert admin_rows(env, "SELECT email FROM users WHERE id = :i", i=second.id) == [
        ("b@example.test",)]  # fmt: skip


# --- AC-USR-04 constraints ----------------------------------------------------------------------
def test_unique_subject_and_email_and_immutable_subject(env: RoleEnv) -> None:
    uid = raw_user(env, S.ACTIVE, subject="dup-sub")
    with env.admin_engine().connect() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status, "
                           "email_verified_at) VALUES ('dup-sub', 'x@y.zz', 'x@y.zz', "
                           "'ACTIVE', now())"))  # fmt: skip
        with pytest.raises(IntegrityError):
            c.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status, "
                           "email_verified_at) VALUES ('other', 'dup-sub@example.test', "
                           "'dup-sub@example.test', 'ACTIVE', now())"))  # fmt: skip
        with pytest.raises(IntegrityError, match="immutable"):
            c.execute(text("UPDATE users SET auth_subject = 'changed' WHERE id = :i"), {"i": uid})
        with pytest.raises(IntegrityError, match="immutable"):
            c.execute(text("UPDATE users SET id = gen_random_uuid() WHERE id = :i"), {"i": uid})


def test_active_requires_a_verified_email_and_rows_are_never_deleted(env: RoleEnv) -> None:
    with env.admin_engine().connect() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status) "
                           "VALUES ('u1', 'u1@x.zz', 'u1@x.zz', 'ACTIVE')"))  # fmt: skip
        raw_user(env, S.ACTIVE)
        for sql in ("DELETE FROM users", "TRUNCATE users, user_sessions"):
            with pytest.raises(DBAPIError, match="never deleted"):
                c.execute(text(sql))


@pytest.mark.parametrize("pair", sorted((a, b) for a in S for b in S if a is not b))
def test_database_status_transitions_match_the_model(env: RoleEnv, pair: tuple[S, S]) -> None:
    source, target = pair
    uid = raw_user(env, source)
    # PENDING -> ACTIVE by status alone is refused (no verified e-mail); verification is the way.
    allowed = pair in ALLOWED_TRANSITIONS and pair != (S.PENDING_VERIFICATION, S.ACTIVE)
    with env.admin_engine().connect() as c:
        statement = text("UPDATE users SET status = :t WHERE id = :i")
        if allowed:
            c.execute(statement, {"t": target.value, "i": uid})
            assert (
                c.execute(text("SELECT status FROM users WHERE id = :i"), {"i": uid}).scalar_one()
                == target.value
            )
        else:
            with pytest.raises(IntegrityError):
                c.execute(statement, {"t": target.value, "i": uid})


# --- AC-USR-06 privileges -----------------------------------------------------------------------
def test_application_role_cannot_change_status_but_can_edit_its_profile(env: RoleEnv) -> None:
    user = first_login(env).user
    factory = create_session_factory(env.engine("app"))
    with pytest.raises(DBAPIError), session_scope(factory, RequestContext(user_id=user.id)) as s:
        s.execute(text("UPDATE users SET status = 'BLOCKED' WHERE id = :i"), {"i": user.id})
    with pytest.raises(DBAPIError), session_scope(factory, RequestContext(user_id=user.id)) as s:
        s.execute(text("UPDATE users SET status_reason = 'X' WHERE id = :i"), {"i": user.id})
    with session_scope(factory, RequestContext(user_id=user.id)) as s:
        s.execute(text("UPDATE users SET display_name = 'Ana', version = version + 1 "
                       "WHERE id = :i"), {"i": user.id})  # fmt: skip
    assert admin_rows(env, "SELECT status, display_name FROM users") == [("ACTIVE", "Ana")]


def test_nobody_can_delete_and_platform_has_no_access_until_its_grants_exist(env: RoleEnv) -> None:
    first_login(env)
    for kind in ("app", "worker", "platform"):
        with env.engine(kind).connect() as c, pytest.raises(DBAPIError):
            c.execute(text("DELETE FROM users"))
    with env.engine("platform").connect() as c, pytest.raises(DBAPIError):
        c.execute(text("SELECT count(*) FROM users"))  # F2-T10 adds the grant-based policy
    with env.engine("platform").connect() as c, pytest.raises(DBAPIError):
        c.execute(text("UPDATE users SET status = 'BLOCKED'"))


def test_worker_may_change_status_but_nothing_else(env: RoleEnv) -> None:
    user = first_login(env).user
    factory = create_session_factory(env.engine("worker"))
    with session_scope(factory, RequestContext()) as s:
        s.execute(text("UPDATE users SET status = 'DEACTIVATED', version = version + 1 "
                       "WHERE id = :i"), {"i": user.id})  # fmt: skip
    for sql in ("UPDATE users SET email = 'x@y.zz'", "UPDATE users SET display_name = 'X'",
                "UPDATE users SET auth_subject = 'x'"):  # fmt: skip
        with pytest.raises(DBAPIError), session_scope(factory, RequestContext()) as s:
            s.execute(text(sql))


# --- AC-USR-07 row-level security ---------------------------------------------------------------
def test_rls_a_person_sees_only_the_own_row_and_cannot_forge_or_touch_others(env: RoleEnv) -> None:
    a = first_login(env, SUB_A, "a@example.test").user
    b = first_login(env, SUB_B, "b@example.test").user
    factory = create_session_factory(env.engine("app"))

    def visible(context: RequestContext) -> list[uuid.UUID]:
        with session_scope(factory, context) as s:
            return [r[0] for r in s.execute(text("SELECT id FROM users"))]

    assert visible(RequestContext()) == []
    assert visible(RequestContext(user_id=a.id)) == [a.id]
    assert visible(RequestContext(user_id=b.id)) == [b.id]
    assert visible(RequestContext(auth_subject=SUB_B)) == [b.id]
    assert visible(RequestContext(auth_subject="unknown")) == []
    assert visible(RequestContext(tenant_id=uuid.uuid4())) == []  # tenant context grants nothing
    with session_scope(factory, RequestContext(user_id=a.id)) as s:  # a cannot change b
        result: Any = s.execute(
            text("UPDATE users SET display_name = 'hacked', version = version + 1 WHERE id = :i"),
            {"i": b.id},
        )
        touched = result.rowcount
    assert touched == 0
    with (
        pytest.raises(DBAPIError),
        session_scope(factory, RequestContext(auth_subject="mine")) as s,
    ):
        s.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status, "
                       "email_verified_at) VALUES ('someone-else', 'z@z.zz', 'z@z.zz', 'ACTIVE', "
                       "now())"))  # fmt: skip
    with (
        pytest.raises(DBAPIError),
        session_scope(factory, RequestContext(auth_subject="mine")) as s,
    ):
        s.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status, "
                       "email_verified_at, status_changed_by) VALUES ('mine', 'm@z.zz', 'm@z.zz', "
                       "'ACTIVE', now(), gen_random_uuid())"))  # fmt: skip
    with (
        pytest.raises(DBAPIError),
        session_scope(factory, RequestContext(auth_subject="mine")) as s,
    ):
        s.execute(text("INSERT INTO users (auth_subject, email, email_normalized, status, "
                       "email_verified_at) VALUES ('mine', 'm@z.zz', 'm@z.zz', 'BLOCKED', "
                       "now())"))  # fmt: skip
    assert admin_rows(env, "SELECT count(*) FROM users") == [(2,)]


# --- AC-USR-08 schema ---------------------------------------------------------------------------
def test_users_carry_no_tenant_customer_role_or_membership_columns(env: RoleEnv) -> None:
    columns = {r[0] for r in admin_rows(env, "SELECT column_name FROM information_schema.columns "
                                             "WHERE table_name = 'users'")}  # fmt: skip
    assert columns == {
        "id", "auth_subject", "email", "email_normalized", "email_verified_at", "status",
        "status_reason", "status_changed_at", "status_changed_by", "display_name",
        "preferred_language", "last_login_at", "created_at", "updated_at", "version",
    }  # fmt: skip
    for forbidden in ("tenant", "customer", "role", "member", "branch", "nif", "phone"):
        assert not any(forbidden in c for c in columns), forbidden
    assert admin_rows(env, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'users'::regclass "
                           "AND contype = 'f'") == [(0,)]  # fmt: skip


# --- status service -----------------------------------------------------------------------------
def test_deactivation_revokes_sessions_in_the_same_transaction_and_is_audited(env: RoleEnv) -> None:
    user = first_login(env).user
    revoker = Revoker()
    updated = status_change(env, user.id, S.DEACTIVATED, revoker, reason="ADMIN_REQUEST")
    assert updated.status is S.DEACTIVATED and updated.status_reason == "ADMIN_REQUEST"
    assert revoker.calls == [(user.id, "ACCOUNT_DEACTIVATED")]
    row = admin_rows(
        env,
        "SELECT action, actor_type, subject_user_id FROM audit_events "
        "WHERE action = 'identity.user.deactivated'",
    )
    assert row == [("identity.user.deactivated", "SYSTEM", user.id)]
    # no-op when already there; leaving BLOCKED needs the privileged flag; nonsense is refused
    assert status_change(env, user.id, S.DEACTIVATED, revoker).version == updated.version
    status_change(env, user.id, S.BLOCKED, revoker, reason="SECURITY")
    assert revoker.calls[-1] == (user.id, "ACCOUNT_BLOCKED")
    with pytest.raises(InvalidStatusTransition):
        status_change(env, user.id, S.ACTIVE, revoker)
    back = status_change(env, user.id, S.ACTIVE, revoker, reason="REVIEWED", privileged=True)
    assert back.status is S.ACTIVE
    with pytest.raises(InvalidStatusTransition):  # unknown id looks like an invalid change
        status_change(env, uuid.uuid4(), S.BLOCKED, revoker)


def test_status_change_is_atomic_with_session_revocation(env: RoleEnv) -> None:
    user = first_login(env).user
    with pytest.raises(RuntimeError):
        status_change(env, user.id, S.BLOCKED, Revoker(fail=True), reason="SECURITY")
    assert admin_rows(env, "SELECT status FROM users") == [("ACTIVE",)]
    changes = admin_rows(
        env,
        "SELECT count(*) FROM audit_events WHERE action LIKE 'identity.user.%' "
        "AND action <> 'identity.user.provisioned'",
    )
    assert changes == [(0,)]


# --- concurrency: deactivation versus sign-in (D16) ---------------------------------------------
def test_a_sign_in_waits_for_a_concurrent_deactivation_and_then_sees_it(env: RoleEnv) -> None:
    user = first_login(env).user
    locked, release = threading.Event(), threading.Event()
    outcome: dict[str, Any] = {}

    def deactivate() -> None:
        def work(s: Session) -> None:
            change_status(
                s, user_id=user.id, new_status=S.DEACTIVATED, reason_code="ADMIN", revoker=Revoker()
            )
            locked.set()  # the row is locked and changed but not yet committed
            assert release.wait(10)

        as_worker(env, work)

    def sign_in() -> None:
        outcome["user"] = first_login(env).user

    t1 = threading.Thread(target=deactivate)
    t1.start()
    assert locked.wait(10)
    t2 = threading.Thread(target=sign_in)
    t2.start()
    t2.join(timeout=1.0)
    assert t2.is_alive(), "the sign-in must wait for the deactivation to commit"
    release.set()
    t1.join(10)
    t2.join(10)
    assert outcome["user"].status is S.DEACTIVATED
