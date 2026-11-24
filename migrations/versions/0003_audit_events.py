"""Audit events (F2-T03, decisions D31 and G5-06).

One append-only table for tenant and platform scope. Protection in depth: no UPDATE, DELETE
or TRUNCATE privilege for any runtime role, a trigger that refuses them for everyone else
(including a superuser; only dropping the table or trigger as the owner can lift it, which is
a schema change and is itself auditable), forced row-level security, narrow INSERT policies
per role, and CHECK constraints that keep secrets, e-mail addresses and full IP addresses out.
No foreign key to users: an audit record must outlive the person (retention is AT-20, D42).

The platform role gets no privilege and no policy here; its read path arrives with the grants
of F2-T10. The worker may insert only system and identity-provider events and cannot read.

Revision ID: 0003
Revises: 0002
"""

from alembic import context, op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

CATEGORIES = "'AUTHN','SESSION','SECURITY_SETTING','AUTHZ','ADMIN','ACCESS_DENIED','IDENTITY'"
# Words and shapes that must never appear in the free-form details column.
FORBIDDEN_DETAILS = (
    "(password|passwd|secret|authorization|cookie|code_verifier|id_token|refresh_token|"
    "access_token|client_secret|bearer |eyJ[A-Za-z0-9_-]{10,}[.]|"
    "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,})"
)


def _quote(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def _roles(suffix: str) -> list[str]:
    """The explicitly configured runtime role of this kind (R07), verified by ``env.py``."""
    return [context.config.attributes["expected_runtime_roles"][suffix]]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE audit_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            scope text NOT NULL CHECK (scope IN ('TENANT','PLATFORM')),
            category text NOT NULL CHECK (category IN ({CATEGORIES})),
            action text NOT NULL CHECK (
                length(action) <= 80 AND action ~ '^[a-z][a-z0-9_]*([.][a-z][a-z0-9_]*)+$'),
            outcome text NOT NULL CHECK (outcome IN ('SUCCESS','FAILURE','DENIED')),
            actor_type text NOT NULL CHECK (actor_type IN ('USER','SYSTEM','IDP','ANONYMOUS')),
            actor_user_id uuid,
            actor_session_id uuid,
            subject_user_id uuid,
            tenant_id uuid,
            branch_id uuid,
            target_type text CHECK (target_type IS NULL OR length(target_type) <= 40),
            target_id uuid,
            request_id uuid,
            ip_prefix cidr CHECK (
                ip_prefix IS NULL
                OR (family(ip_prefix) = 4 AND masklen(ip_prefix) <= 24)
                OR (family(ip_prefix) = 6 AND masklen(ip_prefix) <= 48)),
            ua_family text CHECK (ua_family IS NULL OR length(ua_family) <= 40),
            reason_code text CHECK (
                reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{{0,59}}$'),
            details jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (
                jsonb_typeof(details) = 'object'
                AND length(details::text) <= 4096
                AND details::text !~* '{FORBIDDEN_DETAILS}'),
            schema_version smallint NOT NULL DEFAULT 1,
            source text NOT NULL DEFAULT 'APP' CHECK (source IN ('APP','KEYCLOAK')),
            source_event_id text CHECK (source_event_id IS NULL OR length(source_event_id) <= 200),
            CONSTRAINT audit_scope_tenant CHECK (scope <> 'TENANT' OR tenant_id IS NOT NULL),
            CONSTRAINT audit_user_actor CHECK (actor_type <> 'USER' OR actor_user_id IS NOT NULL),
            CONSTRAINT audit_anonymous_actor CHECK (
                actor_type <> 'ANONYMOUS' OR actor_user_id IS NULL),
            CONSTRAINT audit_source_dedup UNIQUE (source, source_event_id)
        )
        """
    )
    op.execute("CREATE INDEX audit_events_time ON audit_events (occurred_at DESC)")
    op.execute(
        "CREATE INDEX audit_events_actor ON audit_events (actor_user_id, occurred_at DESC) "
        "WHERE actor_user_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX audit_events_subject ON audit_events (subject_user_id, occurred_at DESC) "
        "WHERE subject_user_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX audit_events_action ON audit_events (category, action, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX audit_events_tenant ON audit_events (tenant_id, occurred_at DESC) "
        "WHERE tenant_id IS NOT NULL"
    )

    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")

    # Append-only, also against roles that hold the privilege or bypass row security.
    op.execute(
        "CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = '42501'; END $$"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )

    app_roles, worker_roles, platform_roles = _roles("app"), _roles("worker"), _roles("platform")
    # Default privileges gave app and worker DML; start from nothing and grant exactly what is
    # needed. UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER stay unavailable to every role.
    for role in (*app_roles, *worker_roles, *platform_roles):
        op.execute(f"REVOKE ALL ON audit_events FROM {_quote(role)}")
    for number, role in enumerate(app_roles):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT, INSERT ON audit_events TO {quoted}")
        op.execute(
            f"CREATE POLICY audit_insert_app_{number} ON audit_events FOR INSERT TO {quoted} "
            "WITH CHECK (source = 'APP' "
            "AND (actor_user_id IS NULL OR actor_user_id = app_user_id()) "
            "AND (tenant_id IS NULL OR tenant_id = app_tenant_id()))"
        )
        # A person reads only their own security trail (authentication, sessions, settings).
        op.execute(
            f"CREATE POLICY audit_read_own_{number} ON audit_events FOR SELECT TO {quoted} "
            "USING ((actor_user_id = app_user_id() OR subject_user_id = app_user_id()) "
            "AND category IN ('AUTHN','SESSION','SECURITY_SETTING'))"
        )
    for number, role in enumerate(worker_roles):
        quoted = _quote(role)
        op.execute(f"GRANT INSERT ON audit_events TO {quoted}")
        op.execute(
            f"CREATE POLICY audit_insert_worker_{number} ON audit_events FOR INSERT TO {quoted} "
            "WITH CHECK (actor_type IN ('SYSTEM','IDP'))"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
