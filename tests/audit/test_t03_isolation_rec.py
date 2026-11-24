"""T03 reconciliation: tenant, branch and bootstrap restrictions on real RLS."""

import uuid

import pytest
from app.audit.models import ActorType, AuditEvent, Outcome, Scope
from app.audit.record import record
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.auth.sessions.test_sessions_db import make_user
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def event(user: uuid.UUID, tenant: uuid.UUID, branch: uuid.UUID | None = None) -> AuditEvent:
    return AuditEvent(
        action="auth.logout",
        outcome=Outcome.SUCCESS,
        actor_type=ActorType.USER,
        actor_user_id=user,
        subject_user_id=user,
        scope=Scope.TENANT,
        tenant_id=tenant,
        branch_id=branch,
    )


def test_own_audit_read_is_limited_to_current_tenant(env: RoleEnv) -> None:
    user, tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    factory = create_session_factory(env.engine("app"))
    for tenant in (tenant_a, tenant_b):
        with session_scope(factory, RequestContext(user_id=user, tenant_id=tenant)) as db:
            assert record(db, event(user, tenant))
    with session_scope(factory, RequestContext(user_id=user, tenant_id=tenant_a)) as db:
        assert db.execute(text("SELECT tenant_id FROM audit_events")).scalars().all() == [tenant_a]
    with session_scope(factory, RequestContext(user_id=user)) as db:
        assert db.execute(text("SELECT tenant_id FROM audit_events")).scalars().all() == []


def test_branch_inserts_require_validated_branch(env: RoleEnv) -> None:
    user, tenant, branch, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    factory = create_session_factory(env.engine("app"))
    context = RequestContext(user_id=user, tenant_id=tenant, branch_ids=(branch,))
    with session_scope(factory, context) as db:
        assert record(db, event(user, tenant, branch))
    with pytest.raises(DBAPIError), session_scope(factory, context) as db:
        record(db, event(user, tenant, other))


def test_sql_policies_reject_mixed_bootstrap_and_user_context(env: RoleEnv) -> None:
    user_a, _ = make_user(env)
    user_b, subject_b = make_user(env)
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(user_id=user_a)) as db:
        assert db.execute(text("SELECT id FROM users")).scalars().all() == [user_a]
        db.execute(text("SELECT set_config('app.auth_subject', :sub, true)"), {"sub": subject_b})
        assert db.execute(text("SELECT id FROM users")).scalars().all() == []
    with session_scope(factory, RequestContext(auth_subject=subject_b)) as db:
        assert db.execute(text("SELECT id FROM users")).scalars().all() == [user_b]
        db.execute(
            text("SELECT set_config('app.session_hash', :digest, true)"), {"digest": "ab" * 32}
        )
        assert db.execute(text("SELECT id FROM users")).scalars().all() == []


def test_context_functions_are_not_executable_by_public(env: RoleEnv) -> None:
    with env.admin_engine().connect() as db:
        leaked = db.execute(
            text("""
            SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
                LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
            WHERE n.nspname='public' AND p.proowner =
              (SELECT oid FROM pg_roles WHERE rolname=:owner)
              AND a.grantee=0 AND a.privilege_type='EXECUTE'
        """),
            {"owner": env.names.owner},
        ).all()
    assert leaked == []


@pytest.mark.parametrize(
    "value", ["192.0.2.7", "2001:db8::1", "::1", "mail@example.test", "A" * 43]
)
def test_audit_rejects_sensitive_data_in_unstructured_fields(env: RoleEnv, value: str) -> None:
    from app.audit.record import AuditValidationError, validate

    candidate = AuditEvent(
        action="auth.login.failed",
        outcome=Outcome.FAILURE,
        actor_type=ActorType.SYSTEM,
        source_event_id=value,
    )
    with pytest.raises(AuditValidationError):
        validate(candidate)
    with env.admin_engine().connect() as db, pytest.raises(DBAPIError):
        db.execute(
            text("""
            INSERT INTO audit_events (scope, category, action, outcome, actor_type, source_event_id)
            VALUES ('PLATFORM','AUTHN','auth.login.failed','FAILURE','SYSTEM',:value)
        """),
            {"value": value},
        )


def test_worker_cannot_forge_identity_provider_source(env: RoleEnv) -> None:
    from app.audit.models import Source

    factory = create_session_factory(env.engine("worker"))
    candidate = AuditEvent(
        action="auth.login.failed",
        outcome=Outcome.FAILURE,
        actor_type=ActorType.SYSTEM,
        source=Source.KEYCLOAK,
    )
    with pytest.raises(DBAPIError), session_scope(factory, RequestContext()) as db:
        record(db, candidate)
