"""ADR-002 negative tests on real PostgreSQL 16 (requires TEST_PG_ADMIN_URL)."""

import uuid
from collections.abc import Iterator

import pytest
from app.core.db import RequestContext, session_scope
from sqlalchemy import CursorResult, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from tests.conftest import RoleEnv
from tests.rls_probe import Probe, build_probe


@pytest.fixture
def probe(role_env: RoleEnv) -> Iterator[Probe]:
    yield build_probe(role_env)


def count(engine: Engine, table: str, ctx: RequestContext) -> int:
    with session_scope(engine, ctx) as s:
        return int(s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


@pytest.mark.parametrize("kind", ["app", "worker"])
def test_omitted_context_sees_nothing(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    for table in ("rls_customers", "rls_cases", "rls_memberships"):
        assert count(engine, table, RequestContext()) == 0


@pytest.mark.parametrize("kind", ["app", "worker"])
def test_each_tenant_sees_only_its_own_rows(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    for tenant in (probe.tenant_a, probe.tenant_b):
        with session_scope(engine, probe.ctx(tenant)) as s:
            tenants = {r[0] for r in s.execute(text("SELECT tenant_id FROM rls_customers"))}
        assert tenants == {tenant}


def test_forged_tenant_in_insert_is_rejected(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(ProgrammingError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'forged')"),
            {"t": probe.tenant_b},
        )
    assert count(engine, "rls_customers", probe.ctx(probe.tenant_b)) == 1


def test_insert_without_context_is_rejected(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(ProgrammingError), session_scope(engine) as s:
        s.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'x')"),
            {"t": probe.tenant_a},
        )


def test_row_cannot_be_moved_to_another_tenant(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(ProgrammingError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(text("UPDATE rls_customers SET tenant_id = :b"), {"b": probe.tenant_b})


def test_cross_tenant_update_and_delete_touch_nothing(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        upd = s.execute(
            text("UPDATE rls_customers SET name='hacked' WHERE id = :id"),
            {"id": probe.customer_b},
        )
        dele = s.execute(text("DELETE FROM rls_customers WHERE id = :id"), {"id": probe.customer_b})
        assert isinstance(upd, CursorResult)
        assert isinstance(dele, CursorResult)
        assert upd.rowcount == 0
        assert dele.rowcount == 0
    with session_scope(engine, probe.ctx(probe.tenant_b)) as s:
        assert s.execute(text("SELECT name FROM rls_customers")).scalar_one() == "c"


def test_join_cannot_reach_other_tenants(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        rows = s.execute(
            text(
                "SELECT c.tenant_id, k.tenant_id FROM rls_cases c "
                "FULL JOIN rls_customers k ON k.id = c.customer_id"
            )
        ).all()
    assert rows == [(probe.tenant_a, probe.tenant_a)]


def test_composite_foreign_key_blocks_cross_tenant_reference(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(IntegrityError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(
            text("INSERT INTO rls_cases (tenant_id, customer_id) VALUES (:t, :c)"),
            {"t": probe.tenant_a, "c": probe.customer_b},
        )


def test_force_rls_applies_to_table_owner(probe: Probe) -> None:
    owner = probe.env.engine("owner")
    assert count(owner, "rls_customers", RequestContext()) == 0
    with probe.env.admin_engine().connect() as c:
        flags = c.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname LIKE 'rls\\_%' AND relkind = 'r'"
            )
        ).all()
    assert len(flags) == 3
    assert all(f[1] and f[2] for f in flags)


def test_context_does_not_leak_between_transactions(probe: Probe) -> None:
    engine = probe.env.engine("app")
    assert count(engine, "rls_customers", probe.ctx(probe.tenant_a)) == 1
    assert count(engine, "rls_customers", RequestContext()) == 0


def test_runtime_role_cannot_switch_role_or_disable_rls(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(DBAPIError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(text(f'SET ROLE "{probe.env.names.owner}"'))
    with pytest.raises(DBAPIError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(text("SET row_security = off"))
        s.execute(text("SELECT * FROM rls_customers")).all()


def test_malformed_context_fails_closed(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(DBAPIError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
        s.execute(text("SELECT set_config('app.tenant_id', 'not-a-uuid', true)"))
        s.execute(text("SELECT * FROM rls_customers")).all()


def test_user_sees_only_own_memberships_before_tenant_is_chosen(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with session_scope(engine, probe.ctx(user=probe.user_a)) as s:
        rows = s.execute(text("SELECT tenant_id, role FROM rls_memberships")).all()
    assert {(r[0], r[1]) for r in rows} == {(probe.tenant_a, "OWNER"), (probe.tenant_b, "VIEWER")}
    with session_scope(engine, probe.ctx(user=probe.user_b)) as s:
        assert s.execute(text("SELECT count(*) FROM rls_memberships")).scalar_one() == 1


def test_self_lookup_policy_is_read_only(probe: Probe) -> None:
    engine = probe.env.engine("app")
    with pytest.raises(ProgrammingError), session_scope(engine, probe.ctx(user=probe.user_a)) as s:
        s.execute(
            text("INSERT INTO rls_memberships VALUES (:t, :u, 'OWNER')"),
            {"t": uuid.uuid4(), "u": probe.user_a},
        )


def test_platform_role_has_no_table_access_by_default(probe: Probe) -> None:
    engine = probe.env.engine("platform")
    for table in ("rls_customers", "rls_cases", "rls_memberships"):
        with pytest.raises(ProgrammingError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
            s.execute(text(f"SELECT * FROM {table}"))


def test_runtime_roles_are_not_owners_and_do_not_bypass(probe: Probe) -> None:
    with probe.env.admin_engine().connect() as c:
        owners = {
            r[0]
            for r in c.execute(
                text("SELECT DISTINCT tableowner FROM pg_tables WHERE tablename LIKE 'rls\\_%'")
            )
        }
        bypass = c.execute(
            text("SELECT count(*) FROM pg_roles WHERE rolname = ANY(:n) AND rolbypassrls"),
            {"n": list(probe.env.names.all())},
        ).scalar_one()
    assert owners == {probe.env.names.owner}
    assert bypass == 0
