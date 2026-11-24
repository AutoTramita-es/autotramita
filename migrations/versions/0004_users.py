"""Global users (F2-T04; AT-02 section 5, decisions D09, D10, D36).

``users`` is the global login identity (ADR-003): no tenant, customer, role or membership
column. Rules enforced by the database, not only by code:

* ``auth_subject`` (the Keycloak ``sub``) and ``email_normalized`` are unique; the subject
  never changes;
* status moves only along the allowed transitions; ``ACTIVE`` requires a verified e-mail;
  verifying the e-mail of a pending user activates it automatically;
* the application role cannot touch status at all (column privileges); status is changed by
  the worker (system context) now and by the platform role once its grants exist (F2-T10);
* a row is visible to the person it belongs to, or to a caller that proves the Keycloak
  subject during sign-in (D17); never to anybody else;
* rows are never deleted (anonymisation is AT-20).

Revision ID: 0004
Revises: 0003
"""

from alembic import context, op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_UPDATE_COLUMNS = (
    "email, email_normalized, email_verified_at, display_name, preferred_language, "
    "last_login_at, updated_at, version"
)
STATUS_UPDATE_COLUMNS = (
    "status, status_reason, status_changed_at, status_changed_by, updated_at, version"
)


def _quote(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def _roles(suffix: str) -> list[str]:
    """The explicitly configured runtime role of this kind (R07), verified by ``env.py``."""
    return [context.config.attributes["expected_runtime_roles"][suffix]]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            auth_subject text NOT NULL CHECK (auth_subject ~ '^[A-Za-z0-9._:-]{1,128}$'),
            email text NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
            email_normalized text NOT NULL CHECK (length(email_normalized) BETWEEN 3 AND 320),
            email_verified_at timestamptz,
            status text NOT NULL CHECK (
                status IN ('PENDING_VERIFICATION','ACTIVE','DEACTIVATED','BLOCKED')),
            status_reason text CHECK (
                status_reason IS NULL OR status_reason ~ '^[A-Z][A-Z0-9_]{0,59}$'),
            status_changed_at timestamptz NOT NULL DEFAULT now(),
            status_changed_by uuid,
            display_name text CHECK (
                display_name IS NULL OR length(display_name) BETWEEN 1 AND 120),
            preferred_language text NOT NULL DEFAULT 'es' CHECK (
                preferred_language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
            last_login_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            CONSTRAINT users_auth_subject_key UNIQUE (auth_subject),
            CONSTRAINT users_email_normalized_key UNIQUE (email_normalized),
            CONSTRAINT users_active_needs_verified_email CHECK (
                status <> 'ACTIVE' OR email_verified_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX users_status ON users (status)")
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE FUNCTION users_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.auth_subject IS DISTINCT FROM OLD.auth_subject THEN
                RAISE EXCEPTION 'id and auth_subject are immutable' USING ERRCODE = '23514';
            END IF;
            -- Verifying the e-mail of a pending user activates it (unless the same statement
            -- sets another status explicitly).
            IF OLD.status = 'PENDING_VERIFICATION' AND NEW.status = OLD.status
               AND OLD.email_verified_at IS NULL AND NEW.email_verified_at IS NOT NULL THEN
                NEW.status := 'ACTIVE';
                NEW.status_reason := NULL;
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF NOT ((OLD.status, NEW.status) IN (
                    ('PENDING_VERIFICATION','ACTIVE'), ('PENDING_VERIFICATION','BLOCKED'),
                    ('ACTIVE','DEACTIVATED'), ('ACTIVE','BLOCKED'),
                    ('DEACTIVATED','ACTIVE'), ('DEACTIVATED','BLOCKED'),
                    ('BLOCKED','ACTIVE'), ('BLOCKED','DEACTIVATED'))) THEN
                    RAISE EXCEPTION 'invalid status transition' USING ERRCODE = '23514';
                END IF;
                NEW.status_changed_at := now();
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER users_guard BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION users_guard()"
    )
    op.execute(
        "CREATE FUNCTION users_never_deleted() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'users are never deleted' USING ERRCODE = '42501'; END $$"
    )
    op.execute(
        "CREATE TRIGGER users_no_delete BEFORE DELETE ON users "
        "FOR EACH ROW EXECUTE FUNCTION users_never_deleted()"
    )
    op.execute(
        "CREATE TRIGGER users_no_truncate BEFORE TRUNCATE ON users "
        "FOR EACH STATEMENT EXECUTE FUNCTION users_never_deleted()"
    )

    app_roles, worker_roles, platform_roles = _roles("app"), _roles("worker"), _roles("platform")
    # Start from nothing (default privileges granted table-wide DML) and grant exactly what
    # is needed. No role may DELETE or TRUNCATE; the platform role gets nothing until F2-T10.
    for role in (*app_roles, *worker_roles, *platform_roles):
        op.execute(f"REVOKE ALL ON users FROM {_quote(role)}")
    for number, role in enumerate(app_roles):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT, INSERT ON users TO {quoted}")
        op.execute(f"GRANT UPDATE ({APP_UPDATE_COLUMNS}) ON users TO {quoted}")
        mine = "id = app_user_id() OR auth_subject = app_auth_subject()"
        op.execute(
            f"CREATE POLICY users_select_own_{number} ON users FOR SELECT TO {quoted} "
            f"USING ({mine})"
        )
        op.execute(
            f"CREATE POLICY users_update_own_{number} ON users FOR UPDATE TO {quoted} "
            f"USING ({mine}) WITH CHECK ({mine})"
        )
        op.execute(
            f"CREATE POLICY users_insert_first_login_{number} ON users FOR INSERT TO {quoted} "
            "WITH CHECK (auth_subject = app_auth_subject() "
            "AND status IN ('PENDING_VERIFICATION','ACTIVE') AND status_changed_by IS NULL)"
        )
    for number, role in enumerate(worker_roles):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT ON users TO {quoted}")
        op.execute(f"GRANT UPDATE ({STATUS_UPDATE_COLUMNS}) ON users TO {quoted}")
        op.execute(
            f"CREATE POLICY users_system_read_{number} ON users FOR SELECT TO {quoted} USING (true)"
        )
        op.execute(
            f"CREATE POLICY users_system_status_{number} ON users FOR UPDATE TO {quoted} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP FUNCTION IF EXISTS users_never_deleted()")
    op.execute("DROP FUNCTION IF EXISTS users_guard()")
