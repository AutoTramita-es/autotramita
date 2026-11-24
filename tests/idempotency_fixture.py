"""Disposable fixture tables for the idempotency tests (owner decision for F1-T06).

Created by the owner role in the test database only; never part of the migration chain.
``idempotency_keys`` has the shape the future business migration is expected to use.
``idem_things`` stands in for a business table written by a handler.
"""

from __future__ import annotations

from sqlalchemy import Engine, text
from tests.conftest import RoleEnv

DDL = """
CREATE TABLE idempotency_keys (
    tenant_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    operation text NOT NULL,
    key text NOT NULL,
    fingerprint text NOT NULL,
    status_code integer NOT NULL,
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, actor_id, operation, key)
);
CREATE INDEX idempotency_keys_expires_at ON idempotency_keys (expires_at);
CREATE TABLE idem_things (
    tenant_id uuid NOT NULL DEFAULT app_tenant_id(),
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    name text NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE idem_things ENABLE ROW LEVEL SECURITY;
ALTER TABLE idem_things FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON idempotency_keys
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
CREATE POLICY tenant_isolation ON idem_things
    USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
"""


def build_idempotency_fixture(env: RoleEnv) -> Engine:
    """Migrate (context functions), create the fixture tables as owner, return the app engine."""
    from tests.test_roles_and_migrations import migrate

    owner = env.engine("owner")
    migrate(owner, "upgrade", "head")
    with owner.begin() as conn:
        conn.execute(text(DDL))
    owner.dispose()
    return env.engine("app")
