"""Application sessions (F2-T05; AT-02 section 6, decisions D12, D15, D16, D24).

A session is the application's record that a signed-in person may act, validated on every
request (ADR-010). Only the SHA-256 of the web credential is stored. Rules kept by the
database itself:

* a row is visible to its owner, or to a caller that knows the credential (D17 bootstrap);
* immutable columns cannot change; a revoked session is final; rows are never deleted;
* new sessions are only created for users that may still sign in (not DEACTIVATED/BLOCKED);
* the application role may change context, step-up state, credential (rotation), activity
  and revocation; the worker (system) may only revoke; the platform role has no access until
  its grants exist (F2-T10).

``active_*`` columns carry no foreign key: tenants and memberships arrive with F3a.

Revision ID: 0005
Revises: 0004
"""

from alembic import context, op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

REVOKE_REASONS = (
    "'LOGOUT','USER_REVOKED','IDLE_TIMEOUT','ABSOLUTE_TIMEOUT','PASSWORD_CHANGED',"
    "'ACCOUNT_DEACTIVATED','ACCOUNT_BLOCKED','ADMIN_REVOKED','IDP_LOGOUT','MEMBERSHIP_REVOKED',"
    "'SECURITY_POLICY','REPLAY_DETECTED','REFRESH_REUSE','SESSION_LIMIT'"
)
APP_UPDATE_COLUMNS = (
    "credential_hash, active_tenant_id, active_branch_id, active_membership_id, "
    "context_version, auth_level, step_up_at, country_code, last_activity_at, idle_expires_at, "
    "revoked_at, revoked_reason, revoked_by, version"
)
WORKER_UPDATE_COLUMNS = "revoked_at, revoked_reason, revoked_by, version"


def _quote(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def _roles(suffix: str) -> list[str]:
    """The explicitly configured runtime role of this kind (R07), verified by ``env.py``."""
    return [context.config.attributes["expected_runtime_roles"][suffix]]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE user_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users (id),
            client_type text NOT NULL CHECK (client_type IN ('WEB','ADMIN_WEB','MOBILE')),
            credential_hash bytea CHECK (
                credential_hash IS NULL OR octet_length(credential_hash) = 32),
            kc_session_id text NOT NULL CHECK (kc_session_id ~ '^[A-Za-z0-9._:-]{{1,128}}$'),
            active_tenant_id uuid,
            active_branch_id uuid,
            active_membership_id uuid,
            context_version integer NOT NULL DEFAULT 1 CHECK (context_version >= 1),
            auth_time timestamptz NOT NULL,
            auth_level text NOT NULL DEFAULT 'LOA1' CHECK (auth_level IN ('LOA1','LOA2')),
            step_up_at timestamptz,
            device_label text CHECK (device_label IS NULL OR length(device_label) <= 80),
            platform text CHECK (
                platform IS NULL OR platform ~ '^[A-Za-z0-9._:-]{{1,40}}$'),
            app_version text CHECK (
                app_version IS NULL OR app_version ~ '^[A-Za-z0-9._+-]{{1,40}}$'),
            ua_family text CHECK (ua_family IS NULL OR length(ua_family) <= 40),
            ip_prefix cidr CHECK (
                ip_prefix IS NULL
                OR (family(ip_prefix) = 4 AND masklen(ip_prefix) <= 24)
                OR (family(ip_prefix) = 6 AND masklen(ip_prefix) <= 48)),
            country_code text CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{{2}}$'),
            created_at timestamptz NOT NULL DEFAULT now(),
            last_activity_at timestamptz NOT NULL DEFAULT now(),
            idle_expires_at timestamptz NOT NULL,
            absolute_expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            revoked_reason text CHECK (
                revoked_reason IS NULL OR revoked_reason IN ({REVOKE_REASONS})),
            revoked_by uuid,
            version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            CONSTRAINT user_sessions_credential_key UNIQUE (credential_hash),
            CONSTRAINT user_sessions_kc_session_key UNIQUE (kc_session_id, client_type),
            CONSTRAINT user_sessions_web_has_credential CHECK (
                (client_type = 'MOBILE') = (credential_hash IS NULL)),
            CONSTRAINT user_sessions_lifetimes CHECK (
                absolute_expires_at > created_at AND idle_expires_at <= absolute_expires_at),
            CONSTRAINT user_sessions_revocation_pair CHECK (
                (revoked_at IS NULL) = (revoked_reason IS NULL)),
            CONSTRAINT user_sessions_step_up_level CHECK (
                auth_level <> 'LOA2' OR step_up_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX user_sessions_user ON user_sessions (user_id, created_at)")
    op.execute(
        "CREATE INDEX user_sessions_live ON user_sessions (user_id) WHERE revoked_at IS NULL"
    )
    op.execute("CREATE INDEX user_sessions_idle ON user_sessions (idle_expires_at)")
    op.execute("ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_sessions FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE FUNCTION user_sessions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.client_type IS DISTINCT FROM OLD.client_type
               OR NEW.kc_session_id IS DISTINCT FROM OLD.kc_session_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.absolute_expires_at IS DISTINCT FROM OLD.absolute_expires_at
               OR NEW.auth_time IS DISTINCT FROM OLD.auth_time THEN
                RAISE EXCEPTION 'immutable session column' USING ERRCODE = '23514';
            END IF;
            IF OLD.revoked_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'a revoked session is final' USING ERRCODE = '23514';
            END IF;
            IF NEW.credential_hash IS DISTINCT FROM OLD.credential_hash
               AND (NEW.credential_hash IS NULL OR OLD.credential_hash IS NULL) THEN
                RAISE EXCEPTION 'the credential can only be rotated' USING ERRCODE = '23514';
            END IF;
            IF NEW.context_version < OLD.context_version THEN
                RAISE EXCEPTION 'context_version never decreases' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER user_sessions_guard BEFORE UPDATE ON user_sessions "
        "FOR EACH ROW EXECUTE FUNCTION user_sessions_guard()"
    )
    op.execute(
        "CREATE FUNCTION user_sessions_never_deleted() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'sessions are never deleted' USING ERRCODE = '42501'; END $$"
    )
    op.execute(
        "CREATE TRIGGER user_sessions_no_delete BEFORE DELETE ON user_sessions "
        "FOR EACH ROW EXECUTE FUNCTION user_sessions_never_deleted()"
    )
    op.execute(
        "CREATE TRIGGER user_sessions_no_truncate BEFORE TRUNCATE ON user_sessions "
        "FOR EACH STATEMENT EXECUTE FUNCTION user_sessions_never_deleted()"
    )

    app_roles, worker_roles, platform_roles = _roles("app"), _roles("worker"), _roles("platform")
    for role in (*app_roles, *worker_roles, *platform_roles):
        op.execute(f"REVOKE ALL ON user_sessions FROM {_quote(role)}")
    for number, role in enumerate(app_roles):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT, INSERT ON user_sessions TO {quoted}")
        op.execute(f"GRANT UPDATE ({APP_UPDATE_COLUMNS}) ON user_sessions TO {quoted}")
        mine = "user_id = app_user_id() OR credential_hash = app_session_hash()"
        op.execute(
            f"CREATE POLICY sessions_select_{number} ON user_sessions FOR SELECT TO {quoted} "
            f"USING ({mine})"
        )
        op.execute(
            f"CREATE POLICY sessions_update_{number} ON user_sessions FOR UPDATE TO {quoted} "
            f"USING ({mine}) WITH CHECK ({mine})"
        )
        # Only people who may still sign in get new sessions (the users row is visible to its
        # owner through its own policy).
        op.execute(
            f"CREATE POLICY sessions_insert_{number} ON user_sessions FOR INSERT TO {quoted} "  # noqa: S608
            "WITH CHECK (user_id = app_user_id() AND EXISTS ("
            "SELECT 1 FROM users u WHERE u.id = user_id "
            "AND u.status IN ('ACTIVE','PENDING_VERIFICATION')))"
        )
    for number, role in enumerate(worker_roles):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT ON user_sessions TO {quoted}")
        op.execute(f"GRANT UPDATE ({WORKER_UPDATE_COLUMNS}) ON user_sessions TO {quoted}")
        op.execute(
            f"CREATE POLICY sessions_system_read_{number} ON user_sessions FOR SELECT TO {quoted} "
            "USING (true)"
        )
        op.execute(
            f"CREATE POLICY sessions_system_revoke_{number} ON user_sessions FOR UPDATE "
            f"TO {quoted} USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_sessions")
    op.execute("DROP FUNCTION IF EXISTS user_sessions_never_deleted()")
    op.execute("DROP FUNCTION IF EXISTS user_sessions_guard()")
