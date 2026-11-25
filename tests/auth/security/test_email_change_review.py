"""F2-T09-REC F-4: resolving a D37 change held in MANUAL_REVIEW, on real PostgreSQL 16 under the
worker role, with a stateful fake identity provider."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.auth.idp import IdpEmailState, IdpUser
from app.auth.security.email_change import claim_recovery, create_request
from app.auth.security.email_change_review import (
    Blocker,
    DenyAllReview,
    ProviderState,
    Resolution,
    ReviewDecision,
    ReviewForbidden,
    ReviewResult,
    resolve_review,
)
from app.auth.security.email_change_worker import run_once
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.auth.fake_admin import FakeAdmin
from tests.auth.security.test_email_change_worker import confirmed, jobs, sql, state
from tests.auth.sessions.test_sessions_db import factory, make_user, open_session, rows
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

ROOT = Path(__file__).resolve().parents[3]
NEW = "new@example.test"
RETRY, CANCEL = ReviewDecision.RETRY, ReviewDecision.CANCEL


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


class Allow:
    def __init__(self) -> None:
        self.asked: list[tuple[UUID, ReviewDecision]] = []

    def permits(self, db: Session, operation_id: UUID, decision: ReviewDecision) -> bool:
        assert db.in_transaction()  # the decision is checked inside the resolving transaction
        self.asked.append((operation_id, decision))
        return True


def held(env: RoleEnv, admin: FakeAdmin) -> UUID:
    """A confirmed change that ran out of time and now waits for a decision."""
    operation = confirmed(env, admin, NEW)
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert claim_recovery(db, now=datetime.now(UTC) + timedelta(hours=25)) is None
    assert state(env, operation) == ("MANUAL_REVIEW", 0)
    return operation


def subject_of(admin: FakeAdmin) -> str:
    return next(iter(admin.users.values())).subject


def decide(
    env: RoleEnv, admin: FakeAdmin, operation: UUID, decision: ReviewDecision, **kw: Any
) -> Resolution:
    kw.setdefault("authority", Allow())
    return resolve_review(factory(env, "worker"), admin, operation, decision, **kw)


def audits(env: RoleEnv) -> list[tuple[Any, ...]]:
    return rows(
        env,
        "SELECT outcome, actor_type, details->>'decision', details->>'result', "
        "subject_user_id IS NOT NULL FROM audit_events "
        "WHERE action = 'identity.email.change_reviewed' ORDER BY occurred_at",
    )


def change_at_provider(admin: FakeAdmin, to: str, *, verified: bool = True) -> None:
    old, user = next(iter(admin.users.items()))
    del admin.users[old]
    admin.users[to] = IdpUser(user.subject, True, verified)


def writes(admin: FakeAdmin) -> list[str]:
    return [c for c in admin.calls if c in ("set_email", "enable", "logout", "delete", "email")]


# --- who may decide ------------------------------------------------------------------------------
@pytest.mark.parametrize("authority", [None, DenyAllReview()], ids=["default", "deny_all"])
@pytest.mark.parametrize("decision", [RETRY, CANCEL])
def test_nobody_may_decide_until_an_authority_is_wired(
    env: RoleEnv, authority: Any, decision: ReviewDecision
) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    admin.calls.clear()
    with pytest.raises(ReviewForbidden):
        resolve_review(factory(env, "worker"), admin, operation, decision, authority=authority)
    assert state(env, operation)[0] == "MANUAL_REVIEW" and admin.calls == []
    assert audits(env) == [("DENIED", "SYSTEM", decision.value, "FORBIDDEN", False)]


def test_no_route_command_or_task_reaches_the_review(env: RoleEnv) -> None:
    """F-4: no temporary administration endpoint. The interface arrives with T11 and grants."""
    files = [
        (path.relative_to(ROOT).as_posix(), path.read_text())
        for folder in ("app", "scripts", "migrations")
        for path in (ROOT / folder).rglob("*.py")
    ]
    users = [
        name
        for name, source in files
        if "email_change_review" in source
        and name
        not in (
            "app/auth/security/email_change_review.py",
            "migrations/versions/0009_email_change_review.py",
            "app/platform/authz.py",  # F2-T10: supplies the authority, calls nothing
        )
    ]
    assert users == []
    callers = [
        name
        for name, source in files
        if "resolve_review(" in source and name != "app/auth/security/email_change_review.py"
    ]
    assert callers == []  # still no route, command or task reaches it (interface: T11)


# --- retry -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("applied", [False, True], ids=["not_applied", "applied"])
def test_a_retry_hands_the_change_back_to_the_worker_which_finishes_it(
    env: RoleEnv, applied: bool
) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    if applied:
        change_at_provider(admin, NEW)
    admin.calls.clear()
    done = decide(env, admin, operation, RETRY)
    assert done.result is ReviewResult.RETRY_QUEUED and done.inspection is not None
    assert done.inspection.provider is (
        ProviderState.APPLIED if applied else ProviderState.NOT_APPLIED
    )
    assert writes(admin) == []  # deciding writes nothing at the provider
    assert state(env, operation) == ("APPLYING", 0)
    assert rows(env, "SELECT email FROM users") != [(NEW,)]
    run_once(factory(env, "worker"), admin, None)
    assert state(env, operation) == ("COMPLETED", 1)
    assert rows(env, "SELECT email FROM users") == [(NEW,)]
    assert admin.calls.count("set_email") == (0 if applied else 1)
    assert [j[0] for j in jobs(env)] == ["NEW", "OLD"]
    assert audits(env) == [("SUCCESS", "SYSTEM", "RETRY", "RETRY_QUEUED", True)]


def test_a_retried_change_gets_a_new_bounded_series_and_can_be_held_again(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    sql(env, "UPDATE email_change_operations SET confirmed_at = now() - interval '3 days'")
    assert decide(env, admin, operation, RETRY).result is ReviewResult.RETRY_QUEUED
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert claim_recovery(db, now=datetime.now(UTC) + timedelta(hours=1)) is not None
    sql(env, "UPDATE email_change_operations SET lease_id=NULL, lease_until=NULL")
    with session_scope(factory(env, "worker"), RequestContext()) as db:
        assert claim_recovery(db, now=datetime.now(UTC) + timedelta(hours=25)) is None
    assert state(env, operation)[0] == "MANUAL_REVIEW"


# --- cancel ------------------------------------------------------------------------------------------
def test_a_cancellation_frees_the_address_and_changes_nothing_else(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    before = rows(env, "SELECT email, email_normalized, status, version FROM users")
    admin.calls.clear()
    done = decide(env, admin, operation, CANCEL)
    assert done.result is ReviewResult.CANCELLED
    assert rows(
        env,
        "SELECT status, old_email, new_email, new_email_normalized, token_hash, next_attempt_at "
        "FROM email_change_operations",
    ) == [("CANCELLED", None, None, None, None, None)]
    assert rows(env, "SELECT email, email_normalized, status, version FROM users") == before
    assert writes(admin) == [] and jobs(env) == []
    assert audits(env) == [("SUCCESS", "SYSTEM", "CANCEL", "CANCELLED", True)]
    # the reservation is gone: somebody else may now ask for the same address
    other, _ = make_user(env)
    session = open_session(env, other)
    with session_scope(factory(env), RequestContext(user_id=other)) as db:
        create_request(db, user_id=other, session_id=session.session.id, new_email=NEW)


# --- the facts decide -------------------------------------------------------------------------------
def applied_(env: RoleEnv, admin: FakeAdmin) -> None:
    change_at_provider(admin, NEW)


def third_address(env: RoleEnv, admin: FakeAdmin) -> None:
    change_at_provider(admin, "third@example.test")


def unverified_old(env: RoleEnv, admin: FakeAdmin) -> None:
    old, user = next(iter(admin.users.items()))
    admin.users[old] = IdpUser(user.subject, True, False)


def another_identity(env: RoleEnv, admin: FakeAdmin) -> None:
    subject = subject_of(admin)
    admin.get_email_state = lambda subject_: IdpEmailState(  # type: ignore[method-assign, assignment]
        subject + "-x", NEW, NEW, True
    )


def provider_down(env: RoleEnv, admin: FakeAdmin) -> None:
    admin.down = True


def taken_at_provider(env: RoleEnv, admin: FakeAdmin) -> None:
    admin.add(NEW, "somebody-else")


def taken_locally(env: RoleEnv, admin: FakeAdmin) -> None:
    user, _ = make_user(env)
    sql(env, "UPDATE users SET email=:e, email_normalized=:e WHERE id=:i", e=NEW, i=user)


def deactivated(env: RoleEnv, admin: FakeAdmin) -> None:
    sql(
        env,
        "UPDATE users SET status='DEACTIVATED', version=version+1 WHERE auth_subject=:s",
        s=subject_of(admin),
    )


@pytest.mark.parametrize(
    ("situation", "retry", "cancel"),
    [
        (applied_, None, Blocker.CHANGE_ALREADY_APPLIED),
        (third_address, Blocker.PROVIDER_DIVERGENT, Blocker.PROVIDER_DIVERGENT),
        (unverified_old, Blocker.PROVIDER_DIVERGENT, Blocker.PROVIDER_DIVERGENT),
        (another_identity, Blocker.PROVIDER_DIVERGENT, Blocker.PROVIDER_DIVERGENT),
        (provider_down, Blocker.PROVIDER_UNAVAILABLE, Blocker.PROVIDER_UNAVAILABLE),
        (taken_at_provider, Blocker.ADDRESS_TAKEN_AT_PROVIDER, None),
        (taken_locally, Blocker.ADDRESS_TAKEN_LOCALLY, None),
        (deactivated, Blocker.ACCOUNT_NOT_ACTIVE, None),
    ],
)
@pytest.mark.parametrize("decision", [RETRY, CANCEL])
def test_a_decision_the_facts_do_not_allow_is_refused_and_changes_nothing(
    env: RoleEnv,
    situation: Any,
    retry: Blocker | None,
    cancel: Blocker | None,
    decision: ReviewDecision,
) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    situation(env, admin)
    admin.calls.clear()
    users = rows(env, "SELECT id, email, status FROM users ORDER BY id")
    expected = retry if decision is RETRY else cancel
    done = decide(env, admin, operation, decision)
    assert writes(admin) == []
    assert rows(env, "SELECT id, email, status FROM users ORDER BY id") == users
    if expected is None:
        assert done.result in (ReviewResult.RETRY_QUEUED, ReviewResult.CANCELLED)
        return
    assert done.result is ReviewResult.REFUSED and done.inspection is not None
    found = done.inspection.retry_blockers if decision is RETRY else done.inspection.cancel_blockers
    assert expected in found
    assert state(env, operation)[0] == "MANUAL_REVIEW"
    assert rows(env, "SELECT new_email FROM email_change_operations") == [(NEW,)]
    assert audits(env) == [("FAILURE", "SYSTEM", decision.value, found[0].value, True)]


# --- idempotent and serialised ------------------------------------------------------------------------
@pytest.mark.parametrize("decision", [RETRY, CANCEL])
def test_repeating_a_decision_changes_nothing(env: RoleEnv, decision: ReviewDecision) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    assert decide(env, admin, operation, decision).result is not ReviewResult.REFUSED
    after = rows(env, "SELECT * FROM email_change_operations")
    admin.calls.clear()
    assert decide(env, admin, operation, decision).result is ReviewResult.ALREADY_RESOLVED
    other = CANCEL if decision is RETRY else RETRY
    assert decide(env, admin, operation, other).result is ReviewResult.NOT_IN_REVIEW
    assert rows(env, "SELECT * FROM email_change_operations") == after
    assert admin.calls == [] and len(audits(env)) == 1


def test_an_unknown_or_unheld_operation_is_not_in_review(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = confirmed(env, admin, NEW)
    for target in (operation, uuid4()):
        for decision in (RETRY, CANCEL):
            assert decide(env, admin, target, decision).result is ReviewResult.NOT_IN_REVIEW
    assert state(env, operation) == ("CONFIRMED", 0) and audits(env) == []


class Slow(FakeAdmin):
    """The first reader of the provider waits until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.hold = False
        self.entered, self.release = threading.Event(), threading.Event()

    def get_email_state(self, subject: str) -> IdpEmailState:
        if self.hold and not self.entered.is_set():
            self.entered.set()
            assert self.release.wait(20)
        return super().get_email_state(subject)


@pytest.mark.parametrize(
    ("first", "second"),
    [(RETRY, CANCEL), (CANCEL, RETRY), (RETRY, RETRY), (CANCEL, CANCEL)],
)
def test_two_decisions_at_once_are_serialised_and_only_one_acts(
    env: RoleEnv, first: ReviewDecision, second: ReviewDecision
) -> None:
    admin = Slow()
    operation = held(env, admin)
    admin.hold = True
    results: dict[str, ReviewResult] = {}

    def run(name: str, decision: ReviewDecision) -> None:
        results[name] = decide(env, admin, operation, decision).result

    one = threading.Thread(target=run, args=("first", first))
    one.start()
    assert admin.entered.wait(20)
    two = threading.Thread(target=run, args=("second", second))
    two.start()
    two.join(1.0)
    assert two.is_alive(), "the second decision did not wait for the first"
    admin.release.set()
    one.join(20)
    two.join(20)
    assert results["first"] in (ReviewResult.RETRY_QUEUED, ReviewResult.CANCELLED)
    assert results["second"] is (
        ReviewResult.ALREADY_RESOLVED if first is second else ReviewResult.NOT_IN_REVIEW
    )
    assert [a[0] for a in audits(env)] == ["SUCCESS"]


def test_the_periodic_sweep_never_touches_a_held_change(env: RoleEnv) -> None:
    admin = FakeAdmin()
    operation = held(env, admin)
    admin.calls.clear()
    for _ in range(2):
        run_once(factory(env, "worker"), admin, None)
    assert state(env, operation)[0] == "MANUAL_REVIEW" and admin.calls == []


# --- the database rule ------------------------------------------------------------------------------
def update(env: RoleEnv, role: str, status: str, operation: UUID, named: UUID | None) -> int:
    clear = ", old_email=NULL, new_email=NULL, new_email_normalized=NULL" if status in (
        "CANCELLED", "COMPLETED", "EXPIRED") else ""  # fmt: skip
    done = ", completed_at=now()" if status == "COMPLETED" else ""
    with session_scope(factory(env, role), RequestContext()) as db:
        if named is not None:
            db.execute(
                text("SELECT set_config('app.email_change_review', :v, true)"), {"v": str(named)}
            )
        result: Any = db.execute(
            text(f"UPDATE email_change_operations SET status=:s{clear}{done} WHERE id=:i"),
            {"s": status, "i": operation},
        )
        return int(result.rowcount)


@pytest.mark.parametrize("status", ["APPLYING", "CANCELLED"])
@pytest.mark.parametrize("named", ["nothing", "another_operation"])
def test_a_held_change_cannot_leave_review_by_accident(
    env: RoleEnv, status: str, named: str
) -> None:
    operation = held(env, FakeAdmin())
    with pytest.raises(DBAPIError, match="invalid email change transition"):
        update(env, "worker", status, operation, None if named == "nothing" else uuid4())
    assert state(env, operation)[0] == "MANUAL_REVIEW"


@pytest.mark.parametrize("status", ["PENDING", "CONFIRMED", "COMPLETED", "EXPIRED"])
def test_even_a_named_review_allows_only_retry_and_cancel(env: RoleEnv, status: str) -> None:
    operation = held(env, FakeAdmin())
    with pytest.raises(DBAPIError):
        update(env, "worker", status, operation, operation)
    assert state(env, operation)[0] == "MANUAL_REVIEW"


def test_the_application_and_platform_roles_cannot_resolve_a_held_change(env: RoleEnv) -> None:
    operation = held(env, FakeAdmin())
    # the application may write the status column, but row-level security hides the held row
    assert update(env, "app", "APPLYING", operation, operation) == 0
    for role in ("app", "platform"):  # neither may clear the addresses
        with pytest.raises(DBAPIError, match="permission denied"):
            update(env, role, "CANCELLED", operation, operation)
    assert state(env, operation)[0] == "MANUAL_REVIEW"


# --- nothing identifying leaves -----------------------------------------------------------------------
def test_neither_audit_nor_log_holds_an_address_subject_or_provider_message(
    env: RoleEnv, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="app")
    admin = FakeAdmin()
    operation = held(env, admin)
    subject = subject_of(admin)
    admin.down = True
    refused = decide(env, admin, operation, RETRY)
    admin.down = False
    done = decide(env, admin, operation, CANCEL)
    seen = repr(
        rows(env, "SELECT row_to_json(a)::text FROM audit_events a "
                  "WHERE action = 'identity.email.change_reviewed'")
    ) + repr((refused, done)) + caplog.text  # fmt: skip
    for secret in (NEW, "@example.test", subject):
        assert secret not in seen, secret


def test_a_change_held_before_the_migration_can_be_resolved_after_it(role_env: RoleEnv) -> None:
    """Compatibility of 0009: data written under 0008 is kept and becomes resolvable; going back
    keeps it too and closes the way out again."""
    owner = role_env.engine("owner")
    migrate(owner, "upgrade", "0008")
    admin = FakeAdmin()
    operation = held(role_env, admin)
    kept = rows(role_env, "SELECT * FROM email_change_operations")
    with pytest.raises(DBAPIError, match="invalid email change transition"):
        decide(role_env, admin, operation, CANCEL)
    assert (
        rows(role_env, "SELECT * FROM email_change_operations") == kept and audits(role_env) == []
    )
    migrate(owner, "upgrade", "head")
    assert rows(role_env, "SELECT * FROM email_change_operations") == kept
    migrate(owner, "downgrade", "0008")
    assert rows(role_env, "SELECT * FROM email_change_operations") == kept
    migrate(owner, "upgrade", "head")
    assert decide(role_env, admin, operation, CANCEL).result is ReviewResult.CANCELLED
