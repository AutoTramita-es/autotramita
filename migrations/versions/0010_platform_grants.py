"""Platform grants (F2-T10; AT-02 section 8, decisions D28, D29, D30, I14).

A platform grant is the only source of a central (cross-tenant) privilege. It is read from the
database on every request; nothing about it ever comes from a token. Rules kept by the database
itself, not only by the service layer:

* a closed catalog of five types, a scope that only the verification reviewer may narrow, a
  mandatory expiry (at most 365 days, the verification reviewer 90 days, a bootstrap grant 90);
* nobody grants to themselves; for ``PLATFORM_GRANT_ADMIN`` and ``PLATFORM_USER_ADMIN`` a second
  administrator approves (four eyes: approver is neither the requester nor the beneficiary);
  a grant takes effect at once only for a type its grantor holds and that needs no four eyes;
* only an active account receives a grant; after activation the only change is the
  revocation; a revoked grant is final; rows are never deleted;
* the last active ``PLATFORM_GRANT_ADMIN`` cannot be revoked (anti-lockout, serialised);
* one live (pending or active) grant per person and type.

Visibility. ``platform_has_grant(type, tenant)`` (SQL, STABLE, SECURITY INVOKER) says whether the
person of ``app.user_id`` holds an active, unexpired grant; the policies of the platform role on
``users``, ``user_sessions`` and ``audit_events`` call it, so without a grant that role sees no row
there. A policy of ``platform_grants`` cannot call it: the function reads that very table and the
policy would recurse. Its own rows are visible to everybody holding the platform role; the rows
of others only inside a transaction in which the service layer verified and share-locked the
caller's own grant administrator grant and named it in ``app.grant_authority`` (the two-step
context of G5-02). Every write to the table is checked against ``platform_has_grant`` again by
the policies and the trigger, so the setting alone changes nothing.

The owner role (out of the application, DEV/CI bootstrap only, D30) gets three narrow policies:
read the one account named in ``app.bootstrap_email``, insert a bootstrap grant administrator
grant and its audit record. Tenant tables get nothing (F3a).

Revision ID: 0010
Revises: 0009
"""

from alembic import context, op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

GRANT_TYPES = (
    "'PLATFORM_GRANT_ADMIN','PLATFORM_USER_ADMIN','PLATFORM_AUDIT_VIEW',"
    "'PLATFORM_VERIFICATION_REVIEW','PLATFORM_ACCOUNT_RECOVERY'"
)
FOUR_EYES = "'PLATFORM_GRANT_ADMIN','PLATFORM_USER_ADMIN'"
REVOKE_REASONS = (
    "'NO_LONGER_NEEDED','ROLE_CHANGED','SECURITY_INCIDENT','WITHDRAWN','REJECTED','EXPIRED'"
)
GRANT_UPDATE_COLUMNS = (
    "status, approved_by, activated_at, revoked_at, revoked_by, revoke_reason, version"
)
USER_STATUS_COLUMNS = (
    "status, status_reason, status_changed_at, status_changed_by, updated_at, version"
)
SESSION_REVOKE_COLUMNS = "revoked_at, revoked_reason, revoked_by, version"
# A platform transaction carries a person and nothing else: no bootstrap proof, no tenant.
PLATFORM_CONTEXT = (
    "(app_user_id() IS NOT NULL AND app_auth_subject() IS NULL AND app_session_hash() IS NULL "
    "AND app_tenant_id() IS NULL AND cardinality(app_branch_ids()) = 0)"
)
# Serialises every revocation of an active grant administrator grant (anti-lockout).
LOCKOUT_LOCK = 7_100_010


def _quote(role: str) -> str:
    return '"' + role.replace('"', '""') + '"'


def _role(kind: str) -> str:
    """The explicitly configured role of this kind (R07), verified by ``env.py``."""
    if kind == "owner":
        return _quote(str(op.get_bind().exec_driver_sql("SELECT current_user").scalar_one()))
    return _quote(context.config.attributes["expected_runtime_roles"][kind])


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE platform_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users (id),
            grant_type text NOT NULL CHECK (grant_type IN ({GRANT_TYPES})),
            scope_kind text NOT NULL DEFAULT 'ALL' CHECK (scope_kind IN ('ALL','TENANTS','QUEUE')),
            scope_tenant_ids uuid[],
            queue text CHECK (queue IS NULL OR queue ~ '^[A-Z][A-Z0-9_]{{0,39}}$'),
            status text NOT NULL CHECK (status IN ('PENDING_APPROVAL','ACTIVE','REVOKED')),
            expires_at timestamptz NOT NULL,
            granted_by uuid REFERENCES users (id),
            approved_by uuid REFERENCES users (id),
            reason text NOT NULL CHECK (
                length(reason) BETWEEN 3 AND 200 AND reason !~ '[[:cntrl:]]'),
            created_at timestamptz NOT NULL DEFAULT now(),
            activated_at timestamptz,
            revoked_at timestamptz,
            revoked_by uuid REFERENCES users (id),
            revoke_reason text CHECK (revoke_reason IS NULL OR revoke_reason IN ({REVOKE_REASONS})),
            version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            CONSTRAINT platform_grants_not_self CHECK (granted_by IS NULL OR granted_by <> user_id),
            CONSTRAINT platform_grants_independent_approver CHECK (
                approved_by IS NULL OR (
                    granted_by IS NOT NULL AND approved_by <> user_id
                    AND approved_by <> granted_by)),
            CONSTRAINT platform_grants_four_eyes CHECK (
                status <> 'ACTIVE' OR grant_type NOT IN ({FOUR_EYES}) OR granted_by IS NULL
                OR approved_by IS NOT NULL),
            CONSTRAINT platform_grants_bootstrap CHECK (
                granted_by IS NOT NULL OR (
                    grant_type = 'PLATFORM_GRANT_ADMIN' AND reason = 'bootstrap'
                    AND approved_by IS NULL AND expires_at <= created_at + interval '90 days')),
            CONSTRAINT platform_grants_lifetime CHECK (
                expires_at > created_at AND expires_at <= created_at + CASE
                    WHEN grant_type = 'PLATFORM_VERIFICATION_REVIEW' THEN interval '90 days'
                    ELSE interval '365 days' END),
            CONSTRAINT platform_grants_scope CHECK (
                (scope_kind = 'ALL' AND scope_tenant_ids IS NULL AND queue IS NULL)
                OR (scope_kind = 'TENANTS' AND grant_type = 'PLATFORM_VERIFICATION_REVIEW'
                    AND cardinality(scope_tenant_ids) BETWEEN 1 AND 100 AND queue IS NULL)
                OR (scope_kind = 'QUEUE' AND grant_type = 'PLATFORM_VERIFICATION_REVIEW'
                    AND queue IS NOT NULL AND scope_tenant_ids IS NULL)),
            CONSTRAINT platform_grants_activation CHECK (
                (status <> 'PENDING_APPROVAL' OR activated_at IS NULL)
                AND (status <> 'ACTIVE' OR activated_at IS NOT NULL)),
            CONSTRAINT platform_grants_revocation CHECK (
                (status = 'REVOKED') = (revoked_at IS NOT NULL)
                AND (revoked_at IS NULL) = (revoke_reason IS NULL)
                AND (revoked_at IS NULL) = (revoked_by IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX platform_grants_live ON platform_grants (user_id, grant_type) "
        "WHERE status IN ('PENDING_APPROVAL','ACTIVE')"
    )
    op.execute(
        "CREATE INDEX platform_grants_active ON platform_grants (user_id, grant_type, expires_at) "
        "WHERE status = 'ACTIVE'"
    )
    op.execute("CREATE INDEX platform_grants_created ON platform_grants (created_at DESC, id)")
    op.execute("ALTER TABLE platform_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_grants FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE FUNCTION app_grant_authority() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.grant_authority', true), '')::uuid $$"
    )
    op.execute(
        """
        CREATE FUNCTION platform_has_grant(kind text, tenant uuid DEFAULT NULL)
        RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER AS $$
            SELECT @CONTEXT@ AND EXISTS (
                SELECT 1 FROM platform_grants g
                WHERE g.user_id = app_user_id() AND g.grant_type = kind
                  AND g.status = 'ACTIVE' AND g.expires_at > now()
                  AND (g.scope_kind = 'ALL'
                       OR (tenant IS NOT NULL AND g.scope_kind = 'TENANTS'
                           AND tenant = ANY (g.scope_tenant_ids))))
        $$
        """.replace("@CONTEXT@", PLATFORM_CONTEXT)
    )

    # --- triggers: shape on insert, transitions on update, anti-lockout, no delete -------------
    op.execute(
        f"""
        CREATE FUNCTION platform_grants_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.created_at := now();
            NEW.version := 1;
            NEW.approved_by := NULL;
            IF NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL
               OR NEW.revoke_reason IS NOT NULL OR NEW.status = 'REVOKED' THEN
                RAISE EXCEPTION 'a grant is created pending or active' USING ERRCODE = '23514';
            END IF;
            IF NEW.expires_at <= now() THEN
                RAISE EXCEPTION 'a grant must expire in the future' USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'ACTIVE' THEN
                NEW.activated_at := now();
                -- At once only a bootstrap grant, or a type the grantor holds itself and that
                -- needs no second administrator.
                IF NEW.granted_by IS NOT NULL AND (
                    NEW.grant_type IN ({FOUR_EYES}) OR NEW.granted_by <> app_user_id()
                    OR NOT platform_has_grant(NEW.grant_type)) THEN
                    RAISE EXCEPTION 'this grant needs the approval of a second administrator'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                NEW.activated_at := NULL;
                IF NEW.granted_by IS NULL THEN
                    RAISE EXCEPTION 'a bootstrap grant is active at once' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_grants_update_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.grant_type IS DISTINCT FROM OLD.grant_type
               OR NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
               OR NEW.scope_tenant_ids IS DISTINCT FROM OLD.scope_tenant_ids
               OR NEW.queue IS DISTINCT FROM OLD.queue
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.granted_by IS DISTINCT FROM OLD.granted_by
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'immutable grant column' USING ERRCODE = '23514';
            END IF;
            IF OLD.status = 'REVOKED' THEN
                RAISE EXCEPTION 'a revoked grant is final' USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'ACTIVE' AND OLD.status = 'PENDING_APPROVAL' THEN
                IF NEW.approved_by IS NULL OR NEW.approved_by IS DISTINCT FROM app_user_id()
                   OR NEW.revoked_at IS NOT NULL OR OLD.expires_at <= now() THEN
                    RAISE EXCEPTION 'invalid approval' USING ERRCODE = '23514';
                END IF;
                NEW.activated_at := now();
            ELSIF NEW.status = 'REVOKED' THEN
                IF NEW.revoked_by IS NULL OR NEW.revoked_by IS DISTINCT FROM app_user_id()
                   OR NEW.revoke_reason IS NULL
                   OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   OR NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
                    RAISE EXCEPTION 'invalid revocation' USING ERRCODE = '23514';
                END IF;
                NEW.revoked_at := now();
                IF OLD.status = 'ACTIVE' AND OLD.grant_type = 'PLATFORM_GRANT_ADMIN'
                   AND OLD.expires_at > now() THEN
                    PERFORM pg_advisory_xact_lock(@LOCK@);
                    IF NOT EXISTS (
                        SELECT 1 FROM platform_grants g
                        WHERE g.grant_type = 'PLATFORM_GRANT_ADMIN' AND g.status = 'ACTIVE'
                          AND g.expires_at > now() AND g.user_id <> OLD.user_id) THEN
                        RAISE EXCEPTION 'the last grant administrator cannot be revoked'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
            ELSE
                RAISE EXCEPTION 'invalid grant transition' USING ERRCODE = '23514';
            END IF;
            NEW.version := OLD.version + 1;
            RETURN NEW;
        END $$
        """.replace("@LOCK@", str(LOCKOUT_LOCK))
    )
    # Only an active account receives a grant. Runs after the row exists, so the platform role
    # sees the beneficiary through its own policy (the subject of a grant).
    op.execute(
        """
        CREATE FUNCTION platform_grants_beneficiary() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id = NEW.user_id AND u.status = 'ACTIVE')
            THEN
                RAISE EXCEPTION 'a grant needs an active account' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER platform_grants_insert_guard BEFORE INSERT ON platform_grants "
        "FOR EACH ROW EXECUTE FUNCTION platform_grants_insert_guard()"
    )
    op.execute(
        "CREATE TRIGGER platform_grants_update_guard BEFORE UPDATE ON platform_grants "
        "FOR EACH ROW EXECUTE FUNCTION platform_grants_update_guard()"
    )
    op.execute(
        "CREATE TRIGGER platform_grants_beneficiary_created AFTER INSERT ON platform_grants "
        "FOR EACH ROW EXECUTE FUNCTION platform_grants_beneficiary()"
    )
    op.execute(
        "CREATE TRIGGER platform_grants_beneficiary_activated AFTER UPDATE ON platform_grants "
        "FOR EACH ROW WHEN (NEW.status = 'ACTIVE' AND OLD.status = 'PENDING_APPROVAL') "
        "EXECUTE FUNCTION platform_grants_beneficiary()"
    )
    op.execute(
        "CREATE FUNCTION platform_grants_never_deleted() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'grants are never deleted' USING ERRCODE = '42501'; END $$"
    )
    op.execute(
        "CREATE TRIGGER platform_grants_no_delete BEFORE DELETE ON platform_grants "
        "FOR EACH ROW EXECUTE FUNCTION platform_grants_never_deleted()"
    )
    op.execute(
        "CREATE TRIGGER platform_grants_no_truncate BEFORE TRUNCATE ON platform_grants "
        "FOR EACH STATEMENT EXECUTE FUNCTION platform_grants_never_deleted()"
    )

    app, worker, platform, owner = _role("app"), _role("worker"), _role("platform"), _role("owner")
    # Default privileges gave app and worker DML: start from nothing. App and worker get none.
    for role in (app, worker, platform):
        op.execute(f"REVOKE ALL ON platform_grants FROM {role}")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION platform_has_grant(text, uuid), app_grant_authority() "
        f"TO {platform}"
    )
    op.execute(f"GRANT SELECT, INSERT ON platform_grants TO {platform}")
    op.execute(f"GRANT UPDATE ({GRANT_UPDATE_COLUMNS}) ON platform_grants TO {platform}")

    authority = (
        f"{PLATFORM_CONTEXT} AND (user_id = app_user_id() OR app_grant_authority() IS NOT NULL)"
    )
    administrator = f"{PLATFORM_CONTEXT} AND platform_has_grant('PLATFORM_GRANT_ADMIN')"
    op.execute(
        f"CREATE POLICY grants_platform_read ON platform_grants FOR SELECT TO {platform} "
        f"USING ({authority})"
    )
    op.execute(
        f"CREATE POLICY grants_platform_request ON platform_grants FOR INSERT TO {platform} "
        f"WITH CHECK ({administrator} AND granted_by = app_user_id() "
        "AND user_id <> app_user_id())"
    )
    # Own rows are lockable by every holder (FOR SHARE needs the UPDATE policy); a change
    # needs the grant administrator grant.
    op.execute(
        f"CREATE POLICY grants_platform_change ON platform_grants FOR UPDATE TO {platform} "
        f"USING ({authority}) WITH CHECK ({administrator})"
    )
    op.execute(
        f"CREATE POLICY grants_bootstrap_read ON platform_grants FOR SELECT TO {owner} "
        "USING (granted_by IS NULL)"
    )
    op.execute(
        f"CREATE POLICY grants_bootstrap_insert ON platform_grants FOR INSERT TO {owner} "
        "WITH CHECK (granted_by IS NULL AND status = 'ACTIVE' "
        "AND grant_type = 'PLATFORM_GRANT_ADMIN' AND reason = 'bootstrap')"
    )

    # --- users: user administrators read and change status; grant administrators see the
    # people a grant names. Tenant tables get nothing (F3a). ---------------------------------
    op.execute(f"GRANT SELECT ON users TO {platform}")
    op.execute(f"GRANT UPDATE ({USER_STATUS_COLUMNS}) ON users TO {platform}")
    user_admin = f"{PLATFORM_CONTEXT} AND platform_has_grant('PLATFORM_USER_ADMIN')"
    op.execute(
        f"CREATE POLICY users_platform_read ON users FOR SELECT TO {platform} USING ({user_admin} "  # noqa: S608
        f"OR ({administrator} AND EXISTS "
        "(SELECT 1 FROM platform_grants g WHERE g.user_id = users.id)))"
    )
    op.execute(
        f"CREATE POLICY users_platform_status ON users FOR UPDATE TO {platform} "
        f"USING ({user_admin}) WITH CHECK ({user_admin})"
    )
    op.execute(
        f"CREATE POLICY users_bootstrap_read ON users FOR SELECT TO {owner} "
        "USING (email_normalized = nullif(current_setting('app.bootstrap_email', true), ''))"
    )

    # --- sessions: user administrators read and revoke ------------------------------------
    op.execute(f"GRANT SELECT ON user_sessions TO {platform}")
    op.execute(f"GRANT UPDATE ({SESSION_REVOKE_COLUMNS}) ON user_sessions TO {platform}")
    op.execute(
        f"CREATE POLICY sessions_platform_read ON user_sessions FOR SELECT TO {platform} "
        f"USING ({user_admin})"
    )
    op.execute(
        f"CREATE POLICY sessions_platform_revoke ON user_sessions FOR UPDATE TO {platform} "
        f"USING ({user_admin}) WITH CHECK ({user_admin})"
    )

    # --- audit: auditors read; every use of a grant is written in the same transaction ------
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {platform}")
    op.execute(
        f"CREATE POLICY audit_platform_read ON audit_events FOR SELECT TO {platform} "
        f"USING ({PLATFORM_CONTEXT} AND platform_has_grant('PLATFORM_AUDIT_VIEW'))"
    )
    op.execute(
        f"CREATE POLICY audit_platform_insert ON audit_events FOR INSERT TO {platform} "
        f"WITH CHECK ({PLATFORM_CONTEXT} AND source = 'APP' AND scope = 'PLATFORM' "
        "AND category = 'AUTHZ' AND actor_type = 'USER' AND actor_user_id = app_user_id() "
        "AND tenant_id IS NULL AND branch_id IS NULL)"
    )
    op.execute(
        f"CREATE POLICY audit_bootstrap_insert ON audit_events FOR INSERT TO {owner} "
        "WITH CHECK (source = 'APP' AND scope = 'PLATFORM' AND actor_type = 'SYSTEM' "
        "AND actor_user_id IS NULL AND actor_session_id IS NULL "
        "AND action = 'authz.platform_grant.activated' AND reason_code = 'BOOTSTRAP')"
    )


def downgrade() -> None:
    platform = _role("platform")
    for policy, table in (
        ("audit_bootstrap_insert", "audit_events"),
        ("audit_platform_insert", "audit_events"),
        ("audit_platform_read", "audit_events"),
        ("sessions_platform_revoke", "user_sessions"),
        ("sessions_platform_read", "user_sessions"),
        ("users_bootstrap_read", "users"),
        ("users_platform_status", "users"),
        ("users_platform_read", "users"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    for table in ("audit_events", "user_sessions", "users"):
        op.execute(f"REVOKE ALL ON {table} FROM {platform}")
    op.execute("DROP TABLE IF EXISTS platform_grants")
    for function in (
        "platform_grants_never_deleted()",
        "platform_grants_beneficiary()",
        "platform_grants_update_guard()",
        "platform_grants_insert_guard()",
        "platform_has_grant(text, uuid)",
        "app_grant_authority()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
