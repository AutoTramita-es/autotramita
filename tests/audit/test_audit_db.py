"""F2-T03 / AC-AUD-01..03, 06, 07, 09: the append-only audit log on a real PostgreSQL 16.
Everything runs on the throwaway database of ``role_env``."""

import uuid
from typing import Any

import pytest
from app.audit.catalog import CATALOG
from app.audit.models import ActorType, AuditEvent, Outcome, Scope, Source
from app.audit.record import record, record_independent
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.conftest import RoleEnv
from tests.test_role_sql import schema_objects
from tests.test_roles_and_migrations import migrate

USER_A, USER_B = uuid.uuid4(), uuid.uuid4()
SAMPLE: dict[str, Any] = {"code": "WEB", "int": 3, "bool": True, "uuid": str(uuid.uuid4())}
RAW = (
    "INSERT INTO audit_events (scope, category, action, outcome, actor_type, details, ip_prefix) "
    "VALUES ('PLATFORM', 'AUTHN', 'auth.logout', 'SUCCESS', 'ANONYMOUS', "
    "CAST(:d AS jsonb), CAST(:ip AS cidr))"
)


@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def login(user: uuid.UUID, **kw: Any) -> AuditEvent:
    return AuditEvent(
        action="auth.login.succeeded", outcome=Outcome.SUCCESS, actor_type=ActorType.USER,
        actor_user_id=user, details={"client_type": "WEB"}, **kw,
    )  # fmt: skip


def count_all(env: RoleEnv) -> int:
    with env.admin_engine().connect() as c:  # superuser: bypasses row security
        return int(c.execute(text("SELECT count(*) FROM audit_events")).scalar_one())


def write(env: RoleEnv, event: AuditEvent, user: uuid.UUID | None = USER_A) -> bool:
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(user_id=user)) as s:
        return record(s, event)


# --- AC-AUD-01 append-only --------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["app", "worker", "platform"])
@pytest.mark.parametrize(
    "sql",
    ["UPDATE audit_events SET outcome = 'FAILURE'", "DELETE FROM audit_events",
     "TRUNCATE audit_events"],
)  # fmt: skip
def test_runtime_roles_cannot_update_delete_or_truncate(env: RoleEnv, kind: str, sql: str) -> None:
    write(env, login(USER_A))
    engine = env.engine(kind)
    with engine.connect() as c, pytest.raises(DBAPIError):
        c.execute(text(sql))
    assert count_all(env) == 1


@pytest.mark.parametrize(
    "sql",
    ["UPDATE audit_events SET outcome = 'FAILURE'", "DELETE FROM audit_events",
     "TRUNCATE audit_events"],
)  # fmt: skip
def test_trigger_refuses_changes_even_for_a_superuser(env: RoleEnv, sql: str) -> None:
    write(env, login(USER_A))
    with env.admin_engine().connect() as c, pytest.raises(DBAPIError, match="append-only"):
        c.execute(text(sql))
    assert count_all(env) == 1


def test_table_privilege_matrix(env: RoleEnv) -> None:
    privileges = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
    expected = {
        "app": {"SELECT", "INSERT"},
        "worker": {"INSERT"},
        "platform": {"SELECT", "INSERT"},  # F2-T10: behind PLATFORM_AUDIT_VIEW / own grant use
        "owner": None,  # the owner holds everything as table owner; not asserted here
    }
    with env.admin_engine().connect() as c:
        for kind, allowed in expected.items():
            if allowed is None:
                continue
            role = getattr(env.names, kind)
            granted = {
                p
                for p in privileges
                if c.execute(
                    text("SELECT has_table_privilege(:r, 'audit_events', :p)"), {"r": role, "p": p}
                ).scalar_one()
            }
            assert granted == allowed, (kind, granted)


# --- AC-AUD-02 forced RLS and visibility -------------------------------------------------------
def test_forced_rls_and_per_person_visibility(env: RoleEnv) -> None:
    write(env, login(USER_A))
    write(env, login(USER_B), user=USER_B)
    write(  # an administrative action about user A: not part of A's own security trail
        env,
        AuditEvent(
            action="admin.user.searched",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=USER_B,
            subject_user_id=USER_A,
            details={"match_kind": "ID"},
        ),
        user=USER_B,
    )
    with env.admin_engine().connect() as c:
        flags = c.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                 "WHERE relname = 'audit_events'")
        ).one()  # fmt: skip
    assert tuple(flags) == (True, True)
    factory = create_session_factory(env.engine("app"))

    def visible(user: uuid.UUID | None) -> list[str]:
        with session_scope(factory, RequestContext(user_id=user)) as s:
            return [r[0] for r in s.execute(text("SELECT action FROM audit_events"))]

    assert visible(None) == []  # no context, no rows
    assert visible(USER_A) == ["auth.login.succeeded"]
    assert sorted(visible(USER_B)) == ["auth.login.succeeded"]  # B sees only the own login
    assert visible(uuid.uuid4()) == []
    with env.engine("worker").connect() as c, pytest.raises(DBAPIError):
        c.execute(text("SELECT count(*) FROM audit_events"))  # no privilege, no policy
    platform = create_session_factory(env.engine("platform"))
    for person in (None, USER_A):  # F2-T10: only with PLATFORM_AUDIT_VIEW (0010)
        with session_scope(platform, RequestContext(user_id=person)) as s:
            assert s.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0


# --- AC-AUD-03 scope check, no foreign keys ---------------------------------------------------
def test_tenant_scope_requires_a_tenant_and_there_is_no_foreign_key(env: RoleEnv) -> None:
    with pytest.raises(IntegrityError):
        write(env, login(USER_A, scope=Scope.TENANT))
    tenant = uuid.uuid4()
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(user_id=USER_A, tenant_id=tenant)) as s:
        assert record(s, login(USER_A, scope=Scope.TENANT, tenant_id=tenant))
    with env.admin_engine().connect() as c:
        foreign = c.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conrelid = 'audit_events'::regclass "
                 "AND contype = 'f'")
        ).scalar_one()  # fmt: skip
    assert foreign == 0  # a record outlives the person it names (D31)


# --- AC-AUD-04 database-level guards ----------------------------------------------------------
@pytest.mark.parametrize(
    "details",
    ['{"note": "my password"}', '{"mail": "x@example.test"}', '{"x": "Bearer abcdefghijkl"}',
     '{"t": "eyJhbGciOiJSUzI1NiJ9.e30.sig"}', '{"client_secret": "x"}', '[1, 2]',
     '{"k": "' + "a" * 5000 + '"}'],
)  # fmt: skip
def test_database_rejects_secret_like_or_oversized_details(env: RoleEnv, details: str) -> None:
    with env.admin_engine().connect() as c, pytest.raises(IntegrityError):
        c.execute(text(RAW), {"d": details, "ip": None})


@pytest.mark.parametrize("prefix", ["192.0.2.7/32", "192.0.2.0/25", "2001:db8:1:2::/64"])
def test_database_rejects_full_addresses(env: RoleEnv, prefix: str) -> None:
    with env.admin_engine().connect() as c, pytest.raises(IntegrityError):
        c.execute(text(RAW), {"d": "{}", "ip": prefix})


def test_database_accepts_truncated_prefixes_and_clean_details(env: RoleEnv) -> None:
    with env.admin_engine().connect() as c:
        c.execute(text(RAW), {"d": '{"client_type": "WEB"}', "ip": "192.0.2.0/24"})
        c.execute(text(RAW), {"d": "{}", "ip": "2001:db8:1::/48"})
    assert count_all(env) == 2


def test_user_actor_needs_an_id_and_anonymous_must_not_have_one(env: RoleEnv) -> None:
    no_id = AuditEvent(action="auth.logout", outcome=Outcome.SUCCESS, actor_type=ActorType.USER)
    with pytest.raises(IntegrityError):
        write(env, no_id, user=None)
    with_id = AuditEvent(
        action="auth.logout", outcome=Outcome.SUCCESS, actor_type=ActorType.ANONYMOUS,
        actor_user_id=USER_A,
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        write(env, with_id, user=USER_A)
    assert count_all(env) == 0


# --- insert policies --------------------------------------------------------------------------
def test_app_role_cannot_forge_actor_tenant_or_source(env: RoleEnv) -> None:
    other = uuid.uuid4()
    with pytest.raises(DBAPIError):  # acting as someone else
        write(env, login(other))
    with pytest.raises(DBAPIError):  # a tenant that is not the request's tenant
        write(env, login(USER_A, scope=Scope.TENANT, tenant_id=uuid.uuid4()))
    with pytest.raises(DBAPIError):  # identity-provider events come from the worker only
        write(env, login(USER_A, source=Source.KEYCLOAK, source_event_id="x"))
    assert count_all(env) == 0
    assert write(env, login(USER_A)) is True  # control: the honest event works
    assert count_all(env) == 1


def test_worker_may_insert_system_and_idp_events_only_and_cannot_read(env: RoleEnv) -> None:
    factory = create_session_factory(env.engine("worker"))
    system = AuditEvent(action="session.expired_detected", outcome=Outcome.SUCCESS,
                        actor_type=ActorType.SYSTEM, details={"kind": "IDLE"})  # fmt: skip
    idp = AuditEvent(action="auth.login.failed", outcome=Outcome.FAILURE, actor_type=ActorType.IDP,
                     source=Source.KEYCLOAK, source_event_id="kc-1",
                     details={"client_id": "at-web"})  # fmt: skip
    with session_scope(factory, RequestContext()) as s:
        assert record(s, system) is True
        assert record(s, idp) is True
    with pytest.raises(DBAPIError), session_scope(factory, RequestContext(user_id=USER_A)) as s:
        record(s, login(USER_A))  # a worker cannot claim to be a user
    assert count_all(env) == 2


# --- AC-AUD-06 deduplication ------------------------------------------------------------------
def test_identity_provider_event_ingestion_is_idempotent(env: RoleEnv) -> None:
    factory = create_session_factory(env.engine("worker"))
    idp = AuditEvent(action="auth.login.failed", outcome=Outcome.FAILURE, actor_type=ActorType.IDP,
                     source=Source.KEYCLOAK, source_event_id="kc-42",
                     details={"client_id": "at-web"})  # fmt: skip
    with session_scope(factory, RequestContext()) as s:
        assert record(s, idp) is True
        assert record(s, idp) is False  # same (source, source_event_id)
    with session_scope(factory, RequestContext()) as s:
        assert record(s, idp) is False
    assert count_all(env) == 1


# --- AC-AUD-09 atomicity ----------------------------------------------------------------------
def test_audit_rolls_back_with_its_business_transaction(env: RoleEnv) -> None:
    factory = create_session_factory(env.engine("app"))

    def failing() -> None:
        with session_scope(factory, RequestContext(user_id=USER_A)) as s:
            record(s, login(USER_A))
            raise RuntimeError("business step failed")

    with pytest.raises(RuntimeError):
        failing()
    assert count_all(env) == 0


def test_independent_audit_survives_a_failed_request(env: RoleEnv) -> None:
    factory = create_session_factory(env.engine("app"))
    denied = AuditEvent(action="authz.denied", outcome=Outcome.DENIED,
                        actor_type=ActorType.ANONYMOUS, details={"reason": "CSRF"})  # fmt: skip

    def failing() -> None:
        with session_scope(factory, RequestContext(user_id=USER_A)) as s:
            record(s, login(USER_A))  # rolled back with the request
            record_independent(factory, denied)  # own transaction: kept
            raise RuntimeError("request failed")

    with pytest.raises(RuntimeError):
        failing()
    with env.admin_engine().connect() as c:
        actions = [r[0] for r in c.execute(text("SELECT action FROM audit_events"))]
    assert actions == ["authz.denied"]


# --- every catalog action is storable ---------------------------------------------------------
def test_every_catalog_action_can_be_stored(env: RoleEnv) -> None:
    factory = create_session_factory(env.engine("app"))
    with session_scope(factory, RequestContext(user_id=USER_A)) as s:
        for action, spec in CATALOG.items():
            details = {key: SAMPLE[kind] for key, kind in spec.details.items()}
            assert record(
                s,
                AuditEvent(action=action, outcome=Outcome.SUCCESS, actor_type=ActorType.USER,
                           actor_user_id=USER_A, details=details),
            )  # fmt: skip
    assert count_all(env) == len(CATALOG)
    with env.admin_engine().connect() as c:
        categories = {r[0] for r in c.execute(text("SELECT DISTINCT category FROM audit_events"))}
    assert categories == {spec.category.value for spec in CATALOG.values()}


# --- AC-AUD-07 migration cycle ----------------------------------------------------------------
def test_downgrade_removes_everything_and_upgrade_restores_it(role_env: RoleEnv) -> None:
    owner = role_env.engine("owner")
    migrate(owner, "upgrade", "head")
    before = schema_objects(role_env)
    assert "audit_events" in before[0]
    migrate(owner, "downgrade", "0001")
    tables, functions = schema_objects(role_env)
    assert tables == set() and functions == {"app_user_id", "app_tenant_id", "app_branch_ids"}
    migrate(owner, "upgrade", "head")
    assert schema_objects(role_env) == before
