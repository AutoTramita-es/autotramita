"""T03 reconciliation: tenant, branch and bootstrap restrictions on real RLS."""

import hashlib
import uuid

import pytest
from app.audit.models import ActorType, AuditEvent, Outcome, Scope
from app.audit.record import record
from app.auth.security.markers import RecoveryMarkers
from app.core.db import RequestContext, create_session_factory, session_scope
from app.core.ratelimit import create_redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.auth.fake_admin import FakeAdmin
from tests.auth.sessions.test_sessions_db import make_user, open_session, rows
from tests.auth.web_harness import SUBJECT, build_web
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


# --- R01: no policy answers a context that mixes a bootstrap proof with a person ---------------
@pytest.mark.parametrize("proof", ["app.auth_subject", "app.session_hash"])
def test_a_person_context_with_a_bootstrap_proof_sees_and_writes_nothing(
    env: RoleEnv, proof: str
) -> None:
    user, subject = make_user(env)
    session = open_session(env, user).session.id
    factory = create_session_factory(env.engine("app"))
    value = subject if proof == "app.auth_subject" else "ab" * 32
    set_proof = text("SELECT set_config(:name, :value, true)")
    for table in ("users", "user_sessions", "audit_events"):
        with session_scope(factory, RequestContext(user_id=user)) as db:
            count = text(f"SELECT count(*) FROM {table}")
            assert db.execute(count).scalar_one() > 0  # control
            db.execute(set_proof, {"name": proof, "value": value})
            assert db.execute(count).scalar_one() == 0, table
    writes = (
        "INSERT INTO user_sessions (user_id, client_type, credential_hash, kc_session_id, "
        "auth_time, idle_expires_at, absolute_expires_at) VALUES (app_user_id(), 'WEB', "
        "decode(repeat('cd', 32), 'hex'), 'mixed', now(), now() + interval '1 hour', "
        "now() + interval '2 hours')",
        "INSERT INTO audit_events (scope, category, action, outcome, actor_type, actor_user_id) "
        "VALUES ('PLATFORM', 'AUTHN', 'auth.logout', 'SUCCESS', 'USER', app_user_id())",
        "INSERT INTO email_change_operations (user_id, session_id, old_email, new_email, "
        "new_email_normalized, token_hash, token_issued_at, token_expires_at) VALUES "
        f"(app_user_id(), '{session}', 'a@example.test', 'b@example.test', 'b@example.test', "
        "decode(repeat('ef', 32), 'hex'), now(), now() + interval '30 minutes')",
    )
    for statement in writes:
        with pytest.raises(DBAPIError), session_scope(factory, RequestContext(user_id=user)) as db:
            db.execute(set_proof, {"name": proof, "value": value})
            db.execute(text(statement))
    for statement in writes:  # control: the same statements work in a pure person context
        with session_scope(factory, RequestContext(user_id=user)) as db:
            db.execute(text(statement))


def test_a_session_proof_with_a_tenant_reveals_nothing(env: RoleEnv) -> None:
    user, _ = make_user(env)
    created = open_session(env, user)
    assert created.credential
    factory = create_session_factory(env.engine("app"))
    digest = hashlib.sha256(created.credential.encode()).digest()
    count = text("SELECT count(*) FROM user_sessions")
    with session_scope(factory, RequestContext(session_hash=digest)) as db:
        assert db.execute(count).scalar_one() == 1
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(uuid.uuid4())})
        assert db.execute(count).scalar_one() == 0


# --- R02: the tenant boundary of the own security trail ----------------------------------------
def test_another_persons_events_of_the_same_tenant_stay_invisible(env: RoleEnv) -> None:
    one, two, tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    factory = create_session_factory(env.engine("app"))
    for user in (one, two):
        with session_scope(factory, RequestContext(user_id=user, tenant_id=tenant)) as db:
            assert record(db, event(user, tenant))
    with session_scope(factory, RequestContext(user_id=one, tenant_id=tenant)) as db:
        actors = db.execute(text("SELECT actor_user_id FROM audit_events")).scalars().all()
    assert actors == [one]
    with session_scope(factory, RequestContext(tenant_id=tenant)) as db:  # a tenant alone
        assert db.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
    with env.engine("worker").connect() as db, pytest.raises(DBAPIError):
        db.execute(text("SELECT count(*) FROM audit_events"))
    platform = create_session_factory(env.engine("platform"))
    for person in (one, two):  # F2-T10: the platform role reads only with PLATFORM_AUDIT_VIEW
        with session_scope(platform, RequestContext(user_id=person)) as db:
            assert db.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0


# --- R03: every way of naming a branch the request does not hold -------------------------------
@pytest.mark.parametrize(
    "case", ["no_branches", "foreign_tenant", "branch_without_tenant", "other_branch"]
)
def test_forged_branch_writes_are_refused_by_the_database(env: RoleEnv, case: str) -> None:
    user, tenant, branch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    held = () if case == "no_branches" else (branch,)
    context = RequestContext(user_id=user, tenant_id=tenant, branch_ids=held)
    row = {
        "scope": "TENANT",
        "tenant": uuid.uuid4() if case == "foreign_tenant" else tenant,
        "branch": uuid.uuid4() if case == "other_branch" else branch,
    }
    if case == "branch_without_tenant":
        row = {"scope": "PLATFORM", "tenant": None, "branch": branch}
    statement = text(
        "INSERT INTO audit_events (scope, category, action, outcome, actor_type, actor_user_id, "
        "tenant_id, branch_id) VALUES (:scope, 'AUTHN', 'auth.logout', 'SUCCESS', 'USER', "
        "app_user_id(), :tenant, :branch)"
    )
    factory = create_session_factory(env.engine("app"))
    with pytest.raises(DBAPIError), session_scope(factory, context) as db:
        db.execute(statement, row)
    assert rows(env, "SELECT count(*) FROM audit_events") == [(0,)]


# --- R04: the migration itself removes PUBLIC execution ----------------------------------------
def test_the_migration_removes_a_public_execute_grant_and_strangers_cannot_call(
    role_env: RoleEnv,
) -> None:
    owner = role_env.engine("owner")
    migrate(owner, "upgrade", "0007")
    with owner.begin() as db:
        db.exec_driver_sql("GRANT EXECUTE ON FUNCTION app_user_id() TO PUBLIC")
    migrate(owner, "upgrade", "head")
    functions = rows(
        role_env,
        "SELECT p.oid::regprocedure::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'",
    )
    assert len(functions) >= 10
    stranger = f"{role_env.names.owner}_nobody"
    with role_env.admin_engine().connect() as db:
        db.exec_driver_sql(f'CREATE ROLE "{stranger}"')
    try:
        for (name,) in functions:
            assert rows(
                role_env,
                "SELECT has_function_privilege(:r, CAST(:f AS regprocedure), 'EXECUTE')",
                r=stranger,
                f=name,
            ) == [(False,)], name
        assert rows(
            role_env,
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.prosecdef",
        ) == [(0,)]  # nothing runs with the owner's rights
    finally:
        with role_env.admin_engine().connect() as db:
            db.exec_driver_sql(f'DROP ROLE "{stranger}"')


# --- R05: minimisation ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["aB3xQ9", "xYzSecretValue123", "AbCdEfGhIjKlMnOpQrStUv", "a" * 33, "with space", "Mixed"],
)
def test_a_detail_code_is_a_constant_or_a_short_identifier(value: str) -> None:
    from app.audit.record import AuditValidationError, validate

    candidate = AuditEvent(
        action="auth.login.failed",
        outcome=Outcome.FAILURE,
        actor_type=ActorType.SYSTEM,
        details={"error": value},
    )
    with pytest.raises(AuditValidationError):
        validate(candidate)


@pytest.mark.parametrize("address", ["203.0.113.77", "2001:db8:77:5:abcd::99"])
def test_a_full_client_address_is_stored_nowhere(
    role_env: RoleEnv, redis_url: str, address: str
) -> None:
    migrate(role_env.engine("owner"), "upgrade", "head")
    web = build_web(role_env, redis_url, AUTH_SECURITY_HMAC_KEY="k" * 32)
    admin = FakeAdmin()
    admin.add("person@example.test", SUBJECT)
    web.runtime.admin = admin
    web.runtime.markers = RecoveryMarkers(create_redis(redis_url), namespace=f"ip{id(web)}")
    try:
        client = web.client(client=(address, 5000))
        assert web.sign_in(client).status_code == 302
        assert client.post("/api/v1/auth/logout").status_code == 403  # CSRF denial is audited
        client.post("/api/v1/auth/password-recovery", json={"email": "person@example.test"})
        client.get("/api/v1/auth/callback", params={"code": "x", "state": "y"})
        phone = web.client(
            client=(address, 5001), headers={"authorization": f"Bearer {web.access(sid='m')}"}
        )
        assert phone.post("/api/v1/auth/mobile/session", json={}).status_code == 201
        stored = " ".join(
            str(r[0])
            for table in ("audit_events", "user_sessions", "users")
            for r in web.rows(f"SELECT row_to_json(t)::text FROM {table} t")
        )
        prefixes = web.rows(
            "SELECT DISTINCT ip_prefix::text FROM audit_events WHERE ip_prefix IS NOT NULL"
        )
        audited = web.rows("SELECT action FROM audit_events WHERE ip_prefix IS NOT NULL")
    finally:
        web.close()
    assert address not in stored
    expected = "203.0.113.0/24" if "." in address else "2001:db8:77::/48"
    assert prefixes == [(expected,)]
    assert len(audited) >= 5, audited  # sign-in, CSRF denial, recovery, rejection, mobile


# --- R06: what the worker may write ------------------------------------------------------------
@pytest.mark.parametrize(
    "column",
    ["actor_user_id", "actor_session_id", "branch_without_tenant"],
)
def test_the_worker_cannot_write_in_a_persons_name(env: RoleEnv, column: str) -> None:
    name = "branch_id" if column == "branch_without_tenant" else column
    statement = text(
        f"INSERT INTO audit_events (scope, category, action, outcome, actor_type, {name}) "
        "VALUES ('PLATFORM', 'AUTHN', 'auth.logout', 'SUCCESS', 'SYSTEM', :value)"
    )
    factory = create_session_factory(env.engine("worker"))
    with pytest.raises(DBAPIError), session_scope(factory, RequestContext()) as db:
        db.execute(statement, {"value": uuid.uuid4()})
    assert rows(env, "SELECT count(*) FROM audit_events") == [(0,)]


def test_the_workers_audit_privilege_is_insert_only(env: RoleEnv) -> None:
    held = {
        privilege
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES")
        if rows(
            env,
            "SELECT has_table_privilege(:r, 'audit_events', :p)",
            r=env.names.worker,
            p=privilege,
        )[0][0]
    }
    assert held == {"INSERT"}
    assert rows(
        env,
        "SELECT count(*) FROM pg_attribute a, aclexplode(a.attacl) x "
        "WHERE a.attrelid = 'audit_events'::regclass",
    ) == [(0,)]
