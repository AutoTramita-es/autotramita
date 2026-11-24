"""Probe schema used only by tests to prove the RLS pattern required by ADR-002.

It mirrors the shape business tables will use: tenant_id on every row, composite
(tenant_id, id) keys and foreign keys, ENABLE plus FORCE row level security, policies with
both USING and WITH CHECK, and a user-owned lookup policy for membership bootstrapping (G5-02).
It is created by the owner role in test databases and is never part of the migration chain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from tests.conftest import RoleEnv

DDL = """
CREATE TABLE rls_customers (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name text NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (tenant_id, id)
);
CREATE TABLE rls_cases (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (tenant_id, customer_id) REFERENCES rls_customers (tenant_id, id)
);
CREATE TABLE rls_memberships (
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    PRIMARY KEY (tenant_id, user_id)
);
ALTER TABLE rls_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE rls_customers FORCE ROW LEVEL SECURITY;
ALTER TABLE rls_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE rls_cases FORCE ROW LEVEL SECURITY;
ALTER TABLE rls_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE rls_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON rls_customers
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
CREATE POLICY tenant_isolation ON rls_cases
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
CREATE POLICY tenant_isolation ON rls_memberships
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
-- Membership bootstrapping: before a tenant is chosen, a user may read only their own rows.
CREATE POLICY own_memberships ON rls_memberships FOR SELECT USING (user_id = app_user_id());
"""


@dataclass(frozen=True)
class Probe:
    env: RoleEnv
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID
    customer_a: uuid.UUID
    customer_b: uuid.UUID

    def ctx(self, tenant: uuid.UUID | None = None, user: uuid.UUID | None = None) -> RequestContext:
        return RequestContext(tenant_id=tenant, user_id=user)


def build_probe(env: RoleEnv) -> Probe:
    from tests.test_roles_and_migrations import migrate

    owner = env.engine("owner")
    migrate(owner, "upgrade", "head")
    with owner.begin() as conn:
        conn.execute(text(DDL))
    a, b, ua, ub = (uuid.uuid4() for _ in range(4))
    customers: dict[uuid.UUID, uuid.UUID] = {}
    # Seed as the owner role: FORCE RLS applies to it too, so context is required here as well.
    for tenant, user in ((a, ua), (b, ub)):
        with session_scope(owner, RequestContext(tenant_id=tenant, user_id=user)) as s:
            cid = s.execute(
                text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, 'c') RETURNING id"),
                {"t": tenant},
            ).scalar_one()
            customers[tenant] = cid
            s.execute(
                text("INSERT INTO rls_cases (tenant_id, customer_id) VALUES (:t, :c)"),
                {"t": tenant, "c": cid},
            )
            s.execute(
                text("INSERT INTO rls_memberships VALUES (:t, :u, 'OWNER')"),
                {"t": tenant, "u": user},
            )
    # A second tenant membership for user A, to test the self-lookup across tenants.
    with session_scope(owner, RequestContext(tenant_id=b, user_id=ua)) as s:
        s.execute(text("INSERT INTO rls_memberships VALUES (:t, :u, 'VIEWER')"), {"t": b, "u": ua})
    owner.dispose()
    return Probe(env, a, b, ua, ub, customers[a], customers[b])
