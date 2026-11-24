"""One live session per Keycloak session and client type (F2-T06).

Signing in again while the Keycloak single-sign-on session is still alive returns the same
``sid``. The unique constraint of 0005 then blocked a second sign-in after a logout. Only the
live row has to be unique; a new sign-in supersedes (revokes) the previous live one in the
service. Revoked rows stay as history.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_sessions DROP CONSTRAINT user_sessions_kc_session_key")
    op.execute(
        "CREATE UNIQUE INDEX user_sessions_kc_session_live ON user_sessions "
        "(kc_session_id, client_type) WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS user_sessions_kc_session_live")
    op.execute(
        "ALTER TABLE user_sessions ADD CONSTRAINT user_sessions_kc_session_key "
        "UNIQUE (kc_session_id, client_type)"
    )
