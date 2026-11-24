"""Durable, narrowly scoped email-change operations and notification jobs.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _roles(suffix: str) -> list[str]:
    return [
        row[0]
        for row in op.get_bind().exec_driver_sql(
            "SELECT rolname FROM pg_roles WHERE rolname ~ %s "
            "AND has_database_privilege(rolname, current_database(), 'CONNECT')",
            (f"_{suffix}$",),
        )
    ]


def _quote(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def upgrade() -> None:
    op.execute("""
        CREATE TABLE email_change_operations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id),
            session_id uuid NOT NULL REFERENCES user_sessions(id),
            old_email text,
            new_email text,
            new_email_normalized text,
            token_hash bytea,
            token_issued_at timestamptz,
            token_expires_at timestamptz,
            status text NOT NULL DEFAULT 'PENDING' CHECK (status IN
                ('PENDING', 'CONFIRMED', 'APPLYING', 'COMPLETED', 'CANCELLED',
                 'EXPIRED', 'MANUAL_REVIEW')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            confirmed_at timestamptz,
            completed_at timestamptz,
            next_attempt_at timestamptz,
            lease_id uuid,
            lease_until timestamptz,
            CHECK ((lease_id IS NULL) = (lease_until IS NULL)),
            CHECK (token_hash IS NULL OR octet_length(token_hash) = 32),
            CHECK ((token_hash IS NULL AND token_issued_at IS NULL AND token_expires_at IS NULL)
                OR (token_hash IS NOT NULL AND token_issued_at IS NOT NULL
                    AND token_expires_at = token_issued_at + interval '30 minutes')),
            CHECK ((status = 'PENDING') = (token_hash IS NOT NULL)),
            CHECK (status NOT IN ('CONFIRMED', 'APPLYING', 'COMPLETED')
                OR confirmed_at IS NOT NULL),
            CHECK ((status = 'COMPLETED') = (completed_at IS NOT NULL)),
            CHECK (status IN ('COMPLETED', 'CANCELLED', 'EXPIRED') OR
                (old_email IS NOT NULL AND new_email IS NOT NULL
                 AND new_email_normalized IS NOT NULL)),
            CHECK (old_email IS NULL OR length(old_email) BETWEEN 3 AND 320),
            CHECK (new_email IS NULL OR length(new_email) BETWEEN 3 AND 320),
            CHECK (new_email_normalized IS NULL OR length(new_email_normalized) BETWEEN 3 AND 320)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX email_change_active_user ON email_change_operations (user_id)
        WHERE status IN ('PENDING', 'CONFIRMED', 'APPLYING', 'MANUAL_REVIEW')
    """)
    op.execute("""
        CREATE UNIQUE INDEX email_change_active_address
        ON email_change_operations (new_email_normalized)
        WHERE status IN ('PENDING', 'CONFIRMED', 'APPLYING', 'MANUAL_REVIEW')
    """)
    op.execute("""
        CREATE INDEX email_change_recovery ON email_change_operations (next_attempt_at)
        WHERE status IN ('CONFIRMED', 'APPLYING')
    """)
    op.execute("""
        CREATE FUNCTION email_change_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'immutable email change identity' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'PENDING' AND NEW.status IN ('CONFIRMED','CANCELLED','EXPIRED'))
                OR (OLD.status = 'CONFIRMED' AND NEW.status IN ('APPLYING','MANUAL_REVIEW'))
                OR (OLD.status = 'APPLYING' AND NEW.status IN ('COMPLETED','MANUAL_REVIEW'))
            ) THEN
                RAISE EXCEPTION 'invalid email change transition' USING ERRCODE = '23514';
            END IF;
            IF (
                NEW.new_email IS DISTINCT FROM OLD.new_email OR
                NEW.new_email_normalized IS DISTINCT FROM OLD.new_email_normalized OR
                NEW.old_email IS DISTINCT FROM OLD.old_email
            ) AND NOT (NEW.status IN ('COMPLETED', 'CANCELLED', 'EXPIRED')
                AND NEW.old_email IS NULL AND NEW.new_email IS NULL
                AND NEW.new_email_normalized IS NULL) THEN
                RAISE EXCEPTION 'confirmed addresses are immutable' USING ERRCODE = '23514';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER email_change_guard BEFORE UPDATE ON email_change_operations
        FOR EACH ROW EXECUTE FUNCTION email_change_guard()
    """)
    op.execute("""
        CREATE TABLE email_change_notifications (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operation_id uuid NOT NULL REFERENCES email_change_operations(id),
            recipient_kind text NOT NULL CHECK (recipient_kind IN ('OLD', 'NEW')),
            recipient text,
            status text NOT NULL DEFAULT 'PENDING' CHECK (status IN
                ('PENDING', 'SENT', 'MANUAL_REVIEW')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            next_attempt_at timestamptz,
            lease_id uuid,
            lease_until timestamptz,
            UNIQUE (operation_id, recipient_kind),
            CHECK ((lease_id IS NULL) = (lease_until IS NULL)),
            CHECK (status = 'SENT' OR recipient IS NOT NULL),
            CHECK (recipient IS NULL OR length(recipient) BETWEEN 3 AND 320)
        )
    """)
    op.execute("""
        CREATE INDEX email_change_notice_recovery ON email_change_notifications (next_attempt_at)
        WHERE status = 'PENDING'
    """)
    for table in ("email_change_operations", "email_change_notifications"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        for role in (*_roles("app"), *_roles("worker"), *_roles("platform")):
            op.execute(f"REVOKE ALL ON {table} FROM {_quote(role)}")
    for number, role in enumerate(_roles("app")):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT ON email_change_operations TO {quoted}")
        op.execute(
            "GRANT INSERT (user_id, session_id, old_email, new_email, new_email_normalized, "
            f"token_hash, token_issued_at, token_expires_at) ON email_change_operations TO {quoted}"
        )
        op.execute(
            "GRANT UPDATE (status, token_hash, token_issued_at, token_expires_at, "
            f"confirmed_at, next_attempt_at) ON email_change_operations TO {quoted}"
        )
        op.execute(
            f"CREATE POLICY email_change_app_read_{number} ON email_change_operations "
            f"FOR SELECT TO {quoted} USING (user_id = app_user_id())"
        )
        op.execute(
            f"CREATE POLICY email_change_app_insert_{number} ON email_change_operations "  # noqa: S608
            f"FOR INSERT TO {quoted} WITH CHECK (user_id = app_user_id() AND EXISTS ("
            "SELECT 1 FROM user_sessions s WHERE s.id = session_id "
            "AND s.user_id = app_user_id() AND s.revoked_at IS NULL))"
        )
        op.execute(
            f"CREATE POLICY email_change_app_update_{number} ON email_change_operations "
            f"FOR UPDATE TO {quoted} USING (user_id = app_user_id() AND status = 'PENDING') "
            "WITH CHECK (user_id = app_user_id() AND "
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED'))"
        )
    for number, role in enumerate(_roles("worker")):
        quoted = _quote(role)
        op.execute(f"GRANT SELECT, DELETE ON email_change_operations TO {quoted}")
        op.execute(
            "GRANT UPDATE (status, old_email, new_email, new_email_normalized, token_hash, "
            "token_issued_at, token_expires_at, attempts, confirmed_at, completed_at, "
            f"next_attempt_at, lease_id, lease_until) ON email_change_operations TO {quoted}"
        )
        op.execute(f"GRANT SELECT, DELETE ON email_change_notifications TO {quoted}")
        op.execute(
            "GRANT INSERT (operation_id, recipient_kind, recipient) "
            f"ON email_change_notifications TO {quoted}"
        )
        op.execute(
            "GRANT UPDATE (recipient, status, attempts, updated_at, sent_at, next_attempt_at, "
            f"lease_id, lease_until) ON email_change_notifications TO {quoted}"
        )
        for table in ("email_change_operations", "email_change_notifications"):
            for action in ("SELECT", "UPDATE"):
                op.execute(
                    f"CREATE POLICY {table}_{action.lower()}_{number} ON {table} "
                    f"FOR {action} TO {quoted} USING (true)"
                )
            if table == "email_change_notifications":
                op.execute(
                    f"CREATE POLICY email_change_notifications_insert_{number} ON {table} "  # noqa: S608
                    f"FOR INSERT TO {quoted} WITH CHECK (EXISTS (SELECT 1 "
                    "FROM email_change_operations o WHERE o.id = operation_id "
                    "AND o.status = 'COMPLETED'))"
                )
            condition = (
                "status IN ('COMPLETED', 'CANCELLED', 'EXPIRED') "
                "AND updated_at < now() - interval '30 days'"
                if table == "email_change_operations"
                else "status = 'SENT' AND sent_at < now() - interval '30 days'"
            )
            op.execute(
                f"CREATE POLICY {table}_delete_{number} ON {table} "
                f"FOR DELETE TO {quoted} USING ({condition})"
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_change_notifications")
    op.execute("DROP TABLE IF EXISTS email_change_operations")
    op.execute("DROP FUNCTION IF EXISTS email_change_guard()")
