"""Authentication bootstrap context (F2-T03, decision D17).

Two additional transaction-local settings let row-level security recognise the row that a
caller proves knowledge of before ``app.user_id`` is known: the identity-provider subject at
first sign-in and the hash of a session secret on every later request. They are only readable
helpers; nothing is granted by them and an unset value means "none". Additive: the three
settings of 0001 are unchanged.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION app_auth_subject() RETURNS text LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.auth_subject', true), '') $$"
    )
    # Stored as lower-case hex in the setting; an unset value yields NULL (never an error).
    op.execute(
        "CREATE FUNCTION app_session_hash() RETURNS bytea LANGUAGE sql STABLE AS "
        "$$ SELECT decode(nullif(current_setting('app.session_hash', true), ''), 'hex') $$"
    )
    bind = op.get_bind()
    roles = [
        row[0]
        for row in bind.exec_driver_sql(
            "SELECT rolname FROM pg_roles WHERE rolname ~ '_(app|worker|platform)$' "
            "AND has_database_privilege(rolname, current_database(), 'CONNECT')"
        )
    ]
    for role in roles:
        quoted = '"' + role.replace('"', '""') + '"'
        op.execute(f"GRANT EXECUTE ON FUNCTION app_auth_subject(), app_session_hash() TO {quoted}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_session_hash()")
    op.execute("DROP FUNCTION IF EXISTS app_auth_subject()")
