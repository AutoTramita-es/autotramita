"""Separate authentication bootstrap from user context and tighten audit isolation.

Revision ID: 0008
Revises: 0007
"""

from alembic import context, op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _policies(table: str, prefix: str) -> list[str]:
    return [
        str(row[0])
        for row in op.get_bind().exec_driver_sql(
            "SELECT policyname FROM pg_policies WHERE schemaname='public' "
            "AND tablename=%s AND policyname LIKE %s ORDER BY policyname",
            (table, prefix + "%"),
        )
    ]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _alter(table: str, prefix: str, using: str | None, check: str | None) -> None:
    for policy in _policies(table, prefix):
        clause = (f" USING ({using})" if using else "") + (
            f" WITH CHECK ({check})" if check else ""
        )
        op.execute(f"ALTER POLICY {_quote(policy)} ON {table}{clause}")


_USER = "(app_user_id() IS NOT NULL AND app_auth_subject() IS NULL AND app_session_hash() IS NULL)"
_AUTH_BOOT = (
    "(app_user_id() IS NULL AND app_session_hash() IS NULL AND app_tenant_id() IS NULL "
    "AND cardinality(app_branch_ids()) = 0 AND auth_subject = app_auth_subject())"
)
_SESS_BOOT = (
    "(app_user_id() IS NULL AND app_auth_subject() IS NULL AND app_tenant_id() IS NULL "
    "AND cardinality(app_branch_ids()) = 0 AND credential_hash = app_session_hash())"
)
_AUDIT_READ = (
    "(actor_user_id = app_user_id() OR subject_user_id = app_user_id()) "
    "AND category IN ('AUTHN','SESSION','SECURITY_SETTING')"
)
_AUDIT_INSERT = (
    "source = 'APP' AND (actor_user_id IS NULL OR actor_user_id = app_user_id()) "
    "AND (tenant_id IS NULL OR tenant_id = app_tenant_id())"
)
# Anonymous events are written without a user; a user context never carries a bootstrap proof.
_UNMIXED = "(app_user_id() IS NULL OR (app_auth_subject() IS NULL AND app_session_hash() IS NULL))"
_SESSION_INSERT = (
    "user_id = app_user_id() AND EXISTS (SELECT 1 FROM users u WHERE u.id = user_id "
    "AND u.status IN ('ACTIVE','PENDING_VERIFICATION'))"
)
_D37_INSERT = (
    "user_id = app_user_id() AND EXISTS (SELECT 1 FROM user_sessions s "
    "WHERE s.id = session_id AND s.user_id = app_user_id() AND s.revoked_at IS NULL)"
)


# Direct privileges and policies on application objects: tables, columns, sequences, functions,
# the schema itself and row-level security. grantee 0 is PUBLIC.
_GRANTEES = """
WITH mine AS (SELECT oid FROM pg_roles WHERE rolname = current_user),
grantees AS (
    SELECT a.grantee FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(c.relacl) a
    WHERE n.nspname = 'public' AND c.relowner = (SELECT oid FROM mine)
    UNION
    SELECT a.grantee FROM pg_attribute col JOIN pg_class c ON c.oid = col.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(col.attacl) a
    WHERE n.nspname = 'public' AND c.relowner = (SELECT oid FROM mine)
    UNION
    SELECT a.grantee FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    CROSS JOIN LATERAL aclexplode(p.proacl) a
    WHERE n.nspname = 'public' AND p.proowner = (SELECT oid FROM mine) AND a.grantee <> 0
    UNION
    SELECT a.grantee FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
    WHERE n.nspname = 'public'
    UNION
    SELECT g.role FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL unnest(p.polroles) AS g(role)
    WHERE n.nspname = 'public' AND c.relowner = (SELECT oid FROM mine)
)
SELECT coalesce(r.rolname, 'PUBLIC') FROM grantees g LEFT JOIN pg_roles r ON r.oid = g.grantee
WHERE r.rolname IS DISTINCT FROM current_user
"""


def _reject_historical_grants() -> None:
    """Earlier migrations and operators may have granted something to a role that is not one of
    the configured ones, even one that cannot connect today, or to PUBLIC: refuse (R07)."""
    names = set(context.config.attributes["expected_runtime_roles"].values())
    found = {str(row[0]) for row in op.get_bind().exec_driver_sql(_GRANTEES)}
    if found - names:
        raise RuntimeError("unconfigured role has historical database privileges")


def upgrade() -> None:
    _reject_historical_grants()
    user_visibility = f"({_USER} AND id = app_user_id()) OR {_AUTH_BOOT}"
    session_visibility = f"({_USER} AND user_id = app_user_id()) OR {_SESS_BOOT}"
    _alter("users", "users_select_own_", user_visibility, None)
    # SELECT FOR SHARE also needs the UPDATE policy to expose the row to bootstrap.
    _alter("users", "users_update_own_", user_visibility, user_visibility)
    _alter(
        "users",
        "users_insert_first_login_",
        None,
        f"{_AUTH_BOOT} AND status IN ('PENDING_VERIFICATION','ACTIVE') "
        "AND status_changed_by IS NULL",
    )
    _alter("user_sessions", "sessions_select_", session_visibility, None)
    _alter("user_sessions", "sessions_update_", session_visibility, session_visibility)
    _alter("user_sessions", "sessions_insert_", None, f"{_USER} AND {_SESSION_INSERT}")
    own = f"{_USER} AND user_id = app_user_id()"
    _alter("email_change_operations", "email_change_app_read_", own, None)
    _alter(
        "email_change_operations", "email_change_app_insert_", None, f"{_USER} AND {_D37_INSERT}"
    )
    _alter(
        "email_change_operations",
        "email_change_app_update_",
        f"{own} AND status = 'PENDING'",
        f"{own} AND status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')",
    )
    _alter(
        "audit_events",
        "audit_read_own_",
        f"{_USER} AND {_AUDIT_READ} AND (tenant_id IS NULL OR tenant_id = app_tenant_id())",
        None,
    )
    _alter(
        "audit_events",
        "audit_insert_app_",
        None,
        f"{_UNMIXED} AND {_AUDIT_INSERT} AND "
        "(branch_id IS NULL OR (tenant_id IS NOT NULL AND branch_id = ANY(app_branch_ids())))",
    )
    # Restrict every function owned by this application migration owner, including trigger
    # functions, without changing extensions or functions owned by other database roles.
    functions = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT format('%%I.%%I(%%s)', n.nspname, p.proname, "
            "pg_get_function_identity_arguments(p.oid)) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proowner=(SELECT oid FROM pg_roles "
            "WHERE rolname=current_user)"
        )
        .scalars()
        .all()
    )
    for function in functions:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM PUBLIC")
    # A worker writes system and identity-provider events only, never in a person's name.
    _alter(
        "audit_events",
        "audit_insert_worker_",
        None,
        "((actor_type='SYSTEM' AND source='APP') OR (actor_type='IDP' AND source='KEYCLOAK')) "
        "AND actor_user_id IS NULL AND actor_session_id IS NULL "
        "AND (branch_id IS NULL OR tenant_id IS NOT NULL)",
    )
    # Existing audit rows are deliberately validated: unsafe legacy data blocks migration and
    # must be assessed separately; the append-only table is never silently rewritten.
    op.execute(r"""
        ALTER TABLE audit_events ADD CONSTRAINT audit_no_raw_ip_or_aux_secrets CHECK (
            concat_ws(' ', details::text, target_type, ua_family, source_event_id)
              !~* '([0-9]{1,3}[.]){3}[0-9]{1,3}|([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}|'
                  'password|passwd|secret|authorization|cookie|code_verifier|id_token|'
                  'refresh_token|access_token|client_secret|bearer |'
                  '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}|[A-Za-z0-9_-]{43,}'
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_no_raw_ip_or_aux_secrets")
    _alter("audit_events", "audit_insert_worker_", None, "actor_type IN ('SYSTEM','IDP')")
    mine = "id = app_user_id() OR auth_subject = app_auth_subject()"
    sessions = "user_id = app_user_id() OR credential_hash = app_session_hash()"
    _alter("users", "users_select_own_", mine, None)
    _alter("users", "users_update_own_", mine, mine)
    _alter(
        "users",
        "users_insert_first_login_",
        None,
        "auth_subject = app_auth_subject() AND status IN ('PENDING_VERIFICATION','ACTIVE') "
        "AND status_changed_by IS NULL",
    )
    _alter("user_sessions", "sessions_select_", sessions, None)
    _alter("user_sessions", "sessions_update_", sessions, sessions)
    _alter("user_sessions", "sessions_insert_", None, _SESSION_INSERT)
    own = "user_id = app_user_id()"
    _alter("email_change_operations", "email_change_app_read_", own, None)
    _alter("email_change_operations", "email_change_app_insert_", None, _D37_INSERT)
    _alter(
        "email_change_operations",
        "email_change_app_update_",
        f"{own} AND status = 'PENDING'",
        f"{own} AND status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')",
    )
    _alter("audit_events", "audit_read_own_", _AUDIT_READ, None)
    _alter("audit_events", "audit_insert_app_", None, _AUDIT_INSERT)
    # PUBLIC did not have EXECUTE under the required harden.sql default privileges.
