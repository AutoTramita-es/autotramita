"""F2-T10 / AC-PLT-11 (bootstrap, D30) and the authorities T10 hands to other packages: the F-4
review of a held D37 change and the controlled recovery of a locked account (interfaces: T11).
Real PostgreSQL 16 and Redis 7, the owner and platform roles, a fake admin API."""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from app.auth.security.email_change_review import (
    ReviewDecision,
    ReviewForbidden,
    ReviewResult,
    resolve_review,
)
from app.core.config import Environment
from app.core.db import RequestContext, create_session_factory, session_scope
from app.platform import authz
from app.platform.authz import Authority, GrantReviewAuthority, PlatformDenied
from app.platform.bootstrap import BootstrapRefused, bootstrap_platform_admin
from app.platform.models import GrantType
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from tests.platform.rig import PlatformRig
from tests.platform.test_platform_grants_db import raw_grant

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(UTC)


def owner(rig: PlatformRig) -> sessionmaker[Session]:
    return create_session_factory(rig.env.engine("owner"))


# --- AC-PLT-11 bootstrap ---------------------------------------------------------------------
def test_the_bootstrap_gives_an_active_person_with_a_factor_one_grant_and_records_it(
    rig: PlatformRig,
) -> None:
    who = rig.person("first")
    before = datetime.now(UTC)
    done = rig.bootstrap(who)
    lifetime = done.expires_at - before
    assert done.user_id == who.id and timedelta(days=90) <= lifetime < timedelta(days=90, seconds=5)
    assert rig.web.rows(
        "SELECT grant_type, status, granted_by, approved_by, reason FROM platform_grants"
    ) == [("PLATFORM_GRANT_ADMIN", "ACTIVE", None, None, "bootstrap")]
    assert rig.web.rows(
        "SELECT actor_type, actor_user_id, subject_user_id, reason_code, target_id FROM audit_events "
        "WHERE action = 'authz.platform_grant.activated'"
    ) == [("SYSTEM", None, who.id, "BOOTSTRAP", done.grant_id)]
    assert who.sub in rig.admin.mandatory and who.sub in rig.admin.obliged
    with pytest.raises(BootstrapRefused, match="already holds"):
        rig.bootstrap(who)


@pytest.mark.parametrize("environment", ["prod", "staging"])
def test_the_bootstrap_is_refused_outside_dev_and_test(rig: PlatformRig, environment: str) -> None:
    who = rig.person()
    with pytest.raises(BootstrapRefused, match="only in DEV"):
        bootstrap_platform_admin(
            owner(rig),
            rig.admin,
            email=who.email,
            environment=cast(Environment, environment),
            now=NOW,
        )
    assert rig.web.rows("SELECT count(*) FROM platform_grants") == [(0,)]


@pytest.mark.parametrize("role", ["app", "worker", "platform"])
def test_the_bootstrap_needs_the_owner_credentials(rig: PlatformRig, role: str) -> None:
    who = rig.person()
    with pytest.raises(BootstrapRefused, match="owner credentials"):
        bootstrap_platform_admin(
            create_session_factory(rig.env.engine(role)),
            rig.admin,
            email=who.email,
            environment="test",
            now=NOW,
        )
    assert rig.web.rows("SELECT count(*) FROM platform_grants") == [(0,)]


def test_the_bootstrap_refuses_unknown_inactive_and_unprovable_people(rig: PlatformRig) -> None:
    blocked = rig.person()
    with rig.env.admin_engine().connect() as c:
        c.execute(
            text("UPDATE users SET status='BLOCKED', version=version+1 WHERE id=:u"),
            {"u": blocked.id},
        )
    for email, match in (
        ("nobody@example.test", "no active account"),
        (blocked.email, "no active account"),
        ("not an address", "not a valid"),
    ):
        with pytest.raises(BootstrapRefused, match=match):
            bootstrap_platform_admin(
                owner(rig), rig.admin, email=email, environment="test", now=NOW
            )
    who = rig.person()
    with pytest.raises(BootstrapRefused, match="at most 90 days"):
        bootstrap_platform_admin(owner(rig), rig.admin, email=who.email, environment="test", now=NOW,
                                 lifetime=timedelta(days=91))  # fmt: skip
    rig.admin.down = True
    with pytest.raises(BootstrapRefused, match="not reachable"):
        rig.bootstrap(who)
    rig.admin.down = False
    with pytest.raises(BootstrapRefused, match="not reachable"):
        bootstrap_platform_admin(owner(rig), None, email=who.email, environment="test", now=NOW)
    assert rig.web.rows("SELECT count(*) FROM platform_grants") == [(0,)]
    assert rig.web.rows("SELECT count(*) FROM audit_events WHERE action LIKE 'authz.%'") == [(0,)]


def _cli() -> object:
    spec = importlib.util.spec_from_file_location(
        "bootstrap_cli", ROOT / "scripts" / "identity" / "bootstrap_platform_admin.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("environment", "owner_user", "message"),
    [("prod", "x_owner", "only in DEV"), ("test", None, "owner credentials")],
)
def test_the_command_refuses_production_and_a_missing_owner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environment: str,
    owner_user: str | None,
    message: str,
) -> None:
    from app.core.config import get_settings

    for key, value in {"ENVIRONMENT": environment, "POSTGRES_HOST": "localhost",
                       "POSTGRES_DB": "x_db", "POSTGRES_USER": "x_app",
                       "POSTGRES_PASSWORD": "p" * 20, "REDIS_URL": "redis://localhost:1/0"}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    for key in ("APP_DB_OWNER_USER", "APP_DB_OWNER_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    if owner_user:
        monkeypatch.setenv("APP_DB_OWNER_USER", owner_user)
        monkeypatch.setenv("APP_DB_OWNER_PASSWORD", "o" * 20)
    get_settings.cache_clear()
    try:
        assert _cli().main(["--email", "person@example.test"]) == 2  # type: ignore[attr-defined]
    finally:
        get_settings.cache_clear()
    assert message in capsys.readouterr().err


# --- the F-4 review authority ---------------------------------------------------------------------
@contextmanager
def held(
    rig: PlatformRig, who: uuid.UUID, kind: GrantType, proven: datetime
) -> Iterator[Authority]:
    with session_scope(rig.web.runtime.platform_factory, RequestContext(user_id=who)) as db:  # type: ignore[arg-type]
        grant = authz.acquire(db, who, kind)
        authority = authz.establish(db, held=grant, actor_id=who, actor_session_id=uuid.uuid4(),
                                    second_factor_at=proven, ip_prefix=None, ua_family=None)  # fmt: skip
        try:
            yield authority
        finally:
            authority.close()


def review(rig: PlatformRig, authority: GrantReviewAuthority) -> ReviewResult:
    worker = create_session_factory(rig.env.engine("worker"))
    return resolve_review(
        worker, rig.admin, uuid.uuid4(), ReviewDecision.CANCEL, authority=authority
    ).result


def test_a_user_administrator_with_a_fresh_factor_may_decide_a_held_change(
    rig: PlatformRig,
) -> None:
    operator = rig.person("operator")
    raw_grant(rig.env, operator.id, "PLATFORM_USER_ADMIN")
    now = datetime.now(UTC)
    with held(rig, operator.id, GrantType.PLATFORM_USER_ADMIN, now - timedelta(seconds=30)) as a:
        assert review(rig, GrantReviewAuthority(a, now)) is ReviewResult.NOT_IN_REVIEW  # permitted
        assert rig.web.rows(
            "SELECT count(*) FROM audit_events WHERE action='identity.email.change_reviewed'"
        ) == [(0,)]
    stale = now - timedelta(seconds=301)  # level two older than five minutes
    with (
        held(rig, operator.id, GrantType.PLATFORM_USER_ADMIN, stale) as a,
        pytest.raises(ReviewForbidden),
    ):
        review(rig, GrantReviewAuthority(a, now))
    with held(rig, operator.id, GrantType.PLATFORM_USER_ADMIN, now) as a:
        pass
    with pytest.raises(ReviewForbidden):  # the transaction that held the grant is over
        review(rig, GrantReviewAuthority(a, now))


def test_other_grants_or_none_never_decide_a_held_change(rig: PlatformRig) -> None:
    auditor = rig.person("auditor")
    raw_grant(rig.env, auditor.id, "PLATFORM_AUDIT_VIEW")
    now = datetime.now(UTC)
    with (
        held(rig, auditor.id, GrantType.PLATFORM_AUDIT_VIEW, now) as a,
        pytest.raises(ReviewForbidden),
    ):
        review(rig, GrantReviewAuthority(a, now))
    with (
        pytest.raises(PlatformDenied),
        held(rig, rig.person().id, GrantType.PLATFORM_USER_ADMIN, now),
    ):
        pass


# --- the controlled-recovery authority -----------------------------------------------------------
def test_account_recovery_is_authorised_only_with_its_grant_and_never_for_grant_holders(
    rig: PlatformRig,
) -> None:
    operator = rig.person("recovery")
    raw_grant(rig.env, operator.id, "PLATFORM_ACCOUNT_RECOVERY")
    locked = rig.person("locked", factor=None)
    holder = rig.person("holder")
    rig.admin.mandatory.add(holder.sub)
    now = datetime.now(UTC)
    with held(
        rig, operator.id, GrantType.PLATFORM_ACCOUNT_RECOVERY, now - timedelta(seconds=10)
    ) as a:
        authz.authorize_account_recovery(
            a, rig.admin, target_user_id=locked.id, target_subject=locked.sub, now=now
        )
        for target, subject in ((operator.id, operator.sub), (holder.id, holder.sub)):
            with pytest.raises(PlatformDenied):  # itself; an account whose factor is mandatory
                authz.authorize_account_recovery(
                    a, rig.admin, target_user_id=target, target_subject=subject, now=now
                )
        rig.admin.down = True
        with pytest.raises(PlatformDenied):  # the provider cannot say: no
            authz.authorize_account_recovery(
                a, rig.admin, target_user_id=locked.id, target_subject=locked.sub, now=now
            )
        rig.admin.down = False
        with pytest.raises(PlatformDenied):
            authz.authorize_account_recovery(
                a, None, target_user_id=locked.id, target_subject=locked.sub, now=now
            )
    with (
        held(
            rig, operator.id, GrantType.PLATFORM_ACCOUNT_RECOVERY, now - timedelta(seconds=301)
        ) as a,
        pytest.raises(PlatformDenied),
    ):
        authz.authorize_account_recovery(
            a, rig.admin, target_user_id=locked.id, target_subject=locked.sub, now=now
        )
    user_admin = rig.person("users")
    raw_grant(rig.env, user_admin.id, "PLATFORM_USER_ADMIN")
    with (
        held(rig, user_admin.id, GrantType.PLATFORM_USER_ADMIN, now) as a,
        pytest.raises(PlatformDenied),
    ):
        authz.authorize_account_recovery(
            a, rig.admin, target_user_id=locked.id, target_subject=locked.sub, now=now
        )
    assert locked.sub not in rig.admin.mandatory and rig.admin.deleted == []  # it only decides
