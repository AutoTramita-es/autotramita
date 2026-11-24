"""F1-T05 RLS security gate (AC04-AC09) on real PostgreSQL 16 with real non-owner roles.

Fixtures are created by the owner role in ``tests/rls_probe.py`` (never migrated into the
production schema). Every test exercises genuine app / worker / platform connections;
tenants A and B and their users are synthetic. Any failure here blocks later tasks.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from app.core.db import RequestContext, apply_context, session_scope
from sqlalchemy import CursorResult, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from tests.conftest import RoleEnv
from tests.rls_probe import Probe, build_probe

TABLES = ("rls_customers", "rls_cases", "rls_memberships")
RUNTIME = ("app", "worker")  # tenant-scoped runtime roles
ALL_NON_OWNER = ("app", "worker", "platform")


@pytest.fixture
def probe(role_env: RoleEnv) -> Iterator[Probe]:
    yield build_probe(role_env)


def scalar(engine: Engine, ctx: RequestContext, sql: str, **params: Any) -> Any:
    with session_scope(engine, ctx) as s:
        return s.execute(text(sql), params).scalar_one()


def rowcount(result: object) -> int:
    assert isinstance(result, CursorResult)
    return result.rowcount


# --- catalog assertions (role and FORCE RLS) -----------------------------------------------


def test_catalog_roles_and_force_rls(probe: Probe) -> None:
    for kind in ALL_NON_OWNER:
        engine = probe.env.engine(kind)
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, "
                    "pg_has_role(current_user, :o, 'MEMBER') FROM pg_roles "
                    "WHERE rolname = current_user"
                ),
                {"o": probe.env.names.owner},
            ).one()
        assert row == (getattr(probe.env.names, kind), False, False, False, False)
        engine.dispose()
    with probe.env.admin_engine().connect() as c:
        flags = c.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner) "
                "FROM pg_class WHERE relname LIKE 'rls\\_%' AND relkind = 'r'"
            )
        ).all()
        policies = c.execute(
            text("SELECT tablename, count(*) FROM pg_policies GROUP BY 1 ORDER BY 1")
        ).all()
    assert {f[0] for f in flags} == set(TABLES)
    assert all(f[1] and f[2] and f[3] == probe.env.names.owner for f in flags)
    assert dict(policies) == {"rls_cases": 1, "rls_customers": 1, "rls_memberships": 2}


# --- absent and invalid context fail closed ------------------------------------------------


@pytest.mark.parametrize("kind", RUNTIME)
def test_absent_context_returns_nothing(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    for table in TABLES:
        assert scalar(engine, RequestContext(), f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("kind", RUNTIME)
@pytest.mark.parametrize(
    ("setting", "value", "table"),
    [
        ("app.tenant_id", "not-a-uuid", "rls_customers"),
        ("app.tenant_id", "   ", "rls_cases"),
        ("app.tenant_id", "'; DROP TABLE rls_customers; --", "rls_customers"),
        ("app.user_id", "garbage", "rls_memberships"),
    ],
)
def test_invalid_context_fails_closed(
    probe: Probe, kind: str, setting: str, value: str, table: str
) -> None:
    engine = probe.env.engine(kind)
    # No valid tenant is set, so no permissive policy can short-circuit before the bad value.
    with pytest.raises(DBAPIError), session_scope(engine, RequestContext()) as s:
        s.execute(text("SELECT set_config(:n, :v, true)"), {"n": setting, "v": value})
        s.execute(text(f"SELECT * FROM {table}")).all()
    assert (
        scalar(
            probe.env.engine("owner"),
            probe.ctx(probe.tenant_a),
            "SELECT count(*) FROM rls_customers",
        )
        == 1
    )


# --- tenant A cannot reach tenant B --------------------------------------------------------


@pytest.mark.parametrize("kind", RUNTIME)
def test_tenant_a_cannot_read_b(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    ctx = probe.ctx(probe.tenant_a)
    assert (
        scalar(engine, ctx, "SELECT count(*) FROM rls_customers WHERE id = :i", i=probe.customer_b)
        == 0
    )
    for table in TABLES:
        assert (
            scalar(
                engine, ctx, f"SELECT count(*) FROM {table} WHERE tenant_id = :t", t=probe.tenant_b
            )
            == 0
        )
    with session_scope(engine, ctx) as s:
        seen = {r[0] for r in s.execute(text("SELECT tenant_id FROM rls_memberships"))}
    assert seen == {probe.tenant_a}


@pytest.mark.parametrize("kind", RUNTIME)
def test_forged_writes_by_a_against_b_are_rejected(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    ctx = probe.ctx(probe.tenant_a)
    with pytest.raises(ProgrammingError), session_scope(engine, ctx) as s:
        s.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'forged')"),
            {"t": probe.tenant_b},
        )
    with pytest.raises(ProgrammingError), session_scope(engine, ctx) as s:
        s.execute(text("UPDATE rls_customers SET tenant_id = :b"), {"b": probe.tenant_b})
    with session_scope(engine, ctx) as s:
        upd = s.execute(
            text("UPDATE rls_customers SET name = 'hacked' WHERE id = :i"), {"i": probe.customer_b}
        )
        dele = s.execute(text("DELETE FROM rls_customers WHERE id = :i"), {"i": probe.customer_b})
        assert (rowcount(upd), rowcount(dele)) == (0, 0)
    b_engine = probe.env.engine("app")
    with session_scope(b_engine, probe.ctx(probe.tenant_b)) as s:
        assert s.execute(text("SELECT name FROM rls_customers")).scalar_one() == "c"


@pytest.mark.parametrize("kind", RUNTIME)
def test_joins_and_subqueries_cannot_reveal_b(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    ctx = probe.ctx(probe.tenant_a)
    queries = {
        "full join": (
            "SELECT count(*) FROM rls_cases c FULL JOIN rls_customers k ON k.id = c.customer_id "
            "WHERE c.tenant_id = :b OR k.tenant_id = :b"
        ),
        "union": (
            "SELECT count(*) FROM (SELECT tenant_id FROM rls_customers UNION ALL "
            "SELECT tenant_id FROM rls_cases) u WHERE tenant_id = :b"
        ),
        "exists": (
            "SELECT count(*) FROM rls_customers WHERE EXISTS "
            "(SELECT 1 FROM rls_cases WHERE tenant_id = :b)"
        ),
        "in subquery": (
            "SELECT count(*) FROM rls_cases WHERE customer_id IN "
            "(SELECT id FROM rls_customers WHERE tenant_id = :b)"
        ),
        "cte": (
            "WITH x AS (SELECT * FROM rls_customers) SELECT count(*) FROM x WHERE tenant_id = :b"
        ),
    }
    for name, sql in queries.items():
        assert scalar(engine, ctx, sql, b=probe.tenant_b) == 0, name


# --- composite tenant foreign keys ---------------------------------------------------------


def test_composite_fk_rejects_cross_tenant_reference_even_when_fk_checks_bypass_rls(
    probe: Probe,
) -> None:
    owner = probe.env.engine("owner")
    with owner.begin() as c:  # a table with a PLAIN single-column FK, for contrast only
        c.execute(
            text(
                "CREATE TABLE rls_plain_fk (tenant_id uuid NOT NULL, "
                "customer_id uuid NOT NULL REFERENCES rls_customers (id)); "
                "ALTER TABLE rls_plain_fk ENABLE ROW LEVEL SECURITY; "
                "ALTER TABLE rls_plain_fk FORCE ROW LEVEL SECURITY; "
                "CREATE POLICY t ON rls_plain_fk USING (tenant_id = app_tenant_id()) "
                "WITH CHECK (tenant_id = app_tenant_id())"
            )
        )
    engine = probe.env.engine("app")
    ctx = probe.ctx(probe.tenant_a)
    # The FK check runs outside RLS, so a plain FK happily points at tenant B's invisible row.
    with session_scope(engine, ctx) as s:
        s.execute(
            text("INSERT INTO rls_plain_fk VALUES (:t, :c)"),
            {"t": probe.tenant_a, "c": probe.customer_b},
        )
    # The composite (tenant_id, id) FK of the real pattern closes that hole.
    with pytest.raises(IntegrityError), session_scope(engine, ctx) as s:
        s.execute(
            text("INSERT INTO rls_cases (tenant_id, customer_id) VALUES (:t, :c)"),
            {"t": probe.tenant_a, "c": probe.customer_b},
        )
    with pytest.raises(IntegrityError), session_scope(engine, ctx) as s:
        s.execute(text("UPDATE rls_cases SET customer_id = :c"), {"c": probe.customer_b})
    owner.dispose()


# --- positive controls ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", RUNTIME)
def test_positive_controls_own_tenant_access_works(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    for tenant, customer in (
        (probe.tenant_a, probe.customer_a),
        (probe.tenant_b, probe.customer_b),
    ):
        ctx = probe.ctx(tenant)
        with session_scope(engine, ctx) as s:  # valid same-tenant composite FK works
            new_customer = s.execute(
                text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'new') RETURNING id"),
                {"t": tenant},
            ).scalar_one()
            s.execute(
                text("INSERT INTO rls_cases (tenant_id, customer_id) VALUES (:t, :c)"),
                {"t": tenant, "c": new_customer},
            )
            upd = s.execute(
                text("UPDATE rls_customers SET name = 'renamed' WHERE id = :i"), {"i": customer}
            )
            assert rowcount(upd) == 1
        with session_scope(engine, ctx) as s:
            rows = s.execute(text("SELECT tenant_id FROM rls_customers")).all()
            assert [r[0] for r in rows] == [tenant, tenant]
            assert s.execute(text("SELECT count(*) FROM rls_cases")).scalar_one() == 2
        with session_scope(engine, ctx) as s:  # delete the new rows again
            s.execute(text("DELETE FROM rls_cases WHERE customer_id = :c"), {"c": new_customer})
            dele = s.execute(text("DELETE FROM rls_customers WHERE id = :c"), {"c": new_customer})
            assert rowcount(dele) == 1


# --- runtime roles cannot escalate or bypass RLS -------------------------------------------


@pytest.mark.parametrize("kind", ALL_NON_OWNER)
def test_runtime_roles_cannot_switch_role_disable_or_bypass_rls(probe: Probe, kind: str) -> None:
    engine = probe.env.engine(kind)
    me = getattr(probe.env.names, kind)
    statements = [
        f'SET ROLE "{probe.env.names.owner}"',
        f'SET SESSION AUTHORIZATION "{probe.env.names.owner}"',
        "ALTER TABLE rls_customers DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE rls_customers NO FORCE ROW LEVEL SECURITY",
        f'ALTER ROLE "{me}" BYPASSRLS',
        "DROP POLICY tenant_isolation ON rls_customers",
        "CREATE POLICY allow_all ON rls_customers USING (true)",
    ]
    for sql in statements:
        with pytest.raises(DBAPIError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
            s.execute(text(sql))
    if kind in RUNTIME:
        with pytest.raises(DBAPIError), session_scope(engine, probe.ctx(probe.tenant_a)) as s:
            s.execute(text("SET row_security = off"))
            s.execute(text("SELECT * FROM rls_customers")).all()
    with probe.env.admin_engine().connect() as c:  # nothing changed
        assert c.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'rls_customers'")
        ).scalar_one()
        assert (
            c.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename = 'rls_customers'")
            ).scalar_one()
            == 1
        )
        assert not c.execute(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": me}
        ).scalar_one()


# --- pool reuse does not leak context ------------------------------------------------------


@pytest.mark.parametrize("kind", RUNTIME)
def test_pool_reuse_after_commit_and_rollback_does_not_leak(probe: Probe, kind: str) -> None:
    engine = create_engine(probe.env.url(kind), pool_size=1, max_overflow=0)  # one connection
    ctx = RequestContext(tenant_id=probe.tenant_a, user_id=probe.user_a)
    with session_scope(engine, ctx) as s:
        pid = s.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert s.execute(text("SELECT count(*) FROM rls_customers")).scalar_one() == 1
    with pytest.raises(RuntimeError), session_scope(engine, ctx) as s:
        assert s.execute(text("SELECT count(*) FROM rls_customers")).scalar_one() == 1
        raise RuntimeError("rollback")
    for _ in range(2):
        with session_scope(engine) as s:
            assert s.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
            for table in TABLES:
                assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    with Session(engine) as raw:  # a commit inside a scope also drops the context
        apply_context(raw, ctx)
        assert raw.execute(text("SELECT count(*) FROM rls_customers")).scalar_one() == 1
        raw.commit()
        assert raw.execute(text("SELECT count(*) FROM rls_customers")).scalar_one() == 0
    engine.dispose()


# --- worker: independent, verified context -------------------------------------------------


def test_worker_uses_its_own_role_and_independent_context(probe: Probe) -> None:
    app_engine, worker_engine = probe.env.engine("app"), probe.env.engine("worker")
    with (
        session_scope(app_engine, probe.ctx(probe.tenant_b)) as a,
        session_scope(worker_engine, probe.ctx(probe.tenant_a)) as w,
    ):
        assert w.execute(text("SELECT current_user")).scalar_one() == probe.env.names.worker
        assert a.execute(text("SELECT current_user")).scalar_one() == probe.env.names.app
        a_rows = {r[0] for r in a.execute(text("SELECT tenant_id FROM rls_customers"))}
        w_rows = {r[0] for r in w.execute(text("SELECT tenant_id FROM rls_customers"))}
    assert (a_rows, w_rows) == ({probe.tenant_b}, {probe.tenant_a})


def test_worker_does_not_trust_tenant_id_from_a_message(probe: Probe) -> None:
    engine = probe.env.engine("worker")
    message = {"tenant_id": probe.tenant_b, "name": "from-message"}  # untrusted payload
    verified = RequestContext(tenant_id=probe.tenant_a)  # established server-side
    with pytest.raises(ProgrammingError), session_scope(engine, verified) as s:
        s.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, :n)"),
            {"t": message["tenant_id"], "n": message["name"]},
        )
    with session_scope(engine, verified) as s:  # the verified tenant is what authorises writes
        s.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, :n)"),
            {"t": verified.tenant_id, "n": message["name"]},
        )
    with session_scope(engine, probe.ctx(probe.tenant_b)) as s:
        assert s.execute(text("SELECT count(*) FROM rls_customers")).scalar_one() == 1


# --- platform: no arbitrary access ---------------------------------------------------------


def test_platform_has_no_arbitrary_access(probe: Probe) -> None:
    engine = probe.env.engine("platform")
    contexts = [
        RequestContext(),
        probe.ctx(probe.tenant_a),
        probe.ctx(probe.tenant_a, probe.user_a),
    ]
    for table in TABLES:
        for ctx in contexts:
            for sql in (
                f"SELECT * FROM {table}",
                f"DELETE FROM {table}",
                f"UPDATE {table} SET tenant_id = tenant_id",
                f"TRUNCATE {table}",
            ):
                with pytest.raises(ProgrammingError), session_scope(engine, ctx) as s:
                    s.execute(text(sql))
    with probe.env.admin_engine().connect() as c:
        granted = c.execute(
            text(
                "SELECT count(*) FROM unnest(CAST(:t AS text[])) AS tbl, "
                "unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES',"
                "'TRIGGER']) p "
                "WHERE has_table_privilege(:r, tbl, p)"
            ),
            {"t": list(TABLES), "r": probe.env.names.platform},
        ).scalar_one()
    assert granted == 0
    assert (
        scalar(
            probe.env.engine("owner"),
            probe.ctx(probe.tenant_a),
            "SELECT count(*) FROM rls_customers",
        )
        == 1
    )
