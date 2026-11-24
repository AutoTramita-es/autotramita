"""Idempotency keys for consequential writes (ADR-004), tenant-scoped under RLS.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NO_TENANT = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    # tenant_id is NOT NULL so it can be part of the primary key; the all-zero uuid means
    # "no tenant context" (public endpoints). Rows are visible only under the same context.
    op.execute(
        f"""
        CREATE TABLE idempotency_keys (
            tenant_id uuid NOT NULL DEFAULT '{NO_TENANT}',
            scope text NOT NULL,
            key text NOT NULL,
            request_hash text NOT NULL,
            state text NOT NULL CHECK (state IN ('in_progress', 'completed')),
            status_code integer,
            response_body jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, scope, key)
        )
        """
    )
    op.execute("CREATE INDEX idempotency_keys_expires_at ON idempotency_keys (expires_at)")
    op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON idempotency_keys
            USING (tenant_id = coalesce(app_tenant_id(), '{NO_TENANT}'::uuid))
            WITH CHECK (tenant_id = coalesce(app_tenant_id(), '{NO_TENANT}'::uuid))
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
