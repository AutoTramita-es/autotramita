"""F2-T05 / AC-SES-01..12: application sessions on a real PostgreSQL 16 (disposable database).
Time is passed explicitly, so no test sleeps to make a session expire."""

import dataclasses
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.auth import credentials
from app.auth.errors import (
    AccountDisabled,
    SessionExpired,
    SessionRequired,
    SessionRevoked,
    SessionSecurityViolation,
)
from app.auth.sessions import service as sessions
from app.auth.sessions.models import AuthLevel, ClientType, RevokeReason, SessionPolicy
from app.auth.sessions.service import CreatedSession, DatabaseSessionRevoker, Resolved
from app.auth.settings import AuthSettings
from app.auth.tokens import VerifiedToken
from app.auth.users.models import UserStatus
from app.auth.users.service import SessionRevoker, change_status
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
POLICY = SessionPolicy.from_settings(
    AuthSettings.model_validate({"AUTH_OIDC_ISSUER": "https://auth.test.invalid/realms/x"})
)
WEB, MOBILE = ClientType.WEB, ClientType.MOBILE


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def make_user(env: RoleEnv, status: str = "ACTIVE") -> tuple[uuid.UUID, str]:
    subject = uuid.uuid4().hex
    verified = "NULL" if status == "PENDING_VERIFICATION" else "now()"
    with env.admin_engine().connect() as c:
        uid = c.execute(
            text(
                "INSERT INTO users (auth_subject, email, email_normalized, status, "
                f"email_verified_at) VALUES (:s, :e, :e, :st, {verified}) RETURNING id"
            ),
            {"s": subject, "e": f"{subject}@example.test", "st": status},
        ).scalar_one()
    return uuid.UUID(str(uid)), subject


def factory(env: RoleEnv, kind: str = "app") -> Any:
    return create_session_factory(env.engine(kind))


def open_session(
    env: RoleEnv,
    user_id: uuid.UUID,
    *,
    client: ClientType = WEB,
    kc: str | None = None,
    policy: SessionPolicy = POLICY,
    now: datetime = T0,
    **kw: Any,
) -> CreatedSession:
    with session_scope(factory(env), RequestContext(user_id=user_id)) as db:
        return sessions.create_session(
            db, user_id=user_id, client_type=client, kc_session_id=kc or uuid.uuid4().hex,
            auth_time=now, policy=policy, now=now, **kw,
        )  # fmt: skip


def resolve(env: RoleEnv, secret: str, **kw: Any) -> Resolved:
    lock = kw.pop("lock", False)
    kw.setdefault("now", T0)
    with session_scope(factory(env), RequestContext()) as db:
        return sessions.resolve_web(db, secret, lock=lock, **kw)


def rows(env: RoleEnv, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    with env.admin_engine().connect() as c:
        return [tuple(r) for r in c.execute(text(sql), params)]


def as_worker(env: RoleEnv, fn: Callable[[Session], Any]) -> Any:
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        return fn(db)


def live_count(env: RoleEnv, user_id: uuid.UUID) -> int:
    return int(
        rows(env, "SELECT count(*) FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL",
             u=user_id)[0][0]
    )  # fmt: skip


# --- AC-SES-01 only the hash is stored -----------------------------------------------------------
def test_database_holds_only_the_hash_and_logs_never_show_the_secret(
    env: RoleEnv, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    user, _ = make_user(env)
    created = open_session(env, user)
    secret = created.credential
    assert secret is not None and credentials.is_well_formed(secret)
    assert bytes(rows(env, "SELECT credential_hash FROM user_sessions")[0][0]) == (
        credentials.hash_credential(secret)
    )
    dump = rows(env, "SELECT row_to_json(s)::text FROM user_sessions s")[0][0]
    assert secret not in dump and secret not in caplog.text
    resolved = resolve(env, secret)
    assert resolved.session.id == created.session.id and resolved.user.id == user
    assert secret not in caplog.text


# --- AC-SES-02 liveness and lifetimes ------------------------------------------------------------
def test_idle_deadline_is_exclusive_and_lifetimes_follow_the_client_type(env: RoleEnv) -> None:
    user, _ = make_user(env)
    web = open_session(env, user)
    admin = open_session(env, user, client=ClientType.ADMIN_WEB)
    mobile = open_session(env, user, client=MOBILE)
    assert web.session.idle_expires_at - T0 == timedelta(minutes=30)
    assert web.session.absolute_expires_at - T0 == timedelta(hours=12)
    assert admin.session.idle_expires_at - T0 == timedelta(minutes=15)
    assert admin.session.absolute_expires_at - T0 == timedelta(hours=8)
    assert mobile.session.idle_expires_at - T0 == timedelta(days=7)
    assert mobile.session.absolute_expires_at - T0 == timedelta(days=30)
    assert mobile.credential is None and web.credential and admin.credential
    secret = web.credential
    assert resolve(env, secret, now=T0 + timedelta(minutes=29, seconds=59)).session.is_live(
        T0 + timedelta(minutes=29, seconds=59))  # fmt: skip
    with pytest.raises(SessionExpired) as caught:
        resolve(env, secret, now=T0 + timedelta(minutes=30))
    assert (caught.value.status, caught.value.code) == (401, "SESSION_EXPIRED")


def test_absolute_deadline_wins_over_a_long_idle_deadline(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    secret = created.credential
    assert secret
    with env.admin_engine().connect() as c:  # push the idle deadline up to the absolute one
        c.execute(text("UPDATE user_sessions SET idle_expires_at = absolute_expires_at"))
    last_ok = T0 + timedelta(hours=12) - timedelta(seconds=1)
    assert resolve(env, secret, now=last_ok)
    with pytest.raises(SessionExpired):
        resolve(env, secret, now=T0 + timedelta(hours=12))


def test_expiry_needs_no_cleanup_job_and_unknown_or_malformed_credentials_are_rejected(
    env: RoleEnv,
) -> None:
    user, _ = make_user(env)
    open_session(env, user)
    for bad in (None, "", "x" * 43, "short", 42):
        with pytest.raises(SessionRequired) as caught:
            resolve(env, bad)  # type: ignore[arg-type]
        assert (caught.value.status, caught.value.code) == (401, "SESSION_REQUIRED")


# --- AC-SES-09 activity throttle -----------------------------------------------------------------
def test_touch_is_throttled_extends_idle_and_never_passes_the_absolute_deadline(
    env: RoleEnv,
) -> None:
    user, _ = make_user(env)
    short = dataclasses.replace(POLICY, absolute={**POLICY.absolute, WEB: timedelta(hours=1)})
    created = open_session(env, user, policy=short)
    assert created.credential
    f = factory(env)
    resolved = resolve(env, created.credential, now=T0 + timedelta(seconds=30))
    assert sessions.touch(f, resolved, short, now=T0 + timedelta(seconds=30)) is False  # < 60 s
    assert sessions.touch(f, resolved, short, now=T0 + timedelta(seconds=61)) is True
    stored = rows(env, "SELECT last_activity_at, idle_expires_at FROM user_sessions")[0]
    assert stored == (T0 + timedelta(seconds=61), T0 + timedelta(seconds=61, minutes=30))
    for minute in (25, 40):  # keep the session busy; the second touch would pass 1 h
        at = T0 + timedelta(minutes=minute)
        assert sessions.touch(f, resolve(env, created.credential, now=at), short, now=at) is True
    capped = rows(env, "SELECT idle_expires_at = absolute_expires_at FROM user_sessions")[0][0]
    assert capped is True  # 40 min + 30 min idle would pass the 1 h absolute deadline


def test_touch_skips_a_row_that_is_locked_instead_of_waiting(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    assert created.credential
    resolved = resolve(env, created.credential)
    locked, release = threading.Event(), threading.Event()

    def hold() -> None:
        with session_scope(factory(env), RequestContext()) as db:
            sessions.resolve_web(
                db, created.credential, lock=True, now=T0
            )  # FOR SHARE, uncommitted
            locked.set()
            assert release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(10)
    try:
        later = T0 + timedelta(minutes=5)
        assert sessions.touch(factory(env), resolved, POLICY, now=later) is False
    finally:
        release.set()
        holder.join(10)
    assert sessions.touch(factory(env), resolved, POLICY, now=T0 + timedelta(minutes=5)) is True


# --- AC-SES-03 revocation takes effect on the next request ----------------------------------------
def test_single_other_and_all_revocation(env: RoleEnv) -> None:
    user, _ = make_user(env)
    stranger, _ = make_user(env)
    a, b, c = (open_session(env, user) for _ in range(3))
    outsider = open_session(env, stranger)
    assert a.credential and b.credential and c.credential and outsider.credential
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        assert sessions.revoke(db, a.session.id, reason=RevokeReason.LOGOUT, actor_user_id=user)
    with pytest.raises(SessionRevoked) as caught:
        resolve(env, a.credential)
    assert (caught.value.status, caught.value.code) == (401, "SESSION_REVOKED")
    assert resolve(env, b.credential) and resolve(env, c.credential)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        assert sessions.revoke_others(db, user, c.session.id, actor_user_id=user) == 1
    with pytest.raises(SessionRevoked):
        resolve(env, b.credential)
    assert resolve(env, c.credential)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        revoker = DatabaseSessionRevoker()
        assert revoker.revoke_all(db, user, reason="USER_REVOKED", actor_user_id=user) == 1
    with pytest.raises(SessionRevoked):
        resolve(env, c.credential)
    assert resolve(env, outsider.credential)  # another person's session is untouched
    reasons = rows(env, "SELECT revoked_reason FROM user_sessions WHERE user_id = :u", u=user)
    assert sorted(r[0] for r in reasons) == ["LOGOUT", "USER_REVOKED", "USER_REVOKED"]
    audited = rows(
        env,
        "SELECT action, details->>'count' FROM audit_events WHERE action = 'session.revoked'",
    )
    assert [r[1] for r in audited] == ["1", "1", "1"]


def test_revoking_twice_is_harmless(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        assert sessions.revoke(db, created.session.id, reason=RevokeReason.LOGOUT)
        assert sessions.revoke(db, created.session.id, reason=RevokeReason.LOGOUT) is False


# --- AC-SES-04 deactivation ----------------------------------------------------------------------
def test_deactivation_revokes_every_session_in_its_own_transaction(env: RoleEnv) -> None:
    user, _ = make_user(env)
    secrets = [open_session(env, user).credential for _ in range(3)]
    revoker: SessionRevoker = DatabaseSessionRevoker()  # also checks the protocol is satisfied
    as_worker(env, lambda db: change_status(db, user_id=user, new_status=UserStatus.DEACTIVATED,
                                            reason_code="ADMIN", revoker=revoker))  # fmt: skip
    for secret in secrets:
        assert secret
        with pytest.raises(SessionRevoked):
            resolve(env, secret)
    assert live_count(env, user) == 0
    reasons = rows(env, "SELECT DISTINCT revoked_reason FROM user_sessions")
    assert reasons == [("ACCOUNT_DEACTIVATED",)]
    with pytest.raises(AccountDisabled):
        open_session(env, user)


def test_the_database_refuses_sessions_for_disabled_users(env: RoleEnv) -> None:
    user, _ = make_user(env, "BLOCKED")
    insert = text(
        "INSERT INTO user_sessions (user_id, client_type, credential_hash, kc_session_id, "
        "auth_time, idle_expires_at, absolute_expires_at, created_at) VALUES (:u, 'WEB', "
        "decode(repeat('ab', 32), 'hex'), 'kc', now(), now() + interval '1 hour', "
        "now() + interval '2 hours', now())"
    )
    with pytest.raises(DBAPIError), session_scope(factory(env), RequestContext(user_id=user)) as db:
        db.execute(insert, {"u": user})
    pending, _ = make_user(env, "PENDING_VERIFICATION")  # may sign in, with limited access
    assert open_session(env, pending).session.user_id == pending


def test_a_sign_in_cannot_slip_past_a_concurrent_deactivation(env: RoleEnv) -> None:
    user, _ = make_user(env)
    locked, release = threading.Event(), threading.Event()
    outcome: dict[str, BaseException | CreatedSession] = {}

    def deactivate() -> None:
        def work(db: Session) -> None:
            change_status(db, user_id=user, new_status=UserStatus.DEACTIVATED, reason_code="ADMIN",
                          revoker=DatabaseSessionRevoker())  # fmt: skip
            locked.set()
            assert release.wait(10)

        as_worker(env, work)

    def sign_in() -> None:
        try:
            outcome["session"] = open_session(env, user)
        except BaseException as exc:
            outcome["error"] = exc

    t1 = threading.Thread(target=deactivate)
    t1.start()
    assert locked.wait(10)
    t2 = threading.Thread(target=sign_in)
    t2.start()
    t2.join(1.0)
    assert t2.is_alive(), "creating a session must wait for the deactivation to commit"
    release.set()
    t1.join(10)
    t2.join(10)
    assert isinstance(outcome.get("error"), AccountDisabled), outcome
    assert live_count(env, user) == 0


# --- AC-SES-05 revocation versus a request in flight --------------------------------------------
def test_revocation_waits_for_a_request_in_flight_and_every_later_request_sees_it(
    env: RoleEnv,
) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    assert created.credential
    started, release = threading.Event(), threading.Event()
    revoked_at: list[float] = []
    committed_at: list[float] = []
    import time

    def request_in_flight() -> None:
        with session_scope(factory(env), RequestContext()) as db:
            sessions.resolve_web(db, created.credential, lock=True, now=T0)
            started.set()
            assert release.wait(10)
            committed_at.append(time.monotonic())  # the request finishes before the revoke

    def revoke() -> None:
        with session_scope(factory(env), RequestContext(user_id=user)) as db:
            sessions.revoke(db, created.session.id, reason=RevokeReason.USER_REVOKED)
        revoked_at.append(time.monotonic())

    t1 = threading.Thread(target=request_in_flight)
    t1.start()
    assert started.wait(10)
    t2 = threading.Thread(target=revoke)
    t2.start()
    t2.join(1.0)
    assert t2.is_alive(), "the revocation must wait for the request that holds the row"
    release.set()
    t1.join(10)
    t2.join(10)
    assert revoked_at and committed_at and revoked_at[0] >= committed_at[0]
    with pytest.raises(SessionRevoked):
        resolve(env, created.credential, lock=True)


# --- AC-SES-06 session cap -----------------------------------------------------------------------
def test_the_oldest_live_sessions_are_evicted_beyond_the_cap(env: RoleEnv) -> None:
    user, _ = make_user(env)
    cap3 = dataclasses.replace(POLICY, max_sessions=3)
    opened = [open_session(env, user, policy=cap3, now=T0 + timedelta(minutes=i)) for i in range(5)]
    assert live_count(env, user) == 3
    fate = rows(
        env,
        "SELECT revoked_reason FROM user_sessions WHERE user_id = :u ORDER BY created_at",
        u=user,
    )
    assert [r[0] for r in fate] == ["SESSION_LIMIT", "SESSION_LIMIT", None, None, None]
    evicted = opened[0].credential
    assert evicted
    with pytest.raises(SessionRevoked):
        resolve(env, evicted, now=T0 + timedelta(minutes=5))


def test_parallel_sign_ins_never_exceed_the_cap(env: RoleEnv) -> None:
    user, _ = make_user(env)
    cap3 = dataclasses.replace(POLICY, max_sessions=3)
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def sign_in(n: int) -> None:
        try:
            barrier.wait()
            open_session(env, user, policy=cap3, now=T0 + timedelta(seconds=n))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=sign_in, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert live_count(env, user) == 3
    assert rows(env, "SELECT count(*) FROM user_sessions")[0][0] == workers


# --- AC-SES-07 row-level security and privileges -------------------------------------------------
def test_people_cannot_see_or_revoke_each_others_sessions(env: RoleEnv) -> None:
    a, _ = make_user(env)
    b, _ = make_user(env)
    mine = open_session(env, a)
    assert mine.credential
    f = factory(env)

    def visible(context: RequestContext) -> int:
        with session_scope(f, context) as db:
            return int(db.execute(text("SELECT count(*) FROM user_sessions")).scalar_one())

    assert visible(RequestContext()) == 0
    assert visible(RequestContext(user_id=a)) == 1
    assert visible(RequestContext(user_id=b)) == 0
    assert visible(RequestContext(tenant_id=uuid.uuid4())) == 0
    assert visible(RequestContext(session_hash=credentials.hash_credential(mine.credential))) == 1
    assert visible(RequestContext(session_hash=bytes(32))) == 0
    with session_scope(f, RequestContext(user_id=b)) as db:
        assert sessions.revoke(db, mine.session.id, reason=RevokeReason.ADMIN_REVOKED) is False
    assert live_count(env, a) == 1
    forged = text(
        "INSERT INTO user_sessions (user_id, client_type, credential_hash, kc_session_id, "
        "auth_time, idle_expires_at, absolute_expires_at) VALUES (:u, 'WEB', "
        "decode(repeat('cd', 32), 'hex'), 'x', now(), now() + interval '1 hour', "
        "now() + interval '2 hours')"
    )
    with pytest.raises(DBAPIError), session_scope(f, RequestContext(user_id=b)) as db:
        db.execute(forged, {"u": a})  # a session for somebody else is refused


def test_privileges_per_role(env: RoleEnv) -> None:
    user, _ = make_user(env)
    open_session(env, user)
    for kind in ("app", "worker", "platform"):
        with env.engine(kind).connect() as c, pytest.raises(DBAPIError):
            c.execute(text("DELETE FROM user_sessions"))
    with session_scope(factory(env, "platform"), RequestContext(user_id=user)) as db:
        # F2-T10: only through PLATFORM_USER_ADMIN (0010); without it no row, not even its own
        assert db.execute(text("SELECT count(*) FROM user_sessions")).scalar_one() == 0
    with env.engine("platform").connect() as c, pytest.raises(DBAPIError):
        c.execute(text("UPDATE user_sessions SET context_version = 9"))  # revocation columns only
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(text("UPDATE user_sessions SET context_version = 9"))
    with pytest.raises(DBAPIError), session_scope(factory(env, "worker"), RequestContext()) as db:
        db.execute(text("INSERT INTO user_sessions DEFAULT VALUES"))
    for column in ("user_id", "client_type", "absolute_expires_at", "kc_session_id", "created_at"):
        with (
            pytest.raises(DBAPIError),
            session_scope(factory(env), RequestContext(user_id=user)) as db,
        ):
            db.execute(text(f"UPDATE user_sessions SET {column} = {column}"))


# --- AC-SES-08 immutability ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "assignment",
    ["user_id = gen_random_uuid()", "client_type = 'ADMIN_WEB'",
     "absolute_expires_at = absolute_expires_at + interval '1 day'", "kc_session_id = 'other'",
     "created_at = now()", "credential_hash = NULL", "context_version = 0"],
)  # fmt: skip
def test_the_database_keeps_immutable_columns_immutable_even_for_a_superuser(
    env: RoleEnv, assignment: str
) -> None:
    user, _ = make_user(env)
    open_session(env, user)
    with env.admin_engine().connect() as c, pytest.raises((IntegrityError, DBAPIError)):
        c.execute(text(f"UPDATE user_sessions SET {assignment}"))


def test_a_revoked_session_is_final_and_nothing_is_ever_deleted(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        sessions.revoke(db, created.session.id, reason=RevokeReason.LOGOUT)
    with env.admin_engine().connect() as c:
        with pytest.raises(IntegrityError, match="final"):
            c.execute(text("UPDATE user_sessions SET last_activity_at = now()"))
        with pytest.raises(IntegrityError, match="final"):
            c.execute(text("UPDATE user_sessions SET revoked_reason = 'ADMIN_REVOKED'"))
        for sql in ("DELETE FROM user_sessions", "TRUNCATE user_sessions"):
            with pytest.raises(
                DBAPIError, match=r"never deleted|cannot truncate a table referenced"
            ):
                c.execute(text(sql))


# --- AC-SES-10 theft signals ---------------------------------------------------------------------
def test_a_changed_browser_family_revokes_the_session_through_its_own_transaction(
    env: RoleEnv,
) -> None:
    user, _ = make_user(env)
    created = open_session(env, user, ua_family="Chrome")
    assert created.credential
    with pytest.raises(SessionSecurityViolation) as caught:
        resolve(env, created.credential, ua_family="Firefox")
    assert caught.value.signal == "UA_CHANGE"
    assert live_count(env, user) == 1  # the failed request rolled back; nothing persisted yet
    assert sessions.revoke_independent(factory(env), caught.value) is True
    with pytest.raises(SessionRevoked):
        resolve(env, created.credential, ua_family="Chrome")
    assert rows(env, "SELECT revoked_reason FROM user_sessions") == [("SECURITY_POLICY",)]
    events = rows(env, "SELECT action, outcome, details->>'signal' FROM audit_events "
                       "WHERE action = 'session.theft_suspected'")  # fmt: skip
    assert events == [("session.theft_suspected", "DENIED", "UA_CHANGE")]


def test_same_browser_family_and_a_missing_user_agent_are_not_suspicious(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user, ua_family="Chrome")
    assert created.credential
    assert resolve(env, created.credential, ua_family="Chrome").country_changed is False
    assert resolve(env, created.credential, ua_family=None)


def test_a_new_country_is_flagged_and_audited_but_does_not_revoke(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user, country_code="ES")
    assert created.credential
    assert resolve(env, created.credential, country_code="ES").country_changed is False
    flagged = resolve(env, created.credential, country_code="DE")
    assert flagged.country_changed is True and flagged.session.is_live(T0)
    signals = rows(env, "SELECT details->>'signal' FROM audit_events "
                        "WHERE action = 'session.theft_suspected'")  # fmt: skip
    assert signals == [("COUNTRY_CHANGE",)]
    assert resolve(env, created.credential)  # still usable


# --- AC-SES-11 rotation and step-up --------------------------------------------------------------
def test_rotation_invalidates_the_old_credential_at_once(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    old = created.credential
    assert old
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        new = sessions.rotate_credential(db, created.session.id)
    assert new != old and credentials.is_well_formed(new)
    with pytest.raises(SessionRequired):
        resolve(env, old)
    assert resolve(env, new).session.id == created.session.id
    assert open_session(env, user).credential != new  # every sign-in gets a fresh credential


def test_step_up_records_the_level_and_rotates_web_credentials_only(env: RoleEnv) -> None:
    user, _ = make_user(env)
    web = open_session(env, user)
    mobile = open_session(env, user, client=MOBILE, kc="kc-mobile")
    assert web.credential
    with session_scope(factory(env), RequestContext(user_id=user)) as db:
        new = sessions.record_step_up(db, web.session.id, level=AuthLevel.LOA2, rotate=True,
                                      now=T0 + timedelta(minutes=1))  # fmt: skip
        none = sessions.record_step_up(db, mobile.session.id, level=AuthLevel.LOA2, rotate=False,
                                       now=T0 + timedelta(minutes=1))  # fmt: skip
    assert new and none is None
    with pytest.raises(SessionRequired):
        resolve(env, web.credential)
    stepped = resolve(env, new).session
    assert stepped.auth_level is AuthLevel.LOA2 and stepped.step_up_at == T0 + timedelta(minutes=1)


# --- mobile --------------------------------------------------------------------------------------
def verified(subject: str, sid: str) -> VerifiedToken:
    return VerifiedToken(
        subject=subject, session_id=sid, client_id="at-mobile", issued_at=0, expires_at=1,
        auth_time=None, acr=None, email=None, email_verified=None,
    )  # fmt: skip


def resolve_mobile(env: RoleEnv, token: VerifiedToken, **kw: Any) -> Resolved:
    kw.setdefault("now", T0)
    with session_scope(factory(env), RequestContext()) as db:
        return sessions.resolve_mobile(db, token, **kw)


def test_mobile_sessions_resolve_by_subject_and_keycloak_session(env: RoleEnv) -> None:
    user, subject = make_user(env)
    other, other_subject = make_user(env)
    open_session(env, user, client=MOBILE, kc="kc-m-1")
    resolved = resolve_mobile(env, verified(subject, "kc-m-1"), now=T0)
    assert resolved.session.client_type is MOBILE and resolved.user.id == user
    with pytest.raises(SessionRequired):
        resolve_mobile(env, verified(subject, "kc-unknown"))
    with pytest.raises(SessionRequired):  # another person's token cannot reach this session
        resolve_mobile(env, verified(other_subject, "kc-m-1"))
    with pytest.raises(SessionRequired):
        resolve_mobile(env, verified("no-such-subject", "kc-m-1"))
    assert other != user
    with pytest.raises(SessionExpired):
        resolve_mobile(env, verified(subject, "kc-m-1"), now=T0 + timedelta(days=7))


def test_back_channel_logout_revokes_by_keycloak_session_id(env: RoleEnv) -> None:
    user, subject = make_user(env)
    web = open_session(env, user, kc="shared-kc")
    open_session(env, user, client=MOBILE, kc="shared-kc")
    bystander = open_session(env, user, kc="other-kc")
    assert as_worker(env, lambda db: sessions.revoke_by_kc_session(db, "shared-kc")) == 2
    assert web.credential and bystander.credential
    with pytest.raises(SessionRevoked):
        resolve(env, web.credential)
    assert resolve(env, bystander.credential)
    with pytest.raises(SessionRevoked):
        resolve_mobile(env, verified(subject, "shared-kc"))
    assert {r[0] for r in rows(env, "SELECT revoked_reason FROM user_sessions "
                                     "WHERE revoked_at IS NOT NULL")} == {"IDP_LOGOUT"}  # fmt: skip


# --- AC-SES-12: the migration cycle is covered by tests/test_role_sql.py and
# tests/audit/test_audit_db.py (upgrade head, downgrade, upgrade); see their updated expectations.


def test_untrusted_device_platform_is_not_copied_to_audit(env: RoleEnv) -> None:
    user, _ = make_user(env)
    open_session(env, user, client=ClientType.MOBILE, device_platform="654321")
    details = rows(env, "SELECT details FROM audit_events WHERE action='session.created'")
    assert details[0][0]["device_platform"] == "unknown"
    assert "654321" not in str(details)
