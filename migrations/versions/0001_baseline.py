"""Baseline: request-context helper functions for row-level security.

Revision ID: 0001
Revises:
"""

from alembic import context, op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Values are set with transaction-local set_config(); an unset or empty value means "none".
    op.execute(
        "CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_branch_ids() RETURNS uuid[] LANGUAGE sql STABLE AS "
        "$$ SELECT coalesce(string_to_array(nullif(current_setting('app.branch_ids', true), ''), "
        "',')::uuid[], '{}'::uuid[]) $$"
    )
    # Default privileges (harden.sql) withhold EXECUTE from PUBLIC; grant it to the other
    # roles of this database explicitly: the configured names (R07), verified by ``env.py``.
    names = context.config.attributes["expected_runtime_roles"]
    for role in (names["app"], names["worker"], names["platform"]):
        quoted = '"' + role.replace('"', '""') + '"'
        op.execute(
            "GRANT EXECUTE ON FUNCTION app_user_id(), app_tenant_id(), "
            f"app_branch_ids() TO {quoted}"
        )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_branch_ids()")
    op.execute("DROP FUNCTION IF EXISTS app_tenant_id()")
    op.execute("DROP FUNCTION IF EXISTS app_user_id()")
