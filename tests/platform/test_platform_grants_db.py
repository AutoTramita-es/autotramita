"""F2-T10 / AC-PLT-01..10, AC-AUTHZ-03, AC-USR-06 and AC-SES-07 (platform parts): migration 0010 on
a real PostgreSQL 16 (disposable ``role_env`` database), through the genuine owner, app, worker
and platform roles. Nothing here trusts the service layer: every rule is tried directly in SQL."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from tests.conftest import RoleEnv
from tests.rls_probe import DDL as PROBE_DDL
from tests.test_roles_and_migrations import migrate

ADMIN, USERS, AUDIT, REVIEW, RECOVERY = (
    "PLATFORM_GRANT_ADMIN",
    "PLATFORM_USER_ADMIN",
    "PLATFORM_AUDIT_VIEW",
    "PLATFORM_VERIFICATION_REVIEW",
    "PLATFORM_ACCOUNT_RECOVERY",
)
EVERY_TYPE = (ADMIN, USERS, AUDIT, REVIEW, RECOVERY)


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def person(env: RoleEnv, status: str = "ACTIVE") -> uuid.UUID:
    sub = uuid.uuid4().hex
    verified = "NULL" if status == "PENDING_VERIFICATION" else "now()"
    with env.admin_engine().connect() as c:
        return uuid.UUID(
            str(
                c.execute(
                    text(
                        "INSERT INTO users (auth_subject, email, email_normalized, status, "
                        f"email_verified_at) VALUES (:s, :e, :e, :st, {verified}) RETURNING id"
                    ),
                    {"s": sub, "e": f"{sub}@example.test", "st": status},
                ).scalar_one()
            )
        )


def raw_grant(
    env: RoleEnv,
    user: uuid.UUID,
    kind: str,
    *,
    status: str = "ACTIVE",
    expires: str = "now() + interval '30 days'",
    granted_by: uuid.UUID | None = None,
    approved_by: uuid.UUID | None = None,
    created: str = "now()",
) -> uuid.UUID:
    """A grant row as fixture data: written by the superuser with triggers off (the CHECK
    constraints still hold), so tests can start from any state."""
    if kind != ADMIN or granted_by is not None:
        granted_by = granted_by or person(env)
        if kind in (ADMIN, USERS) and status == "ACTIVE":
            approved_by = approved_by or person(env)
    reason = "bootstrap" if granted_by is None else "fixture"
    with env.admin_engine().connect() as c:
        c.execute(text("SET session_replication_role = replica"))
        grant = c.execute(
            text(
                "INSERT INTO platform_grants (user_id, grant_type, status, expires_at, granted_by, "
                "approved_by, reason, created_at, activated_at) VALUES (:u, :t, :s, "
                f"{expires}, :g, :a, :r, {created}, "
                f"CASE WHEN :s = 'PENDING_APPROVAL' THEN NULL ELSE {created} END) RETURNING id"
            ),
            {"u": user, "t": kind, "s": status, "g": granted_by, "a": approved_by, "r": reason},
        ).scalar_one()
        c.execute(text("SET session_replication_role = DEFAULT"))
    return uuid.UUID(str(grant))


@contextmanager
def platform(
    env: RoleEnv, user: uuid.UUID, authority: uuid.UUID | None = None
) -> Iterator[Session]:
    factory = create_session_factory(env.engine("platform"))
    with session_scope(factory, RequestContext(user_id=user)) as db:
        if authority is not None:
            db.execute(
                text("SELECT set_config('app.grant_authority', :g, true)"), {"g": str(authority)}
            )
        yield db


def count(db: Session, table: str) -> int:
    return int(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def admin_rows(env: RoleEnv, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    with env.admin_engine().connect() as c:
        return [tuple(r) for r in c.execute(text(sql), params)]


def request_as(
    env: RoleEnv, actor: uuid.UUID, authority: uuid.UUID, beneficiary: uuid.UUID, kind: str,
    status: str = "PENDING_APPROVAL", expires: str = "now() + interval '30 days'",
) -> uuid.UUID:  # fmt: skip
    with platform(env, actor, authority) as db:
        return uuid.UUID(
            str(
                db.execute(
                    text(
                        "INSERT INTO platform_grants (user_id, grant_type, status, expires_at, "
                        f"granted_by, reason) VALUES (:u, :t, :s, {expires}, :a, 'needed for work') "
                        "RETURNING id"
                    ),
                    {"u": beneficiary, "t": kind, "s": status, "a": actor},
                ).scalar_one()
            )
        )


def administrator(env: RoleEnv) -> tuple[uuid.UUID, uuid.UUID]:
    who = person(env)
    return who, raw_grant(env, who, ADMIN)


# --- AC-PLT-01 shape: catalog, mandatory expiry within its limit, nobody grants to themselves ----
@pytest.mark.parametrize(
    ("kind", "lifetime", "ok"),
    [
        (ADMIN, "365 days", True), (ADMIN, "366 days", False), (USERS, "365 days", True),
        (REVIEW, "90 days", True), (REVIEW, "91 days", False), (AUDIT, "1 minute", True),
        ("PLATFORM_SUPER_ADMIN", "1 day", False), (RECOVERY, "0 seconds", False),
    ],
)  # fmt: skip
def test_types_and_lifetimes_are_closed_and_bounded(
    env: RoleEnv, kind: str, lifetime: str, ok: bool
) -> None:
    actor, authority = administrator(env)
    beneficiary = person(env)
    if ok:
        request_as(
            env, actor, authority, beneficiary, kind, expires=f"now() + interval '{lifetime}'"
        )
    else:
        with pytest.raises(DBAPIError):
            request_as(
                env, actor, authority, beneficiary, kind, expires=f"now() + interval '{lifetime}'"
            )


def test_expiry_is_mandatory_and_in_the_future(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    for expires in ("NULL", "now() - interval '1 second'"):
        with pytest.raises(DBAPIError):
            request_as(env, actor, authority, person(env), AUDIT, expires=expires)


def test_nobody_grants_to_themselves_even_through_sql(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    with pytest.raises(DBAPIError):
        request_as(env, actor, authority, actor, AUDIT)
    # the CHECK holds against any writer, the superuser included
    with pytest.raises(IntegrityError), env.admin_engine().connect() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(
            text(
                "INSERT INTO platform_grants (user_id, grant_type, status, expires_at, granted_by, "
                "reason) VALUES (:u, 'PLATFORM_AUDIT_VIEW', 'PENDING_APPROVAL', now() + "
                "interval '1 day', :u, 'x x x')"
            ),
            {"u": actor},
        )


@pytest.mark.parametrize(
    ("kind", "scope", "ok"),
    [
        (REVIEW, "scope_kind = 'TENANTS', scope_tenant_ids = ARRAY[gen_random_uuid()]", True),
        (REVIEW, "scope_kind = 'QUEUE', queue = 'ONBOARDING'", True),
        (AUDIT, "scope_kind = 'TENANTS', scope_tenant_ids = ARRAY[gen_random_uuid()]", False),
        (USERS, "scope_kind = 'QUEUE', queue = 'ONBOARDING'", False),
        (REVIEW, "scope_kind = 'TENANTS', scope_tenant_ids = '{}'", False),
        (REVIEW, "queue = 'ONBOARDING'", False),  # ALL with a queue
    ],
)
def test_only_the_verification_reviewer_has_a_narrower_scope(
    env: RoleEnv, kind: str, scope: str, ok: bool
) -> None:
    grant = raw_grant(env, person(env), kind, status="PENDING_APPROVAL")
    statement = text(f"UPDATE platform_grants SET {scope} WHERE id = :g")
    with env.admin_engine().connect() as c:
        c.execute(text("SET session_replication_role = replica"))  # shape only, no transition
        if ok:
            c.execute(statement, {"g": grant})
        else:
            with pytest.raises(IntegrityError):
                c.execute(statement, {"g": grant})


def test_only_an_active_account_receives_a_grant(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    for status in ("PENDING_VERIFICATION", "DEACTIVATED", "BLOCKED"):
        with pytest.raises(IntegrityError):
            request_as(env, actor, authority, person(env, status), AUDIT)
    with pytest.raises(IntegrityError):
        request_as(env, actor, authority, uuid.uuid4(), AUDIT)  # nobody


# --- AC-PLT-02 after activation only the revocation; never deleted ------------------------------
@pytest.mark.parametrize(
    "assignment",
    [
        "expires_at = expires_at + interval '1 day'", "grant_type = 'PLATFORM_USER_ADMIN'",
        "user_id = granted_by", "granted_by = user_id", "reason = 'other reason'",
        "created_at = now()", "scope_kind = 'ALL'", "status = 'PENDING_APPROVAL'",
        "status = 'ACTIVE'",
    ],
)  # fmt: skip
def test_an_active_grant_cannot_be_changed(env: RoleEnv, assignment: str) -> None:
    actor, authority = administrator(env)
    grant = raw_grant(env, person(env), AUDIT)
    with pytest.raises(DBAPIError), platform(env, actor, authority) as db:
        db.execute(text(f"UPDATE platform_grants SET {assignment} WHERE id = :g"), {"g": grant})


def test_a_revocation_is_final_and_names_its_actor(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    grant = raw_grant(env, person(env), AUDIT)
    other = person(env)
    with pytest.raises(DBAPIError), platform(env, actor, authority) as db:  # someone else's name
        db.execute(
            text("UPDATE platform_grants SET status='REVOKED', revoked_by=:o, "
                 "revoke_reason='WITHDRAWN' WHERE id=:g"), {"g": grant, "o": other})  # fmt: skip
    with platform(env, actor, authority) as db:
        db.execute(
            text("UPDATE platform_grants SET status='REVOKED', revoked_by=:a, "
                 "revoke_reason='NO_LONGER_NEEDED' WHERE id=:g"), {"g": grant, "a": actor})  # fmt: skip
    assert admin_rows(env, "SELECT status, revoked_by, revoked_at IS NOT NULL, version "
                      "FROM platform_grants WHERE id=:g", g=grant) == [("REVOKED", actor, True, 2)]  # fmt: skip
    for assignment in ("status = 'ACTIVE'", "revoke_reason = 'EXPIRED'", "revoked_at = now()"):
        with pytest.raises(DBAPIError), platform(env, actor, authority) as db:
            db.execute(text(f"UPDATE platform_grants SET {assignment} WHERE id = :g"), {"g": grant})


@pytest.mark.parametrize("kind", ["app", "worker", "platform", "owner"])
def test_grants_are_never_deleted_or_truncated(env: RoleEnv, kind: str) -> None:
    actor, authority = administrator(env)
    engine = env.engine(kind)
    for sql in ("DELETE FROM platform_grants", "TRUNCATE platform_grants"):
        try:
            with engine.begin() as c:
                c.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(actor)})
                c.execute(
                    text("SELECT set_config('app.grant_authority', :g, true)"),
                    {"g": str(authority)},
                )
                deleted = c.execute(text(sql)).rowcount
        except DBAPIError:
            continue
        # Only the owner gets this far: it has no DELETE policy, so nothing is visible to delete.
        assert kind == "owner" and sql.startswith("DELETE") and deleted == 0, (kind, sql)
    with pytest.raises(DBAPIError), env.admin_engine().connect() as c:  # not even the superuser
        c.execute(text("DELETE FROM platform_grants"))
    assert admin_rows(env, "SELECT count(*) FROM platform_grants") == [(1,)]


# --- AC-PLT-03 four eyes ------------------------------------------------------------------------
@pytest.mark.parametrize("kind", [ADMIN, USERS])
def test_four_eyes_types_never_take_effect_at_once(env: RoleEnv, kind: str) -> None:
    actor, authority = administrator(env)
    if kind == USERS:
        raw_grant(env, actor, USERS)  # holding the type itself changes nothing
    with pytest.raises(DBAPIError):
        request_as(env, actor, authority, person(env), kind, status="ACTIVE")


def test_neither_the_requester_nor_the_beneficiary_approves(env: RoleEnv) -> None:
    requester, requester_authority = administrator(env)
    beneficiary, beneficiary_authority = administrator(env)
    grant = request_as(env, requester, requester_authority, beneficiary, USERS)
    approve = text(
        "UPDATE platform_grants SET status='ACTIVE', approved_by=app_user_id() WHERE id=:g"
    )
    for who, authority in ((requester, requester_authority), (beneficiary, beneficiary_authority)):
        with pytest.raises(DBAPIError), platform(env, who, authority) as db:
            db.execute(approve, {"g": grant})
    second, second_authority = administrator(env)
    with (
        pytest.raises(DBAPIError),
        platform(env, second, second_authority) as db,
    ):  # in another's name
        db.execute(
            text("UPDATE platform_grants SET status='ACTIVE', approved_by=:o WHERE id=:g"),
            {"g": grant, "o": requester},
        )
    with platform(env, second, second_authority) as db:
        db.execute(approve, {"g": grant})
    assert admin_rows(env, "SELECT status, approved_by, activated_at IS NOT NULL FROM platform_grants "
                      "WHERE id=:g", g=grant) == [("ACTIVE", second, True)]  # fmt: skip


def test_an_expired_request_cannot_be_approved(env: RoleEnv) -> None:
    second, second_authority = administrator(env)
    grant = raw_grant(env, person(env), USERS, status="PENDING_APPROVAL",
                      created="now() - interval '2 days'", expires="now() - interval '1 day'")  # fmt: skip
    with pytest.raises(DBAPIError), platform(env, second, second_authority) as db:
        db.execute(
            text(
                "UPDATE platform_grants SET status='ACTIVE', approved_by=app_user_id() WHERE id=:g"
            ),
            {"g": grant},
        )


def test_one_live_grant_per_person_and_type(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    beneficiary = person(env)
    request_as(env, actor, authority, beneficiary, AUDIT)
    with pytest.raises(IntegrityError):
        request_as(env, actor, authority, beneficiary, AUDIT)
    request_as(env, actor, authority, beneficiary, REVIEW)  # another type is another grant


# --- AC-PLT-04 escalation ------------------------------------------------------------------------
def test_without_the_grant_administrator_grant_nothing_can_be_written(env: RoleEnv) -> None:
    auditor = person(env)
    audit_grant = raw_grant(env, auditor, AUDIT)
    target = person(env)
    for status in ("PENDING_APPROVAL", "ACTIVE"):
        with pytest.raises(ProgrammingError):  # row-level security: WITH CHECK
            request_as(env, auditor, audit_grant, target, AUDIT, status=status)
    other = raw_grant(env, target, REVIEW, status="PENDING_APPROVAL")
    with pytest.raises(DBAPIError), platform(env, auditor, audit_grant) as db:
        db.execute(
            text(
                "UPDATE platform_grants SET status='ACTIVE', approved_by=app_user_id() WHERE id=:g"
            ),
            {"g": other},
        )
    with pytest.raises(DBAPIError), platform(env, auditor, audit_grant) as db:  # not even its own
        db.execute(
            text("UPDATE platform_grants SET status='REVOKED', revoked_by=app_user_id(), "
                 "revoke_reason='WITHDRAWN' WHERE id=:g"), {"g": audit_grant})  # fmt: skip
    assert admin_rows(env, "SELECT status FROM platform_grants WHERE id=:g", g=audit_grant) == [
        ("ACTIVE",)
    ]


def test_a_type_takes_effect_at_once_only_when_its_grantor_holds_it(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    with pytest.raises(DBAPIError):  # the administrator does not hold the auditor grant
        request_as(env, actor, authority, person(env), AUDIT, status="ACTIVE")
    raw_grant(env, actor, AUDIT)
    granted = request_as(env, actor, authority, person(env), AUDIT, status="ACTIVE")
    assert admin_rows(
        env, "SELECT status, approved_by FROM platform_grants WHERE id=:g", g=granted
    ) == [("ACTIVE", None)]


def test_an_expired_or_revoked_grant_gives_no_power(env: RoleEnv) -> None:
    for case in ("expired", "revoked"):
        actor = person(env)
        if case == "revoked":
            grant = raw_grant(env, actor, ADMIN)
            with env.admin_engine().connect() as c:
                c.execute(text("SET session_replication_role = replica"))
                c.execute(text("UPDATE platform_grants SET status='REVOKED', revoked_at=now(), "
                               "revoked_by=user_id, revoke_reason='WITHDRAWN' WHERE id=:g"), {"g": grant})  # fmt: skip
        else:
            grant = raw_grant(env, actor, ADMIN, created="now() - interval '40 days'",
                              expires="now() - interval '1 second'")  # fmt: skip
        with platform(env, actor) as db:
            assert (
                db.execute(text("SELECT platform_has_grant('PLATFORM_GRANT_ADMIN')")).scalar_one()
                is False
            )
        with pytest.raises(ProgrammingError):
            request_as(env, actor, grant, person(env), AUDIT)


# --- AC-PLT-06 anti-lockout ----------------------------------------------------------------------
def test_the_last_grant_administrator_cannot_be_revoked(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    revoke = text("UPDATE platform_grants SET status='REVOKED', revoked_by=app_user_id(), "
                  "revoke_reason='WITHDRAWN' WHERE id=:g")  # fmt: skip
    with (
        pytest.raises(DBAPIError, match="last grant administrator"),
        platform(env, actor, authority) as db,
    ):
        db.execute(revoke, {"g": authority})
    second, second_authority = administrator(env)
    with platform(env, actor, authority) as db:  # now another one exists: allowed (even itself)
        db.execute(revoke, {"g": authority})
    with (
        pytest.raises(DBAPIError, match="last grant administrator"),
        platform(env, second, second_authority) as db,
    ):
        db.execute(revoke, {"g": second_authority})


def test_two_administrators_revoking_each_other_at_once_leave_one(env: RoleEnv) -> None:
    a, grant_a = administrator(env)
    b, grant_b = administrator(env)
    revoke = text("UPDATE platform_grants SET status='REVOKED', revoked_by=app_user_id(), "
                  "revoke_reason='WITHDRAWN' WHERE id=:g")  # fmt: skip
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(actor: uuid.UUID, own: uuid.UUID, target: uuid.UUID) -> None:
        try:
            with platform(env, actor, own) as db:
                db.execute(
                    text("SELECT 1 FROM platform_grants WHERE id = :g FOR UPDATE"), {"g": target}
                )
                barrier.wait(timeout=10)
                db.execute(revoke, {"g": target})
            outcomes.append("revoked")
        except DBAPIError as error:
            outcomes.append("refused" if "last grant administrator" in str(error) else repr(error))

    threads = [threading.Thread(target=attempt, args=(a, grant_a, grant_b)),
               threading.Thread(target=attempt, args=(b, grant_b, grant_a))]  # fmt: skip
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["refused", "revoked"]
    assert admin_rows(env, "SELECT count(*) FROM platform_grants WHERE status='ACTIVE'") == [(1,)]


# --- AC-PLT-05 revocation waits for a request that holds the grant (TOCTOU) ----------------------
def test_a_revocation_waits_for_the_transaction_that_uses_the_grant(env: RoleEnv) -> None:
    holder = person(env)
    auditor_grant = raw_grant(env, holder, AUDIT)
    actor, authority = administrator(env)
    using = threading.Event()
    release = threading.Event()
    seen: list[Any] = []

    def use() -> None:
        with platform(env, holder) as db:
            db.execute(text("SELECT 1 FROM platform_grants WHERE id=:g AND status='ACTIVE' "
                            "AND expires_at > now() FOR SHARE"), {"g": auditor_grant})  # fmt: skip
            using.set()
            release.wait(timeout=10)
            seen.append(
                db.execute(text("SELECT platform_has_grant('PLATFORM_AUDIT_VIEW')")).scalar_one()
            )

    worker = threading.Thread(target=use)
    worker.start()
    assert using.wait(timeout=10)
    started = time.monotonic()
    timer = threading.Timer(0.5, release.set)
    timer.start()
    with platform(env, actor, authority) as db:
        db.execute(text("UPDATE platform_grants SET status='REVOKED', revoked_by=app_user_id(), "
                        "revoke_reason='SECURITY_INCIDENT' WHERE id=:g"), {"g": auditor_grant})  # fmt: skip
    waited = time.monotonic() - started
    worker.join(timeout=10)
    assert seen == [True] and waited >= 0.4  # the request finished with its grant, then it ended
    with platform(env, holder) as db:  # the next request sees the revocation
        assert (
            db.execute(text("SELECT platform_has_grant('PLATFORM_AUDIT_VIEW')")).scalar_one()
            is False
        )


# --- AC-PLT-07 / AC-USR-06 / AC-SES-07 / AC-AUD-02 visibility per role --------------------------
def seed_people_sessions_and_audit(env: RoleEnv) -> uuid.UUID:
    someone = person(env)
    with env.admin_engine().connect() as c:
        c.execute(
            text("INSERT INTO user_sessions (user_id, client_type, credential_hash, kc_session_id, "
                 "auth_time, idle_expires_at, absolute_expires_at) VALUES (:u, 'WEB', "
                 "decode(repeat('ab', 32), 'hex'), 'sid-x', now(), now() + interval '1 hour', "
                 "now() + interval '2 hours')"), {"u": someone})  # fmt: skip
        c.execute(
            text("INSERT INTO audit_events (scope, category, action, outcome, actor_type, "
                 "actor_user_id) VALUES ('PLATFORM', 'AUTHN', 'auth.logout', 'SUCCESS', 'USER', :u)"),
            {"u": someone},
        )  # fmt: skip
    return someone


def test_the_platform_role_without_a_grant_sees_nothing(env: RoleEnv) -> None:
    seed_people_sessions_and_audit(env)
    nobody = person(env)
    raw_grant(env, person(env), AUDIT)  # someone else's grant
    for authority in (None, uuid.uuid4()):
        with platform(env, nobody, authority) as db:
            assert count(db, "users") == 0 and count(db, "user_sessions") == 0
            assert count(db, "audit_events") == 0
    with platform(env, nobody) as db:
        assert count(db, "platform_grants") == 0
    factory = create_session_factory(env.engine("platform"))
    with session_scope(factory, RequestContext()) as db:  # no person at all
        for table in ("users", "user_sessions", "audit_events", "platform_grants"):
            assert count(db, table) == 0


@pytest.mark.parametrize("kind", ["app", "worker"])
def test_the_application_and_the_worker_have_no_platform_path(env: RoleEnv, kind: str) -> None:
    holder = person(env)
    grant = raw_grant(env, holder, ADMIN)
    factory = create_session_factory(env.engine(kind))
    with (
        pytest.raises(ProgrammingError),
        session_scope(factory, RequestContext(user_id=holder)) as db,
    ):
        db.execute(text("SELECT count(*) FROM platform_grants"))
    with (
        pytest.raises(ProgrammingError),
        session_scope(factory, RequestContext(user_id=holder)) as db,
    ):
        db.execute(text("SELECT platform_has_grant('PLATFORM_GRANT_ADMIN')"))
    if kind == "app":  # its own policies only: the grant opens no other person's row
        seed_people_sessions_and_audit(env)
        with session_scope(factory, RequestContext(user_id=holder)) as db:
            db.execute(
                text("SELECT set_config('app.grant_authority', :g, true)"), {"g": str(grant)}
            )
            assert count(db, "users") == 1 and count(db, "user_sessions") == 0  # itself only
            assert count(db, "audit_events") == 0


def test_user_administrators_read_people_and_sessions_and_change_status(env: RoleEnv) -> None:
    someone = seed_people_sessions_and_audit(env)
    admin_user = person(env)
    raw_grant(env, admin_user, USERS)
    with platform(env, admin_user) as db:
        assert count(db, "users") == 4  # everybody: someone, itself, its grantor and approver
        assert count(db, "user_sessions") == 1 and count(db, "audit_events") == 0
        db.execute(text("UPDATE users SET status='BLOCKED', status_reason='SECURITY', "
                        "version=version+1 WHERE id=:u"), {"u": someone})  # fmt: skip
        db.execute(text("UPDATE user_sessions SET revoked_at=now(), revoked_reason='ADMIN_REVOKED', "
                        "revoked_by=app_user_id(), version=version+1 WHERE user_id=:u"), {"u": someone})  # fmt: skip
    for statement in (
        "UPDATE users SET email = 'x@example.test' WHERE id = :u",  # status columns only
        "UPDATE user_sessions SET active_tenant_id = gen_random_uuid() WHERE user_id = :u",
        "DELETE FROM users WHERE id = :u",
    ):
        with pytest.raises(DBAPIError), platform(env, admin_user) as db:
            db.execute(text(statement), {"u": someone})
    assert admin_rows(env, "SELECT status FROM users WHERE id=:u", u=someone) == [("BLOCKED",)]


def test_without_the_user_administrator_grant_status_cannot_change(env: RoleEnv) -> None:
    someone = seed_people_sessions_and_audit(env)
    actor, authority = administrator(env)  # a grant administrator is not a user administrator
    raw_grant(env, someone, REVIEW)  # someone is now named by a grant: visible, not changeable
    with platform(env, actor, authority) as db:
        assert db.execute(text("SELECT id FROM users WHERE id=:u"), {"u": someone}).all() != []
        changed = db.execute(text("UPDATE users SET status='BLOCKED', version=version+1 "
                                  "WHERE id=:u RETURNING id"), {"u": someone}).all()  # fmt: skip
        assert changed == [] and count(db, "user_sessions") == 0
    assert admin_rows(env, "SELECT status FROM users WHERE id=:u", u=someone) == [("ACTIVE",)]


def test_grant_administrators_see_only_the_people_a_grant_names(env: RoleEnv) -> None:
    named = person(env)
    unnamed = person(env)
    actor, authority = administrator(env)
    request_as(env, actor, authority, named, AUDIT)
    with platform(env, actor, authority) as db:
        visible = {r[0] for r in db.execute(text("SELECT id FROM users"))}
    assert named in visible and unnamed not in visible
    with platform(env, actor) as db:  # without the second step only its own grants and itself
        assert count(db, "platform_grants") == 1
        assert {r[0] for r in db.execute(text("SELECT id FROM users"))} == {actor}


def test_auditors_read_the_trail_and_write_only_their_own_grant_records(env: RoleEnv) -> None:
    seed_people_sessions_and_audit(env)
    auditor = person(env)
    raw_grant(env, auditor, AUDIT)
    with platform(env, auditor) as db:
        assert count(db, "audit_events") == 1 and count(db, "users") == 0
    insert = ("INSERT INTO audit_events (scope, category, action, outcome, actor_type, actor_user_id, "
              "tenant_id) VALUES ('PLATFORM', :c, 'authz.platform_grant.used', 'SUCCESS', 'USER', :a, :t)")  # fmt: skip
    with platform(env, auditor) as db:
        db.execute(text(insert), {"c": "AUTHZ", "a": auditor, "t": None})
    for category, actor, tenant in (("AUTHN", auditor, None), ("AUTHZ", person(env), None),
                                    ("AUTHZ", auditor, uuid.uuid4())):  # fmt: skip
        with pytest.raises(ProgrammingError), platform(env, auditor) as db:
            db.execute(text(insert), {"c": category, "a": actor, "t": tenant})
    with pytest.raises(DBAPIError), platform(env, auditor) as db:
        db.execute(text("UPDATE audit_events SET outcome = 'FAILURE'"))


# --- AC-PLT-08 the verification reviewer has no user or grant powers; nothing is inherited -------
def test_a_verification_reviewer_has_no_user_or_grant_powers(env: RoleEnv) -> None:
    seed_people_sessions_and_audit(env)
    reviewer = person(env)
    grant = raw_grant(env, reviewer, REVIEW)
    with platform(env, reviewer, grant) as db:  # even with a forged second step
        assert count(db, "users") == 0 and count(db, "user_sessions") == 0
        assert count(db, "audit_events") == 0
        for kind in EVERY_TYPE:
            holds = db.execute(text("SELECT platform_has_grant(:t)"), {"t": kind}).scalar_one()
            assert holds is (kind == REVIEW)
    with pytest.raises(ProgrammingError):
        request_as(env, reviewer, grant, person(env), REVIEW)


def test_a_grant_administrator_inherits_no_other_type(env: RoleEnv) -> None:
    actor, authority = administrator(env)
    with platform(env, actor, authority) as db:
        held = {
            k
            for k in EVERY_TYPE
            if db.execute(text("SELECT platform_has_grant(:t)"), {"t": k}).scalar_one()
        }
    assert held == {ADMIN}


# --- AC-PLT-09 / AC-AUTHZ-03 platform grants open no tenant data, tenant roles give no grant -----
def test_no_platform_grant_opens_tenant_data(env: RoleEnv) -> None:
    with env.engine("owner").begin() as c:
        c.execute(text(PROBE_DDL))
    tenant = uuid.uuid4()
    with session_scope(
        create_session_factory(env.engine("app")), RequestContext(tenant_id=tenant)
    ) as db:
        db.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'C')"), {"t": tenant}
        )
    everything = person(env)
    for kind in EVERY_TYPE:
        raw_grant(env, everything, kind)
    for table in ("rls_customers", "rls_cases", "rls_memberships"):
        with pytest.raises(ProgrammingError), platform(env, everything) as db:
            db.execute(text(f"SELECT * FROM {table}"))
    with platform(env, everything) as db:  # a tenant context switches every platform power off
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        assert (
            db.execute(text("SELECT platform_has_grant('PLATFORM_USER_ADMIN')")).scalar_one()
            is False
        )
        assert count(db, "users") == 0 and count(db, "platform_grants") == 0


def test_a_tenant_membership_gives_no_platform_grant(env: RoleEnv) -> None:
    with env.engine("owner").begin() as c:
        c.execute(text(PROBE_DDL))
    member = person(env)
    tenant = uuid.uuid4()
    with session_scope(
        create_session_factory(env.engine("app")), RequestContext(tenant_id=tenant)
    ) as db:
        db.execute(
            text("INSERT INTO rls_memberships VALUES (:t, :u, 'OWNER')"), {"t": tenant, "u": member}
        )
    with platform(env, member) as db:
        assert not any(
            db.execute(text("SELECT platform_has_grant(:t)"), {"t": k}).scalar_one()
            for k in EVERY_TYPE
        )
        assert count(db, "users") == 0


# --- functions and owner bootstrap policies ------------------------------------------------------
def test_the_grant_function_runs_as_the_caller_and_only_for_the_platform_role(env: RoleEnv) -> None:
    rows = admin_rows(
        env,
        "SELECT p.proname, p.prosecdef, p.provolatile, coalesce(p.proacl::text, '') FROM pg_proc p "
        "WHERE p.proname IN ('platform_has_grant', 'app_grant_authority') ORDER BY 1",
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("app_grant_authority", False, "s"), ("platform_has_grant", False, "s")]  # fmt: skip
    for row in rows:
        grantees = {item.split("=")[0] for item in row[3].strip("{}").split(",") if item}
        assert grantees == {env.names.owner, env.names.platform}, row


def test_the_platform_context_never_mixes_with_a_sign_in_proof(env: RoleEnv) -> None:
    actor, _ = administrator(env)
    with platform(env, actor) as db:
        db.execute(text("SELECT set_config('app.auth_subject', 'someone', true)"))
        assert (
            db.execute(text("SELECT platform_has_grant('PLATFORM_GRANT_ADMIN')")).scalar_one()
            is False
        )
        assert count(db, "platform_grants") == 0


def test_the_owner_may_only_insert_a_bootstrap_grant_for_the_one_person_it_names(
    env: RoleEnv,
) -> None:
    target = person(env)
    other = person(env)
    email = admin_rows(env, "SELECT email_normalized FROM users WHERE id=:u", u=target)[0][0]
    owner = create_session_factory(env.engine("owner"))
    with session_scope(owner, RequestContext()) as db:
        assert count(db, "users") == 0  # nothing without naming the person
        db.execute(text("SELECT set_config('app.bootstrap_email', :e, true)"), {"e": email})
        assert [r[0] for r in db.execute(text("SELECT id FROM users"))] == [target]
    for shape in (
        "(:u, 'PLATFORM_USER_ADMIN', 'ACTIVE', now() + interval '1 day', NULL, 'bootstrap')",
        "(:u, 'PLATFORM_GRANT_ADMIN', 'ACTIVE', now() + interval '91 days', NULL, 'bootstrap')",
        "(:u, 'PLATFORM_GRANT_ADMIN', 'ACTIVE', now() + interval '1 day', :o, 'bootstrap')",
        "(:u, 'PLATFORM_GRANT_ADMIN', 'PENDING_APPROVAL', now() + interval '1 day', NULL, 'bootstrap')",
        "(:o, 'PLATFORM_GRANT_ADMIN', 'ACTIVE', now() + interval '1 day', NULL, 'bootstrap')",  # unnamed
    ):
        with pytest.raises(DBAPIError), session_scope(owner, RequestContext()) as db:
            db.execute(text("SELECT set_config('app.bootstrap_email', :e, true)"), {"e": email})
            db.execute(text("INSERT INTO platform_grants (user_id, grant_type, status, expires_at, "
                            f"granted_by, reason) VALUES {shape}"), {"u": target, "o": other})  # fmt: skip
    with session_scope(owner, RequestContext()) as db:  # the owner reads no person's audit
        assert count(db, "audit_events") == 0 and count(db, "user_sessions") == 0


# --- expiry boundary and the policy catalog ----------------------------------------------------
def test_a_grant_works_until_its_expiry_and_not_a_moment_after(env: RoleEnv) -> None:
    holder = person(env)
    raw_grant(env, holder, AUDIT, expires="now() + interval '1500 milliseconds'")
    with platform(env, holder) as db:
        assert (
            db.execute(text("SELECT platform_has_grant('PLATFORM_AUDIT_VIEW')")).scalar_one()
            is True
        )
    time.sleep(1.7)
    with platform(env, holder) as db:  # still ACTIVE in the row, but expired: no power at all
        assert (
            db.execute(text("SELECT platform_has_grant('PLATFORM_AUDIT_VIEW')")).scalar_one()
            is False
        )
        assert count(db, "audit_events") == 0
    assert admin_rows(env, "SELECT status FROM platform_grants WHERE user_id = :u", u=holder) == [
        ("ACTIVE",)
    ]


def test_every_policy_of_the_platform_role_is_behind_a_grant_or_its_own_rows(env: RoleEnv) -> None:
    policies = admin_rows(
        env,
        "SELECT tablename, policyname, coalesce(qual, '') || ' ' || coalesce(with_check, '') "
        "FROM pg_policies WHERE schemaname = 'public' AND :r = ANY(roles) ORDER BY 1, 2",
        r=env.names.platform,
    )
    assert {(t, p) for t, p, _ in policies} == {
        ("audit_events", "audit_platform_insert"), ("audit_events", "audit_platform_read"),
        ("platform_grants", "grants_platform_change"), ("platform_grants", "grants_platform_read"),
        ("platform_grants", "grants_platform_request"), ("user_sessions", "sessions_platform_read"),
        ("user_sessions", "sessions_platform_revoke"), ("users", "users_platform_read"),
        ("users", "users_platform_status"),
    }  # fmt: skip
    for table, name, expression in policies:
        assert "app_user_id() IS NOT NULL" in expression, name  # a person, never a bare role
        assert "app_tenant_id() IS NULL" in expression, name  # never inside a tenant context
        if name == "audit_platform_insert":
            assert "actor_user_id = app_user_id()" in expression  # only its own records
        elif table == "platform_grants" and name != "grants_platform_request":
            assert "app_grant_authority()" in expression or "platform_has_grant" in expression, name
        else:
            assert "platform_has_grant" in expression, name
    others = admin_rows(
        env,
        "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public' "
        "AND (qual ~ 'platform_has_grant|app_grant_authority' OR with_check ~ 'platform_has_grant|app_grant_authority') "
        "AND NOT (:r = ANY(roles))",
        r=env.names.platform,
    )
    assert others == []  # no other role is opened by a platform grant
